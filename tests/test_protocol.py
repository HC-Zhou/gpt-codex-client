from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest

from gpt_codex_client import AsyncCodexClient, CodexClient, StreamError, Token


def frame(kind: str, **data: Any) -> bytes:
    return ("data: " + json.dumps({"type": kind, **data}) + "\n\n").encode()


def terminal(status: str = "completed", **data: Any) -> bytes:
    return frame("response." + status, response={"id": "r", "model": "m", "status": status, **data})


class ControlledStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], ending: str = "eof") -> None:
        self.chunks = chunks
        self.ending = ending
        self.closed = 0

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks
        if self.ending == "disconnect":
            raise httpx.ReadError("disconnected")
        if self.ending == "open":
            raise AssertionError("Read beyond terminal event")

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self:
            yield chunk
        if self.ending == "cancel":
            raise asyncio.CancelledError

    def close(self) -> None:
        self.closed += 1

    async def aclose(self) -> None:
        self.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("ending", ["eof", "disconnect", "failed", "error", "open"])
async def test_lifecycle(asynchronous: bool, streaming: bool, ending: str) -> None:
    chunks = [frame("response.output_text.delta", delta="partial")]
    if ending == "open":
        chunks.append(terminal())
    elif ending == "failed":
        chunks.append(
            frame("response.failed", response={"error": {"code": "bad", "message": "failure"}})
        )
    elif ending == "error":
        chunks.append(frame("error", code="bad", message="failure"))
    wire = ControlledStream(chunks, ending)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=wire)

    async def consume() -> None:
        if asynchronous:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = AsyncCodexClient(http_client=http)
                client._token = Token(access_token="test")
                if streaming:
                    stream = await client.responses.create(model="m", input="hi", stream=True)
                    async with stream:
                        async for _ in stream:
                            pass
                        assert (await stream.get_final_response()).output_text == "partial"
                else:
                    assert (
                        await client.responses.create(model="m", input="hi")
                    ).output_text == "partial"
                assert not http.is_closed
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as http_sync:
                client_sync = CodexClient(http_client=http_sync)
                client_sync._token = Token(access_token="test")
                if streaming:
                    with client_sync.responses.create(
                        model="m", input="hi", stream=True
                    ) as sync_stream:
                        list(sync_stream)
                        assert sync_stream.get_final_response().output_text == "partial"
                else:
                    assert (
                        client_sync.responses.create(model="m", input="hi").output_text == "partial"
                    )
                assert not http_sync.is_closed

    if ending == "open":
        await consume()
    else:
        with pytest.raises(StreamError) as caught:
            await consume()
        assert caught.value.partial_response is not None
        assert caught.value.partial_response.output_text == "partial"
    assert wire.closed == 1
    assert calls == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "failure", ["connect", "timeout", "429", "503", "quota", "400", "exhausted", "no_retry"]
)
async def test_inference_retries(
    asynchronous: bool, streaming: bool, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    delays: list[float] = []

    def sleep(self: Any, attempt: int, delay: float) -> None:
        delays.append(delay)

    async def asleep(self: Any, attempt: int, delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(CodexClient, "_sleep_before_retry", sleep)
    monkeypatch.setattr(AsyncCodexClient, "_sleep_before_retry", asleep)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1 or failure == "exhausted":
            if failure == "connect":
                raise httpx.ConnectError("test")
            if failure == "timeout":
                raise httpx.ReadTimeout("headers")
            code = (
                400
                if failure == "400"
                else 503
                if failure in {"503", "exhausted", "no_retry"}
                else 429
            )
            return httpx.Response(
                code,
                headers={"retry-after-ms": "1"},
                json={
                    "error": {"code": "insufficient_quota" if failure == "quota" else "temporary"}
                },
            )
        return httpx.Response(200, content=terminal())

    async def consume() -> None:
        if asynchronous:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = AsyncCodexClient(
                    http_client=http, max_retries=0 if failure == "no_retry" else 1
                )
                client._token = Token(access_token="test")
                if streaming:
                    stream = await client.responses.create(model="m", input="hi", stream=True)
                    async with stream:
                        async for _ in stream:
                            pass
                else:
                    await client.responses.create(model="m", input="hi")
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as http_sync:
                client_sync = CodexClient(
                    http_client=http_sync, max_retries=0 if failure == "no_retry" else 1
                )
                client_sync._token = Token(access_token="test")
                if streaming:
                    with client_sync.responses.create(
                        model="m", input="hi", stream=True
                    ) as sync_stream:
                        list(sync_stream)
                else:
                    client_sync.responses.create(model="m", input="hi")

    from gpt_codex_client import APIError

    if failure in {"quota", "400", "exhausted", "no_retry"}:
        with pytest.raises(APIError):
            await consume()
    else:
        await consume()
    assert calls == (1 if failure in {"quota", "400", "no_retry"} else 2)
    assert len(delays) == calls - 1


def tool(index: int, arguments: str = "") -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": f"fc_{index}",
        "call_id": f"call_{index}",
        "name": f"tool_{index}",
        "arguments": arguments,
    }


def tool_frames() -> list[bytes]:
    return [
        frame("response.output_item.added", output_index=0, item=tool(0)),
        frame("response.output_item.added", output_index=1, item=tool(1)),
        frame("response.function_call_arguments.delta", output_index=1, delta="{"),
        frame("response.function_call_arguments.delta", output_index=0, delta='{"x":'),
        frame("response.function_call_arguments.delta", output_index=1, delta="}"),
        frame("response.function_call_arguments.delta", output_index=0, delta="1}"),
        frame("response.output_item.done", output_index=0, item=tool(0, '{"x":1}')),
        terminal(output=[tool(0, '{"x":1}'), tool(1, "{}")]),
    ]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("terminal_only", [False, True])
async def test_chat_tools_roundtrip(
    asynchronous: bool, streaming: bool, terminal_only: bool
) -> None:
    requests: list[dict[str, Any]] = []
    frames = tool_frames()
    if terminal_only:
        frames = frames[-1:]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b"".join(frames) if len(requests) == 1 else terminal())

    message: dict[str, Any]
    if asynchronous:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncCodexClient(http_client=http)
            client._token = Token(access_token="test")
            if streaming:
                stream = await client.chat.completions.create(model="m", messages=[], stream=True)
                chunks = [chunk async for chunk in stream]
                message = collect_chat(chunks)
            else:
                result = await client.chat.completions.create(model="m", messages=[])
                message = result.choices[0].message.to_dict()
                assert result.choices[0].finish_reason == "tool_calls"
            await client.chat.completions.create(
                model="m",
                messages=[
                    message,
                    {"role": "tool", "tool_call_id": "call_0", "content": "ok"},
                    {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
                ],
            )
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http_sync:
            sync = CodexClient(http_client=http_sync)
            sync._token = Token(access_token="test")
            if streaming:
                chunks = list(sync.chat.completions.create(model="m", messages=[], stream=True))
                message = collect_chat(chunks)
            else:
                result = sync.chat.completions.create(model="m", messages=[])
                message = result.choices[0].message.to_dict()
                assert result.choices[0].finish_reason == "tool_calls"
            sync.chat.completions.create(
                model="m",
                messages=[
                    message,
                    {"role": "tool", "tool_call_id": "call_0", "content": "ok"},
                    {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
                ],
            )
    assert requests[1]["input"] == [
        {"type": "function_call", "call_id": "call_0", "name": "tool_0", "arguments": '{"x":1}'},
        {"type": "function_call", "call_id": "call_1", "name": "tool_1", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_0", "output": "ok"},
        {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
    ]


def collect_chat(chunks: list[Any]) -> dict[str, Any]:
    calls: dict[int, dict[str, Any]] = {}
    message: dict[str, Any] = {"role": "assistant"}
    for chunk in chunks:
        delta = chunk.choices[0].delta
        if delta.content:
            message["content"] = message.get("content", "") + delta.content
        if delta.provider_data:
            message["provider_data"] = delta.provider_data
        for call in delta.tool_calls or []:
            current = calls.setdefault(
                call["index"], {"type": "function", "function": {"arguments": ""}}
            )
            if "id" in call:
                current["id"] = call["id"]
            if "name" in call["function"]:
                current["function"]["name"] = call["function"]["name"]
            current["function"]["arguments"] += call["function"].get("arguments", "")
    if calls:
        message["tool_calls"] = list(calls.values())
        assert chunks[-1].choices[0].finish_reason == "tool_calls"
    return message


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("chat", [False, True])
async def test_context_roundtrip(asynchronous: bool, streaming: bool, chat: bool) -> None:
    output = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-secret", "future": True},
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": "looking"}],
        },
        tool(0, "{}"),
    ]
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=terminal(output=output))

    # Exercise identical operations through both public clients; Any keeps the matrix compact.
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(handler)
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    resource = client.chat.completions if chat else client.responses

    async def invoke(**kwargs: Any) -> Any:
        result = resource.create(**kwargs)
        return await result if asynchronous else result

    try:
        result = await invoke(
            model="m",
            **({"messages": []} if chat else {"input": []}),
            preserve_context=True,
            include=["extra"],
            stream=streaming,
        )
        if streaming:
            chunks = [chunk async for chunk in result] if asynchronous else list(result)
            if chat:
                message = collect_chat(chunks)
            else:
                result = (
                    await result.get_final_response()
                    if asynchronous
                    else result.get_final_response()
                )
        if chat:
            if not streaming:
                message = result.choices[0].message.to_dict()
            assert message["content"] == "looking"
            assert "opaque-secret" not in message["content"]
            await invoke(
                model="m",
                messages=[message, {"role": "tool", "tool_call_id": "call_0", "content": "ok"}],
            )
        else:
            replay = result.to_input_items()
            assert replay == output
            replay[0]["future"] = False
            assert result.output[0]["future"] is True
            assert result.output_text == "looking"
            await invoke(
                model="m",
                input=[
                    *result.to_input_items(),
                    {"type": "function_call_output", "call_id": "call_0", "output": "ok"},
                ],
            )
        assert requests[0]["include"] == ["extra", "reasoning.encrypted_content"]
        assert requests[1]["input"] == [
            *output,
            {"type": "function_call_output", "call_id": "call_0", "output": "ok"},
        ]
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


@pytest.mark.parametrize("alteration", ["version", "provider", "model", "content", "tool_calls"])
def test_context_validation(alteration: str) -> None:
    from gpt_codex_client import ChatCompletion, Response
    from gpt_codex_client._converters import chat_messages_to_response_input

    response = Response.from_dict({"status": "completed", "model": "m", "output": [tool(0, "{}")]})
    message = (
        ChatCompletion.from_response(response, preserve_context=True).choices[0].message.to_dict()
    )
    if alteration in {"version", "provider", "model"}:
        message["provider_data"][alteration] = "other"
    else:
        message[alteration] = "edited"
    with pytest.raises(ValueError):
        chat_messages_to_response_input([message], model="m")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "reason,expected",
    [("max_output_tokens", "length"), ("content_filter", "content_filter"), ("other", None)],
)
async def test_chat_incomplete(
    asynchronous: bool, streaming: bool, reason: str, expected: str | None
) -> None:
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=terminal("incomplete", incomplete_details={"reason": reason})
            )
        )
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")

    async def consume() -> str:
        result = client.chat.completions.create(model="m", messages=[], stream=streaming)
        if asynchronous:
            result = await result
        if streaming:
            chunks = [chunk async for chunk in result] if asynchronous else list(result)
            return str(chunks[-1].choices[0].finish_reason)
        return str(result.choices[0].finish_reason)

    try:
        if expected is None:
            with pytest.raises(StreamError) as caught:
                await consume()
            assert caught.value.code == reason
        else:
            assert await consume() == expected
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "payload", [b"data: invalid\n\n", b"data: [DONE]\n\n", b"data: []\n\n", b""]
)
async def test_invalid_or_unterminated(asynchronous: bool, payload: bytes) -> None:
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        stream = client.responses.create(model="m", input="hi", stream=True)
        if asynchronous:
            stream = await stream
        with pytest.raises(StreamError):
            if asynchronous:
                await stream.get_final_response()
            else:
                stream.get_final_response()
        with pytest.raises(StreamError) as first:
            if asynchronous:
                async for _ in stream:
                    pass
            else:
                list(stream)
        with pytest.raises(StreamError) as second:
            if asynchronous:
                await stream.get_final_response()
            else:
                stream.get_final_response()
        assert first.value is second.value
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


async def test_cancellation_closes_stream() -> None:
    wire = ControlledStream([frame("response.output_text.delta", delta="partial")], "cancel")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=wire))
    ) as http:
        client = AsyncCodexClient(http_client=http)
        client._token = Token(access_token="test")
        with pytest.raises(asyncio.CancelledError):
            await client.responses.create(model="m", input="hi")
        assert wire.closed == 1
        assert not http.is_closed


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_early_exit_closes_once(asynchronous: bool) -> None:
    wire = ControlledStream([frame("response.output_text.delta", delta="partial")], "open")
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=wire))
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        stream = client.responses.create(model="m", input="hi", stream=True)
        if asynchronous:
            stream = await stream
            async with stream:
                async for _ in stream:
                    break
            await stream.aclose()
        else:
            with stream:
                next(iter(stream))
            stream.close()
        assert wire.closed == 1
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


def test_retry_headers_and_limit() -> None:
    import time
    from email.utils import formatdate

    from gpt_codex_client import APIError
    from gpt_codex_client._errors import error_from_response, retry_delay

    for headers, minimum, maximum in [
        ({"retry-after-ms": "1500"}, 1.5, 1.5),
        ({"retry-after": "2"}, 2, 2),
        ({"retry-after": formatdate(time.time() + 20, usegmt=True)}, 18, 20),
        ({"retry-after-ms": "nan", "retry-after": "2"}, 2, 2),
    ]:
        error = error_from_response(httpx.Response(429, headers=headers))
        assert minimum <= retry_delay(0, error, 60) <= maximum
    error = error_from_response(httpx.Response(429, headers={"retry-after": "61"}))
    with pytest.raises(APIError, match="max_retry_delay") as caught:
        retry_delay(0, error, 60)
    assert caught.value is error
    assert retry_delay(2, error_from_response(httpx.Response(503)), 60) == 1


def test_capabilities_and_replay_validation() -> None:
    from gpt_codex_client import Model, Response

    metadata = {"slug": "future-model", "new_capability": {"enabled": True}}
    assert Model.from_dict(metadata).raw == metadata
    with pytest.raises(StreamError):
        Response.from_dict({"status": "incomplete"}).to_input_items()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_terminal_alias(asynchronous: bool) -> None:
    content = frame("future.event", value=True) + frame(
        "response.done", response={"status": "completed", "output": []}
    )
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        stream = client.responses.create(model="m", input="", stream=True)
        if asynchronous:
            stream = await stream
        events = [event async for event in stream] if asynchronous else list(stream)
        assert [event.type for event in events] == ["future.event", "response.completed"]
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_fragmented_unicode_and_retry_cleanup(asynchronous: bool) -> None:
    payload = (
        'data: {"type":"response.output_text.delta","delta":"你好"}\n\n'
    ).encode() + terminal(
        output=[{"type": "message", "content": [{"type": "output_text", "text": "你好"}]}]
    )
    wire = ControlledStream([payload[i : i + 1] for i in range(len(payload))], "open")
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=wire))
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        result = client.responses.create(model="m", input="hi")
        if asynchronous:
            result = await result
        assert result.output_text == "你好"
        assert wire.closed == 1
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_failed_response_closed_before_retry(
    asynchronous: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = ControlledStream([b'{"error":{"code":"temporary"}}'])
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, stream=failed)
        return httpx.Response(200, content=terminal())

    def sleep(self: Any, attempt: int, delay: float) -> None:
        assert failed.closed == 1

    async def asleep(self: Any, attempt: int, delay: float) -> None:
        sleep(self, attempt, delay)

    monkeypatch.setattr(CodexClient, "_sleep_before_retry", sleep)
    monkeypatch.setattr(AsyncCodexClient, "_sleep_before_retry", asleep)
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(handler)
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        result = client.responses.create(model="m", input="hi")
        if asynchronous:
            await result
        assert attempts == 2
        assert failed.closed == 1
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
async def test_chat_unsupported_and_conflicting_tools(asynchronous: bool, conflict: bool) -> None:
    payload = (
        frame("response.output_item.added", output_index=0, item=tool(0, "{"))
        + terminal(output=[tool(0, "different")])
        if conflict
        else terminal(output=[{"type": "custom_tool_call", "name": "shell", "input": "ls"}])
    )
    wire = ControlledStream([payload], "open")
    http: Any = (httpx.AsyncClient if asynchronous else httpx.Client)(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=wire))
    )
    client: Any = (AsyncCodexClient if asynchronous else CodexClient)(http_client=http)
    client._token = Token(access_token="test")
    try:
        result = client.chat.completions.create(model="m", messages=[], stream=True)
        if asynchronous:
            result = await result
        with pytest.raises(StreamError, match=r"Conflicting|Unsupported"):
            if asynchronous:
                async for _ in result:
                    pass
            else:
                list(result)
        assert wire.closed == 1
    finally:
        if asynchronous:
            await http.aclose()
        else:
            http.close()


def test_strict_and_invalid_tool_history() -> None:
    from gpt_codex_client._converters import (
        chat_messages_to_response_input,
        chat_tools_to_response_tools,
    )

    assert chat_tools_to_response_tools(
        [{"type": "function", "function": {"name": "f", "strict": True}}]
    ) == [{"type": "function", "name": "f", "strict": True}]
    messages: list[dict[str, Any]] = [
        {"role": "tool", "content": "result"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": {}}}],
        },
    ]
    for message in messages:
        with pytest.raises(ValueError):
            chat_messages_to_response_input([message])


def test_option_validation() -> None:
    for kwargs in [{"max_retries": -1}, {"max_retry_delay": float("nan")}, {"max_retry_delay": -1}]:
        with pytest.raises(ValueError):
            CodexClient(**kwargs)  # type: ignore[arg-type]


def test_disabled_preservation_and_include_deduplication() -> None:
    from gpt_codex_client._converters import response_request_body

    assert "include" not in response_request_body(model="m", input="hi")
    assert response_request_body(
        model="m", input="hi", preserve_context=True, include=["reasoning.encrypted_content"]
    )["include"] == ["reasoning.encrypted_content"]
