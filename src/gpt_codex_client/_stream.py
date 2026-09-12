from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

import httpx

from ._errors import StreamError, error_from_response
from ._response_state import ResponseState
from ._types import Response, ResponseStreamEvent


def parse_sse_lines(lines: Iterable[str]) -> Iterator[ResponseStreamEvent]:
    decoder = SSEDecoder()
    for raw_line in lines:
        event = decoder.feed_line(raw_line)
        if event is not None:
            yield event

    event = decoder.finish()
    if event is not None:
        yield event


class SSEDecoder:
    def __init__(self) -> None:
        self._event_type: str | None = None
        self._data_lines: list[str] = []

    def feed_line(self, raw_line: str) -> ResponseStreamEvent | None:
        line = raw_line.rstrip("\r\n")
        if not line:
            return self._flush()
        if line.startswith(":"):
            return None
        if line.startswith("event:"):
            self._event_type = line[6:].strip()
        elif line.startswith("data:"):
            self._data_lines.append(line[5:].lstrip())
        return None

    def finish(self) -> ResponseStreamEvent | None:
        return self._flush()

    def _flush(self) -> ResponseStreamEvent | None:
        if not self._data_lines:
            self._event_type = None
            return None
        event = _event_from_parts(self._event_type, self._data_lines)
        self._event_type = None
        self._data_lines = []
        return event


class ResponseStream:
    def __init__(self, manager: AbstractContextManager[httpx.Response]) -> None:
        self._manager = manager
        self._response: httpx.Response | None = None
        self._entered = False
        self._closed = False
        self._state = ResponseState()

    @property
    def final_response(self) -> Response | None:
        return self._state.final

    def __enter__(self) -> ResponseStream:
        if self._closed:
            raise StreamError("Stream is closed")
        if not self._entered:
            self._response = self._manager.__enter__()
            self._entered = True
            if self._response.status_code >= 400:
                try:
                    self._response.read()
                    raise error_from_response(self._response)
                finally:
                    self.close()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[ResponseStreamEvent]:
        if self._state.is_terminal():
            return
        if not self._entered:
            self.__enter__()
        if self._response is None or self._closed:
            raise StreamError("Stream is not open")
        try:
            for event in parse_sse_lines(self._response.iter_lines()):
                recorded = self._state.record(event)
                if self._state.is_terminal():
                    self.close()
                    yield recorded
                    return
                yield recorded
            self._state.fail("Stream ended before a terminal response", kind="truncated")
        except StreamError as error:
            if self._state.error is None:
                error.partial_response = self._state.snapshot()
                self._state.error = error
            raise
        except httpx.RequestError:
            self._state.fail("Response stream interrupted", kind="transport")
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._entered:
            self._manager.__exit__(None, None, None)

    def get_final_response(self) -> Response:
        return self._state.result()


def _event_from_parts(event_type: str | None, data_lines: list[str]) -> ResponseStreamEvent:
    data_text = "\n".join(data_lines)
    if data_text == "[DONE]":
        return ResponseStreamEvent(type="done", data={})
    try:
        parsed: Any = json.loads(data_text)
    except json.JSONDecodeError as exc:
        raise StreamError("Invalid SSE JSON", kind="protocol") from exc
    if not isinstance(parsed, dict):
        raise StreamError("SSE JSON must be an object", kind="protocol")
    resolved_type = event_type
    if resolved_type is None and isinstance(parsed.get("type"), str):
        resolved_type = parsed["type"]
    return ResponseStreamEvent(type=resolved_type or "message", data=parsed)


def stream_lines_from_bytes(chunks: Iterable[bytes]) -> Iterator[str]:
    buffer = ""
    for chunk in chunks:
        buffer += chunk.decode("utf-8")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line
    if buffer:
        yield buffer
