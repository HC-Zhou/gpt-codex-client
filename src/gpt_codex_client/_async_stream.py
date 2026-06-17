from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType

import httpx

from ._errors import StreamError, error_from_response
from ._stream import SSEDecoder
from ._types import Response, ResponseStreamEvent


class AsyncResponseStream:
    def __init__(self, manager: AbstractAsyncContextManager[httpx.Response]) -> None:
        self._manager = manager
        self._response: httpx.Response | None = None
        self._entered = False
        self._closed = False
        self._output_text_parts: list[str] = []
        self.final_response: Response | None = None

    async def __aenter__(self) -> AsyncResponseStream:
        if self._entered:
            return self
        self._response = await self._manager.__aenter__()
        self._entered = True
        if self._response.status_code >= 400:
            error = error_from_response(self._response)
            await self.aclose()
            raise error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __aiter__(self) -> AsyncIterator[ResponseStreamEvent]:
        return self._iterate()

    async def aclose(self) -> None:
        if self._closed:
            return
        if not self._entered:
            self._closed = True
            return
        await self._manager.__aexit__(None, None, None)
        self._closed = True

    async def get_final_response(self) -> Response:
        if self.final_response is None:
            self.final_response = Response(
                id=None,
                model=None,
                output_text="".join(self._output_text_parts),
                status=None,
                raw={},
            )
        return self.final_response

    async def _iterate(self) -> AsyncIterator[ResponseStreamEvent]:
        close_when_done = False
        if not self._entered:
            await self.__aenter__()
            close_when_done = True
        if self._response is None:
            raise StreamError("Stream response is not open")
        decoder = SSEDecoder()
        try:
            async for line in self._response.aiter_lines():
                event = decoder.feed_line(line)
                if event is not None:
                    yield self._record_event(event)
            event = decoder.finish()
            if event is not None:
                yield self._record_event(event)
        finally:
            if close_when_done:
                await self.aclose()

    def _record_event(self, event: ResponseStreamEvent) -> ResponseStreamEvent:
        delta = event.data.get("delta")
        if event.type == "response.output_text.delta" and isinstance(delta, str):
            self._output_text_parts.append(delta)

        response_payload = event.data.get("response")
        if isinstance(response_payload, dict):
            response = Response.from_dict(response_payload)
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
