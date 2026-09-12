from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from copy import deepcopy
from typing import Any

import httpx

from ._async_stream import AsyncResponseStream
from ._errors import APIConnectionError, StreamError, error_from_response
from ._session_pool import Entry, SessionPool, plan_request
from ._stream import ResponseStream
from ._types import JsonObject, Response, ResponseStreamEvent


class ConnectFailure(APIConnectionError):
    """The generation request has not been sent; auto may use SSE."""


def connection_options(headers: dict[str, str], timeout: float) -> dict[str, Any]:
    headers = {
        k.lower(): v
        for k, v in headers.items()
        if k.lower() not in {"accept", "content-type", "openai-beta"}
    }
    return dict(
        additional_headers=headers,
        user_agent_header=None,
        open_timeout=timeout,
        close_timeout=5,
        compression=None,
        max_size=None,
    )


def connect_function(asynchronous: bool) -> Any:
    try:
        module = importlib.import_module(
            "websockets.asyncio.client" if asynchronous else "websockets.sync.client"
        )
    except ImportError as exc:
        raise ConnectFailure(
            "Install gpt-codex-client[websocket] to use WebSocket transport"
        ) from exc
    return module.connect


def raise_connect_error(error: Exception) -> None:
    if isinstance(error, ConnectFailure):
        raise error
    # Any HTTP handshake rejection is surfaced, rather than bypassing a business rejection.
    response = getattr(error, "response", None)
    if response is not None and hasattr(response, "status_code"):
        raise error_from_response(
            httpx.Response(
                response.status_code, headers=dict(response.headers), content=response.body
            )
        ) from error
    if isinstance(error, OSError | TimeoutError) or type(error).__name__ in {
        "InvalidHandshake",
        "InvalidMessage",
        "SecurityError",
    }:
        raise ConnectFailure("WebSocket connection failed before request submission") from error
    raise error


def connect_sync(url: str, headers: dict[str, str], timeout: float) -> Any:
    try:
        return connect_function(False)(url, **connection_options(headers, timeout))
    except Exception as exc:
        raise_connect_error(exc)


async def connect_async(url: str, headers: dict[str, str], timeout: float) -> Any:
    try:
        return await connect_function(True)(url, **connection_options(headers, timeout))
    except Exception as exc:
        raise_connect_error(exc)


def decode_frame(frame: Any) -> ResponseStreamEvent:
    try:
        data = json.loads(frame)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise StreamError("Invalid WebSocket JSON", kind="protocol") from exc
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise StreamError("Invalid WebSocket event", kind="protocol")
    return ResponseStreamEvent(type=data["type"], data=data)


def missing_continuation(event: ResponseStreamEvent) -> bool:
    data = event.data
    response = data.get("response")
    error = response.get("error") if isinstance(response, dict) else data.get("error", data)
    return (
        not (isinstance(response, dict) and response.get("output"))
        and event.type in {"error", "response.failed", "response.done"}
        and isinstance(error, dict)
        and error.get("code") == "previous_response_not_found"
    )


def generation_event(event: ResponseStreamEvent) -> bool:
    # Only lifecycle acknowledgements are safe to ignore before a missing-state rejection.
    response = event.data.get("response")
    return bool(isinstance(response, dict) and response.get("output")) or event.type not in {
        "response.created",
        "response.in_progress",
    }


def close_socket(entry: Entry) -> None:
    if entry.socket is not None:
        with contextlib.suppress(Exception):
            entry.socket.close()


async def aclose_socket(entry: Entry) -> None:
    if entry.socket is not None:
        with contextlib.suppress(Exception):
            await entry.socket.close()


def schedule_timer(delay: float, callback: Callable[[], None]) -> threading.Timer:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class WebSocketSource:
    def __init__(
        self,
        pool: SessionPool,
        url: str,
        headers: dict[str, str],
        body: JsonObject,
        session_id: str | None,
        timeout: float,
        transport: str,
        fallback: Callable[[], ResponseStream],
        connector: Callable[[str, dict[str, str], float], Any] = connect_sync,
    ) -> None:
        self.pool, self.url, self.headers = pool, url, headers
        self.body, self.session_id = deepcopy(body), session_id
        self.timeout, self.transport, self.fallback = timeout, transport, fallback
        self.connector = connector
        self.entry: Entry | None = None
        self.request: JsonObject = {}
        self.sse: ResponseStream | None = None
        self.closed = False

    def _acquire(self) -> None:
        entry, garbage = self.pool.reserve(
            self.session_id, self.url, manual=self.body.get("previous_response_id") is not None
        )
        self.entry = entry
        for old in garbage:
            close_socket(old)
        try:
            if entry.socket is None:
                socket = self.connector(self.url, self.headers, self.timeout)
                if not self.pool.attach(entry, socket):
                    socket.close()
                    raise StreamError("Session was cleared during connection")
            self.request = plan_request(entry, self.body)
        except BaseException:
            self.pool.release(entry, self.body, None)
            close_socket(entry)
            raise

    def open(self) -> None:
        try:
            self._acquire()
        except ConnectFailure:
            if self.transport != "auto" or self.pool.closed:
                raise
            self.sse = self.fallback()
            self.sse.__enter__()

    def events(self) -> Iterator[ResponseStreamEvent]:
        if self.sse is not None:
            yield from self.sse
            return
        recovered = False
        while True:
            entry = self.entry
            assert entry is not None
            if not entry.valid:
                raise StreamError("Session was cleared", kind="transport")
            seen_output = False
            try:
                entry.socket.send(json.dumps({"type": "response.create", **self.request}))
                while True:
                    event = decode_frame(entry.socket.recv(timeout=self.timeout))
                    if not entry.valid:
                        raise StreamError("Session was cleared", kind="transport")
                    if (
                        missing_continuation(event)
                        and not seen_output
                        and not recovered
                        and self.request.get("previous_response_id") is not None
                        and self.body.get("previous_response_id") is None
                    ):
                        recovered = True
                        self.pool.release(entry, self.body, None)
                        close_socket(entry)
                        self._acquire()
                        break
                    seen_output = seen_output or generation_event(event)
                    yield event
            except StreamError:
                raise
            except Exception as exc:
                raise StreamError("WebSocket stream interrupted", kind="transport") from exc

    def close(self, response: Response | None) -> None:
        if self.closed:
            return
        self.closed = True
        if self.sse is not None:
            self.sse.close()
        elif self.entry is not None:
            if self.pool.release(self.entry, self.body, response):
                self.pool.schedule(self.entry, schedule_timer, close_socket)
            else:
                close_socket(self.entry)


class AsyncWebSocketSource:
    def __init__(
        self,
        pool: SessionPool,
        url: str,
        headers: dict[str, str],
        body: JsonObject,
        session_id: str | None,
        timeout: float,
        transport: str,
        fallback: Callable[[], Awaitable[AsyncResponseStream]],
        cleanup_tasks: set[asyncio.Task[None]],
        connector: Callable[[str, dict[str, str], float], Awaitable[Any]] = connect_async,
    ) -> None:
        self.pool, self.url, self.headers = pool, url, headers
        self.body, self.session_id = deepcopy(body), session_id
        self.timeout, self.transport, self.fallback = timeout, transport, fallback
        self.cleanup_tasks, self.connector = cleanup_tasks, connector
        self.entry: Entry | None = None
        self.request: JsonObject = {}
        self.sse: AsyncResponseStream | None = None
        self.closed = False

    async def _acquire(self) -> None:
        entry, garbage = self.pool.reserve(
            self.session_id, self.url, manual=self.body.get("previous_response_id") is not None
        )
        self.entry = entry
        try:
            for old in garbage:
                await aclose_socket(old)
            if entry.socket is None:
                socket = await self.connector(self.url, self.headers, self.timeout)
                if not self.pool.attach(entry, socket):
                    await socket.close()
                    raise StreamError("Session was cleared during connection")
            self.request = plan_request(entry, self.body)
        except BaseException:
            self.pool.release(entry, self.body, None)
            await aclose_socket(entry)
            raise

    async def open(self) -> None:
        try:
            await self._acquire()
        except ConnectFailure:
            if self.transport != "auto" or self.pool.closed:
                raise
            self.sse = await self.fallback()
            await self.sse.__aenter__()

    async def events(self) -> AsyncIterator[ResponseStreamEvent]:
        if self.sse is not None:
            async for event in self.sse:
                yield event
            return
        recovered = False
        while True:
            entry = self.entry
            assert entry is not None
            if not entry.valid:
                raise StreamError("Session was cleared", kind="transport")
            seen_output = False
            try:
                await asyncio.wait_for(
                    entry.socket.send(json.dumps({"type": "response.create", **self.request})),
                    timeout=self.timeout,
                )
                while True:
                    event = decode_frame(
                        await asyncio.wait_for(entry.socket.recv(), timeout=self.timeout)
                    )
                    if not entry.valid:
                        raise StreamError("Session was cleared", kind="transport")
                    if (
                        missing_continuation(event)
                        and not seen_output
                        and not recovered
                        and self.request.get("previous_response_id") is not None
                        and self.body.get("previous_response_id") is None
                    ):
                        recovered = True
                        self.pool.release(entry, self.body, None)
                        await aclose_socket(entry)
                        await self._acquire()
                        break
                    seen_output = seen_output or generation_event(event)
                    yield event
            except StreamError:
                raise
            except Exception as exc:
                raise StreamError("WebSocket stream interrupted", kind="transport") from exc

    def _dispose_later(self, entry: Entry) -> None:
        task = asyncio.create_task(aclose_socket(entry))
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.cleanup_tasks.discard)

    async def close(self, response: Response | None) -> None:
        if self.closed:
            return
        self.closed = True
        if self.sse is not None:
            await self.sse.aclose()
        elif self.entry is not None:
            if self.pool.release(self.entry, self.body, response):
                self.pool.schedule(
                    self.entry, asyncio.get_running_loop().call_later, self._dispose_later
                )
            else:
                await aclose_socket(self.entry)
