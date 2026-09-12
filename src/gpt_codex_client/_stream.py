from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

import httpx

from ._errors import StreamError, error_from_response
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
        self._output_text_parts: list[str] = []
        self.final_response: Response | None = None

    def __enter__(self) -> ResponseStream:
        if self._entered:
            return self
        self._response = self._manager.__enter__()
        self._entered = True
        if self._response.status_code >= 400:
            self._response.read()
            error = error_from_response(self._response)
            self.close()
            raise error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[ResponseStreamEvent]:
        close_when_done = False
        if not self._entered:
            self.__enter__()
            close_when_done = True
        if self._response is None:
            raise StreamError("Stream response is not open")
        try:
            for event in parse_sse_lines(self._response.iter_lines()):
                yield self._record_event(event)
        finally:
            if close_when_done:
                self.close()

    def close(self) -> None:
        if self._closed:
            return
        if not self._entered:
            self._closed = True
            return
        self._manager.__exit__(None, None, None)
        self._closed = True

    def get_final_response(self) -> Response:
        if self.final_response is None:
            self.final_response = Response(
                id=None,
                model=None,
                output_text="".join(self._output_text_parts),
                status=None,
                raw={},
            )
        return self.final_response

    def _record_event(self, event: ResponseStreamEvent) -> ResponseStreamEvent:
        delta = event.data.get("delta")
        if event.type == "response.output_text.delta" and isinstance(delta, str):
            self._output_text_parts.append(delta)

        response_payload = event.data.get("response")
        if isinstance(response_payload, dict):
            response = Response.from_dict(response_payload)
            if not response.output_text and self._output_text_parts:
                response.output_text = "".join(self._output_text_parts)
            event.response = response
            if event.type in {"response.completed", "response.incomplete"}:
                self.final_response = response
        elif event.type == "response.completed":
            self.final_response = Response(
                id=None,
                model=None,
                output_text="".join(self._output_text_parts),
                status="completed",
                raw=event.data,
            )
            event.response = self.final_response

        return event


def _event_from_parts(event_type: str | None, data_lines: list[str]) -> ResponseStreamEvent:
    data_text = "\n".join(data_lines)
    if data_text == "[DONE]":
        return ResponseStreamEvent(type="done", data={})
    try:
        parsed: Any = json.loads(data_text)
    except json.JSONDecodeError:
        parsed = {"data": data_text}
    if not isinstance(parsed, dict):
        parsed = {"data": parsed}
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
