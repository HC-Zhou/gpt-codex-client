from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType

import httpx

from ._errors import StreamError, error_from_response
from ._response_state import ResponseState
from ._stream import SSEDecoder
from ._types import Response, ResponseStreamEvent


async def _events(response: httpx.Response) -> AsyncIterator[ResponseStreamEvent]:
    decoder = SSEDecoder()
    async for line in response.aiter_lines():
        event = decoder.feed_line(line)
        if event is not None:
            yield event
    event = decoder.finish()
    if event is not None:
        yield event


class AsyncResponseStream:
    def __init__(self, manager: AbstractAsyncContextManager[httpx.Response]) -> None:
        self._manager = manager
        self._response: httpx.Response | None = None
        self._entered = False
        self._closed = False
        self._state = ResponseState()

    @property
    def final_response(self) -> Response | None:
        return self._state.final

    async def __aenter__(self) -> AsyncResponseStream:
        if self._closed:
            raise StreamError("Stream is closed")
        if not self._entered:
            self._response = await self._manager.__aenter__()
            self._entered = True
            if self._response.status_code >= 400:
                try:
                    await self._response.aread()
                    raise error_from_response(self._response)
                finally:
                    await self.aclose()
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

    async def _iterate(self) -> AsyncIterator[ResponseStreamEvent]:
        if self._state.is_terminal():
            return
        if not self._entered:
            await self.__aenter__()
        if self._response is None or self._closed:
            raise StreamError("Stream is not open")
        try:
            async for event in _events(self._response):
                recorded = self._state.record(event)
                if self._state.is_terminal():
                    await self.aclose()
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
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._entered:
            await self._manager.__aexit__(None, None, None)

    async def get_final_response(self) -> Response:
        return self._state.result()
