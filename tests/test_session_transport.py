from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import httpx
import pytest

from gpt_codex_client import AsyncCodexClient, CodexClient, Response, StreamError, Token
from gpt_codex_client import _websocket as ws
from gpt_codex_client._session_pool import Entry, SessionPool, plan_request

OUTPUT: list[dict[str, Any]] = [
    {"type": "reasoning", "id": "rs", "encrypted_content": "opaque", "summary": []},
    {"type": "function_call", "id": "fc", "call_id": "call", "name": "lookup", "arguments": "{}"},
]
RESULT = {"type": "function_call_output", "call_id": "call", "output": "ok"}
USER = {"role": "user", "content": "hi"}
COUNTS = {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 80}}


def completed(id: str = "resp", output: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": id,
            "model": "m",
            "status": "completed",
            "output": deepcopy(OUTPUT if output is None else output),
            "usage": COUNTS,
        },
    }


MISSING = {"type": "error", "error": {"code": "previous_response_not_found", "message": "missing"}}


class Socket:
    def __init__(self, scripts: list[list[Any]] | None = None) -> None:
        self.scripts = scripts or []
        self.frames: list[Any] = []
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.send_error: Exception | None = None

    def send(self, data: str) -> None:
        if self.closed:
            raise OSError("closed")
        self.sent.append(json.loads(data))
        if self.send_error:
            raise self.send_error
        self.frames = self.scripts.pop(0) if self.scripts else [completed()]

    def recv(self, timeout: float | None = None) -> str:
        if self.closed:
            raise OSError("closed")
        if not self.frames:
            raise OSError("EOF")
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return json.dumps(frame)

    def close(self) -> None:
        self.closed = True


class AsyncSocket:
    def __init__(self, socket: Socket) -> None:
        self.socket = socket

    async def send(self, data: str) -> None:
        self.socket.send(data)

    async def recv(self) -> str:
        return self.socket.recv()

    async def close(self) -> None:
        self.socket.close()


class Factory:
    def __init__(self, sockets: list[Socket] | None = None) -> None:
        self.pending = list(sockets or [])
        self.sockets: list[Socket] = []
        self.options: list[dict[str, Any]] = []

    def connect(self, url: str, **options: Any) -> Socket:
        assert url.startswith("wss://")
        self.options.append(options)
        socket = self.pending.pop(0) if self.pending else Socket()
        self.sockets.append(socket)
        return socket

    async def aconnect(self, url: str, **options: Any) -> AsyncSocket:
        return AsyncSocket(self.connect(url, **options))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ws,
            "connect_function",
            lambda asynchronous: self.aconnect if asynchronous else self.connect,
        )


def client_for(asynchronous: bool, **kwargs: Any) -> Any:
    client = AsyncCodexClient(**kwargs) if asynchronous else CodexClient(**kwargs)
    client._token = Token(access_token="test")
    return client


async def resolve(value: Any) -> Any:
    return await value if hasattr(value, "__await__") else value


async def shutdown(client: Any, asynchronous: bool) -> None:
    if asynchronous:
        await client.aclose()
    else:
        client.close()


async def consume(stream: Any, asynchronous: bool) -> list[Any]:
    if asynchronous:
        async with stream:
            return [item async for item in stream]
    with stream:
        return list(stream)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("chat", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_roundtrip(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, chat: bool, streaming: bool
) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    try:
        options = dict(
            model="m",
            session_id="s",
            prompt_cache_key="key",
            model_reasoning_effort="high",
            transport="websocket",
            preserve_context=True,
            stream=streaming,
        )
        if chat:
            first = await resolve(client.chat.completions.create(messages=[USER], **options))
        else:
            first = await resolve(client.responses.create(input=[USER], **options))
        if streaming:
            events = await consume(first, asynchronous)
            if chat:
                data = events[-1].choices[0].delta.provider_data
                assert events[-1].usage.cached_tokens == 80
            else:
                first = await resolve(first.get_final_response())
                data = first.provider_context()
        else:
            assert first.usage.input_tokens == 100
            data = first.choices[0].message.provider_data if chat else first.provider_context()
        if chat:
            assistant = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
                "provider_data": data,
            }
            second = await resolve(
                client.chat.completions.create(
                    messages=[
                        USER,
                        assistant,
                        {"role": "tool", "tool_call_id": "call", "content": "ok"},
                    ],
                    **options,
                )
            )
        else:
            second = await resolve(
                client.responses.create(input=[USER, *data["output_items"], RESULT], **options)
            )
        if streaming:
            await consume(second, asynchronous)
        assert len(factory.sockets) == 1
        frames = factory.sockets[0].sent
        assert "previous_response_id" not in frames[0]
        assert frames[1]["previous_response_id"] == "resp"
        assert frames[1]["input"] == [RESULT]
        assert frames[1]["store"] is False
        assert frames[0]["reasoning"] == frames[1]["reasoning"] == {"effort": "high"}
        assert "model_reasoning_effort" not in frames[1]
        assert factory.options[0]["additional_headers"]["session-id"] == "s"
        assert not factory.sockets[0].closed
    finally:
        await shutdown(client, asynchronous)
    assert factory.sockets[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("second_failure", [False, True])
async def test_missing_recovery(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, second_failure: bool
) -> None:
    original = Socket([[completed()], [MISSING]])
    fresh = Socket([[MISSING if second_failure else completed("new")]])
    factory = Factory([original, fresh])
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    opts = dict(model="m", transport="websocket", session_id="s")
    try:
        await resolve(client.responses.create(input=[USER], **opts))
        if second_failure:
            with pytest.raises(StreamError):
                await resolve(client.responses.create(input=[USER, *OUTPUT, RESULT], **opts))
        else:
            response = await resolve(client.responses.create(input=[USER, *OUTPUT, RESULT], **opts))
            assert response.id == "new"
        assert len(factory.sockets) == 2
        assert original.closed
        assert original.sent[1]["input"] == [RESULT]
        assert fresh.sent[0]["input"] == [USER, *OUTPUT, RESULT]
        assert "previous_response_id" not in fresh.sent[0]
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["send", "eof", "output_missing", "incomplete", "malformed"])
async def test_no_unsafe_replay(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, kind: str
) -> None:
    item = {"type": "response.output_item.added", "output_index": 0, "item": OUTPUT[1]}
    terminal = completed()
    terminal["type"] = "response.incomplete"
    terminal["response"]["status"] = "incomplete"
    scripts: dict[str, list[Any]] = {
        "send": [],
        "eof": [OSError("EOF")],
        "output_missing": [item, MISSING],
        "incomplete": [terminal],
        "malformed": [[1]],
    }
    socket = Socket([[completed()], scripts[kind]])
    factory = Factory([socket])
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    opts = dict(model="m", transport="auto", session_id="s")
    try:
        await resolve(client.responses.create(input=[USER], **opts))
        if kind == "send":
            socket.send_error = OSError("ambiguous")
        if kind == "incomplete":
            result = await resolve(client.responses.create(input=[USER, *OUTPUT, RESULT], **opts))
            assert result.status == "incomplete"
        else:
            with pytest.raises(StreamError):
                await resolve(client.responses.create(input=[USER, *OUTPUT, RESULT], **opts))
        assert len(factory.sockets) == 1
        assert socket.closed and not client._sessions.entries
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_busy_and_clear(monkeypatch: pytest.MonkeyPatch, asynchronous: bool) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(asynchronous, session_cache_max_size=1)
    opts = dict(model="m", input=[USER], transport="websocket", session_id="s", stream=True)
    try:
        first = await resolve(client.responses.create(**opts))
        await resolve(first.__aenter__() if asynchronous else first.__enter__())
        second = await resolve(client.responses.create(**opts))
        await consume(second, asynchronous)
        assert len(factory.sockets) == 2 and factory.sockets[1].closed
        assert "previous_response_id" not in factory.sockets[1].sent[0]
        assert len(client._sessions.entries) == 1
        await resolve(client.aclose_session("s") if asynchronous else client.close_session("s"))
        with pytest.raises(StreamError):
            await consume(first, asynchronous)
        assert factory.sockets[0].closed and not client._sessions.entries
        await resolve(
            client.aclose_session("unknown") if asynchronous else client.close_session("unknown")
        )
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_manual_one_shot(monkeypatch: pytest.MonkeyPatch, asynchronous: bool) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    try:
        for _ in range(2):
            await resolve(
                client.responses.create(
                    model="m",
                    input=[RESULT],
                    transport="websocket",
                    session_id="s",
                    previous_response_id="manual",
                )
            )
        assert len(factory.sockets) == 2
        assert all(
            s.closed and s.sent[0]["previous_response_id"] == "manual" for s in factory.sockets
        )
        assert not client._sessions.entries
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("transport", ["auto", "websocket"])
async def test_missing_dependency(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, transport: str
) -> None:
    real_import = importlib.import_module

    def missing(name: str) -> Any:
        if name.startswith("websockets"):
            raise ImportError("missing")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", missing)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(completed())}\n\n")

    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(handler)
    )
    client = client_for(asynchronous, http_client=http)
    try:
        if transport == "websocket":
            with pytest.raises(ws.ConnectFailure, match="Install"):
                await resolve(client.responses.create(model="m", input=[], transport=transport))
            assert not seen
        else:
            result = await resolve(
                client.responses.create(model="m", input=[], transport=transport)
            )
            assert result.usage.cached_tokens == 80 and len(seen) == 1
    finally:
        await shutdown(client, asynchronous)
        assert not http.is_closed
        await resolve(http.aclose() if asynchronous else http.close())


class Timer:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def test_pool_expiry_lru_and_generation() -> None:
    pool = SessionPool(1, 300)
    now = [0.0]
    pool.clock = lambda: now[0]
    timers: list[Timer] = []
    disposed: list[Entry] = []

    def schedule(delay: float, callback: Callable[[], None]) -> Timer:
        assert delay == 300
        timer = Timer(callback)
        timers.append(timer)
        return timer

    response = Response.from_dict(completed()["response"])
    body = {"input": [USER]}
    entry, _ = pool.reserve("s", "url")
    assert pool.release(entry, body, response)
    pool.schedule(entry, schedule, disposed.append)
    reused, _ = pool.reserve("s", "url")
    assert reused is entry and timers[0].cancelled
    timers[0].callback()
    assert entry.valid
    assert pool.release(entry, body, response)
    pool.schedule(entry, schedule, disposed.append)
    now[0] = 301
    timers[1].callback()
    assert not pool.entries and disposed == [entry]
    new, _ = pool.reserve("s", "url")
    assert pool.release(new, body, response)
    different, garbage = pool.reserve("other", "url")
    assert garbage == [new] and len(pool.entries) == 1
    oneshot, _ = pool.reserve("third", "url")
    assert oneshot not in pool.entries.values()
    assert pool.release(different, body, response)
    now[0] += 55 * 60
    fresh, garbage = pool.reserve("other", "url")
    assert fresh is not different and different in garbage
    _, garbage = pool.reserve("other", "newurl")
    assert fresh in garbage and not fresh.valid


def test_planner() -> None:
    body: dict[str, Any] = {"model": "m", "input": [USER], "tools": [{"a": 1, "b": True}]}
    entry = Entry(
        "s", "url", 0, 0, body=deepcopy(body), response_id="resp", output=deepcopy(OUTPUT)
    )
    current = {**body, "input": [USER, *OUTPUT, RESULT], "tools": [{"b": True, "a": 1}]}
    assert plan_request(entry, current)["input"] == [RESULT]
    assert plan_request(entry, {**current, "input": [USER, *OUTPUT]})["input"] == []
    current["tools"][0]["a"] = 1.0
    assert "previous_response_id" not in plan_request(entry, current)
    assert entry.response_id is None
    assert body["tools"][0]["a"] == 1


@pytest.mark.parametrize("size,ttl", [(-1, 300), (True, 300), (1, 0), (1, float("nan"))])
def test_invalid_pool_options(size: int, ttl: float) -> None:
    with pytest.raises(ValueError):
        SessionPool(size, ttl)


@pytest.mark.asyncio
async def test_async_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = Socket()

    class BlockingSocket(AsyncSocket):
        async def recv(self) -> str:
            await asyncio.Future[None]()
            raise AssertionError("unreachable")

    async def connect(url: str, **options: Any) -> BlockingSocket:
        return BlockingSocket(socket)

    monkeypatch.setattr(ws, "connect_function", lambda _: connect)
    client = client_for(True)
    try:
        stream = await client.responses.create(
            model="m", input=[], transport="websocket", session_id="s", stream=True
        )
        task = asyncio.create_task(consume(stream, True))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert socket.closed and not client._sessions.entries
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["connect", "business"])
async def test_handshake_boundary(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, failure: str
) -> None:
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response as HandshakeResponse

    from gpt_codex_client import AuthError

    error: Exception = (
        OSError("offline")
        if failure == "connect"
        else InvalidStatus(
            HandshakeResponse(403, "Forbidden", Headers(), b'{"error":{"message":"denied"}}')
        )
    )

    def connect(url: str, **kwargs: Any) -> Any:
        raise error

    async def aconnect(url: str, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(ws, "connect_function", lambda flag: aconnect if flag else connect)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(completed())}\n\n")

    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(handler)
    )
    client = client_for(asynchronous, http_client=http)
    try:
        if failure == "business":
            with pytest.raises(AuthError):
                await resolve(client.responses.create(model="m", input=[], transport="auto"))
            assert not seen
        else:
            result = await resolve(client.responses.create(model="m", input=[], transport="auto"))
            assert result.status == "completed" and len(seen) == 1
        assert not client._sessions.active
    finally:
        await shutdown(client, asynchronous)
        await resolve(http.aclose() if asynchronous else http.close())


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_clear_during_connect(monkeypatch: pytest.MonkeyPatch, asynchronous: bool) -> None:
    socket = Socket()
    client = client_for(asynchronous)

    def connect(url: str, **kwargs: Any) -> Socket:
        client.close_session("s")
        return socket

    async def aconnect(url: str, **kwargs: Any) -> AsyncSocket:
        await client.aclose_session("s")
        return AsyncSocket(socket)

    monkeypatch.setattr(ws, "connect_function", lambda flag: aconnect if flag else connect)
    try:
        with pytest.raises(StreamError, match="cleared"):
            await resolve(
                client.responses.create(model="m", input=[], transport="auto", session_id="s")
            )
        assert socket.closed and not socket.sent and not client._sessions.active
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_early_exit_and_complete_release(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    first = Socket([[{"type": "response.created", "response": {"id": "r"}}, completed()]])
    factory = Factory([first])
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    try:
        stream = await resolve(
            client.responses.create(
                model="m", input=[], transport="websocket", session_id="s", stream=True
            )
        )
        if asynchronous:
            async with stream:
                async for _ in stream:
                    break
        else:
            with stream:
                for _ in stream:
                    break
        assert first.closed and not client._sessions.entries
        stream = await resolve(
            client.responses.create(
                model="m", input=[], transport="websocket", session_id="s", stream=True
            )
        )
        if asynchronous:
            async with stream:
                async for event in stream:
                    assert event.type == "response.completed"
                    assert not client._sessions.entries["s"].busy
        else:
            with stream:
                for event in stream:
                    assert event.type == "response.completed"
                    assert not client._sessions.entries["s"].busy
        await resolve(client.aclose_session("s") if asynchronous else client.close_session("s"))
        await resolve(client.aclose_session("s") if asynchronous else client.close_session("s"))
        assert all(s.closed for s in factory.sockets)
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("options", [{}, {"session_id": "s", "session_cache_max_size": 0}])
async def test_no_persistent_session(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, options: dict[str, Any]
) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(
        asynchronous, session_cache_max_size=options.get("session_cache_max_size", 32)
    )
    try:
        for _ in range(2):
            await resolve(
                client.responses.create(
                    model="m", input=[], transport="websocket", session_id=options.get("session_id")
                )
            )
        assert not client._sessions.entries
        assert len(factory.sockets) == 2 and all(s.closed for s in factory.sockets)
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_changed_history_and_endpoint(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    opts = dict(model="m", transport="websocket", session_id="s")
    history = [deepcopy(USER)]
    try:
        await resolve(client.responses.create(input=history, **opts))
        history[0]["content"] = "edited"
        assert client._sessions.entries["s"].body["input"][0]["content"] == "hi"
        await resolve(client.responses.create(input=[*history, *OUTPUT, RESULT], **opts))
        assert "previous_response_id" not in factory.sockets[0].sent[1]
        client.base_url = "https://another.test/codex/"
        await resolve(client.responses.create(input=[], **opts))
        assert factory.sockets[0].closed and len(factory.sockets) == 2
        assert "previous_response_id" not in factory.sockets[1].sent[0]
    finally:
        await shutdown(client, asynchronous)


def test_frame_and_protocol_items() -> None:
    for frame in [b"not-json", "[]", "{}"]:
        with pytest.raises(StreamError):
            ws.decode_frame(frame)
    future = {"type": "future.event", "unknown": {"x": 1}}
    assert ws.decode_frame(json.dumps(future)).data == future


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_expiry_callback_closes_socket(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    factory = Factory()
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    callbacks: list[Callable[[], None]] = []
    original = client._sessions.schedule

    def fake_schedule(entry: Entry, ignored: Any, dispose: Callable[[Entry], None]) -> None:
        def timer(delay: float, callback: Callable[[], None]) -> Timer:
            callbacks.append(callback)
            return Timer(callback)

        original(entry, timer, dispose)

    monkeypatch.setattr(client._sessions, "schedule", fake_schedule)
    try:
        await resolve(
            client.responses.create(model="m", input=[], transport="websocket", session_id="s")
        )
        callbacks[0]()
        if asynchronous:
            await asyncio.gather(*client._ws_cleanup_tasks)
        assert factory.sockets[0].closed and not client._sessions.entries
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_failed_terminal_output_is_not_recovered(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    failure = {
        "type": "response.failed",
        "response": {"status": "failed", "output": OUTPUT, "error": MISSING["error"]},
    }
    factory = Factory([Socket([[completed()], [failure]])])
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    try:
        await resolve(
            client.responses.create(model="m", input=[USER], session_id="s", transport="websocket")
        )
        with pytest.raises(StreamError):
            await resolve(
                client.responses.create(
                    model="m", input=[USER, *OUTPUT, RESULT], session_id="s", transport="websocket"
                )
            )
        assert len(factory.sockets) == 1
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_websocket_parse_and_event_passthrough(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    output = [
        {
            "type": "message",
            "id": "msg",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "{}"}],
        }
    ]
    frames = [
        {"type": "future.event", "value": 1},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "message", "id": "msg", "content": []},
        },
        {"type": "response.output_text.delta", "item_id": "msg", "delta": "{}"},
        completed(output=output),
    ]
    factory = Factory([Socket([frames, [completed(output=output)]])])
    factory.install(monkeypatch)
    client = client_for(asynchronous)
    try:
        stream = await resolve(
            client.responses.create(
                model="m", input=[], transport="websocket", session_id="s", stream=True
            )
        )
        events = await consume(stream, asynchronous)
        assert events[0].type == "future.event" and events[0].data["value"] == 1
        assert events[-1].response.output_text == "{}"
        parsed = await resolve(
            client.responses.parse(
                model="m", input=[], text_format={}, transport="websocket", session_id="s"
            )
        )
        assert parsed.parsed == {} and parsed.response.usage.cached_tokens == 80
    finally:
        await shutdown(client, asynchronous)


@pytest.mark.parametrize("stage", ["send", "recv"])
async def test_async_io_timeout_releases_session(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    socket = Socket()
    cancelled = asyncio.Event()

    async def block() -> None:
        try:
            await asyncio.Future[None]()
        finally:
            cancelled.set()

    class TimedSocket(AsyncSocket):
        async def send(self, data: str) -> None:
            if stage == "send":
                await block()
            else:
                await super().send(data)

        async def recv(self) -> str:
            await block()
            raise AssertionError("unreachable")

    async def connect(url: str, **options: Any) -> TimedSocket:
        return TimedSocket(socket)

    monkeypatch.setattr(ws, "connect_function", lambda _: connect)
    client = client_for(True)
    try:
        with pytest.raises(StreamError, match="interrupted"):
            await client.responses.create(
                model="m", input=[], transport="websocket", session_id="s", timeout=0.01
            )
        assert cancelled.is_set()
        assert socket.closed and not client._sessions.entries
    finally:
        await client.aclose()
