from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol

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


class AsyncEventSource(Protocol):
    async def open(self) -> None: ...
    def events(self) -> AsyncIterator[ResponseStreamEvent]: ...
    async def close(self, response: Response | None) -> None: ...


class AsyncResponseStream:
    def __init__(
        self,
        manager: AbstractAsyncContextManager[httpx.Response] | None = None,
        *,
        source: AsyncEventSource | None = None,
    ) -> None:
        self._manager = manager
        self._source = source
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
            if self._source is not None:
                await self._source.open()
                self._entered = True
                return self
            assert self._manager is not None
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
        if (self._response is None and self._source is None) or self._closed:
            raise StreamError("Stream is not open")
        try:
            if self._source is not None:
                events = self._source.events()
            else:
                assert self._response is not None
                events = _events(self._response)
            async for event in events:
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
        if self._entered and self._source is not None:
            await self._source.close(self._state.final)
        elif self._entered:
            assert self._manager is not None
            await self._manager.__aexit__(None, None, None)

    async def get_final_response(self) -> Response:
        return self._state.result()
