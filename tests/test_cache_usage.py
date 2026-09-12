from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest

from gpt_codex_client import AsyncCodexClient, CodexClient, Response, Token, Usage
from gpt_codex_client._cache import cache_key, session_headers

USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "input_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 10},
    "output_tokens_details": {"reasoning_tokens": 5},
    "future": {"value": 1},
}


def payload() -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "model": "m",
            "status": "completed",
            "usage": USAGE,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
        },
    }


def test_identity() -> None:
    long = "界" * 65
    assert cache_key(long, None) == hashlib.sha256(long.encode()).hexdigest()
    assert cache_key("s", "key") == "key"
    assert cache_key(None, None) is None
    assert session_headers({"Session-Id": "wrong", "X-Client-Request-ID": "wrong"}, "s") == {
        "session-id": "s",
        "x-client-request-id": "s",
    }
    for value in ["", " ", "a" * 65]:
        with pytest.raises(ValueError):
            cache_key("s", value)
    with pytest.raises(ValueError):
        cache_key(" ", None)


def test_usage() -> None:
    result = Usage.from_dict(USAGE)
    assert (result.input_tokens, result.cached_tokens, result.cache_write_tokens) == (100, 80, 10)
    assert (result.output_tokens, result.reasoning_tokens, result.total_tokens) == (20, 5, 120)
    result.raw["future"]["value"] = 2
    assert USAGE["future"] == {"value": 1}
    for value in [None, "1", -1, True, 1.5]:
        assert Usage.from_dict({"input_tokens": value}).input_tokens is None
    assert Usage.from_dict({"input_tokens": 0}).input_tokens == 0
    assert Usage.from_dict({}).cache_write_tokens is None
    assert Response.from_dict({}).usage is None


@pytest.mark.parametrize("entry", ["responses", "parse", "chat", "responses_stream", "chat_stream"])
def test_sync_entrypoints(entry: str) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(payload())}\n\n")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        CodexClient(http_client=http, default_headers={"Session-ID": "wrong"}) as client,
    ):
        client._token = Token(access_token="test")
        opts: dict[str, Any] = {
            "model": "gpt-5.5",
            "model_reasoning_effort": "high",
            "session_id": "s",
            "prompt_cache_key": "key",
        }
        result: Any
        stream_flag: Any = entry.endswith("stream")
        if entry == "parse":
            result = client.responses.parse(input="hi", text_format={}, **opts).response
        elif entry.startswith("chat"):
            result = client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}],
                stream=stream_flag,
                **opts,
            )
        else:
            result = client.responses.create(input="hi", stream=stream_flag, **opts)
        if entry.endswith("stream"):
            with result:
                events = list(result)
            result = events[-1] if entry.startswith("chat") else result.get_final_response()
        assert result.usage.input_tokens == 100
        assert result.usage.cached_tokens == 80
        assert not http.is_closed
    body = json.loads(seen[0].content)
    assert body["prompt_cache_key"] == "key" and body["store"] is False
    assert "session_id" not in body and "transport" not in body
    assert seen[0].headers["session-id"] == "s"
    assert body["reasoning"] == {"effort": "high"}
    assert "model_reasoning_effort" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["responses", "parse", "chat", "responses_stream", "chat_stream"])
async def test_async_entrypoints(entry: str) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(payload())}\n\n")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
        AsyncCodexClient(http_client=http) as client,
    ):
        client._token = Token(access_token="test")
        opts: dict[str, Any] = {
            "model": "gpt-5.5",
            "model_reasoning_effort": "high",
            "session_id": "s",
        }
        result: Any
        stream_flag: Any = entry.endswith("stream")
        if entry == "parse":
            result = (await client.responses.parse(input="hi", text_format={}, **opts)).response
        elif entry.startswith("chat"):
            result = await client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}],
                stream=stream_flag,
                **opts,
            )
        else:
            result = await client.responses.create(input="hi", stream=stream_flag, **opts)
        if entry.endswith("stream"):
            async with result:
                events = [event async for event in result]
            result = events[-1] if entry.startswith("chat") else await result.get_final_response()
        assert result.usage.total_tokens == 120
    body = json.loads(seen[0].content)
    assert body["prompt_cache_key"] == "s"
    assert body["reasoning"] == {"effort": "high"}
    assert "model_reasoning_effort" not in body


def test_manual_and_no_session() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(payload())}\n\n")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        CodexClient(http_client=http) as client,
    ):
        client._token = Token(access_token="test")
        client.responses.create(
            model="m",
            input=[],
            session_id=None,
            prompt_cache_key=None,
            previous_response_id="manual",
        )
    body = json.loads(seen[0].content)
    assert body["previous_response_id"] == "manual"
    assert "prompt_cache_key" not in body
    assert "session-id" not in seen[0].headers
