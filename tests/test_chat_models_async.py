from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from gpt_codex_client import (
    AsyncCodexClient,
    ChatCompletion,
    ChatCompletionChunk,
    CodexClient,
    Token,
)
from gpt_codex_client._config import save_token
from gpt_codex_client._converters import chat_messages_to_response_input, parse_tool_arguments


def test_models_list_cache(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == "https://manifest.test/models.json"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": "hidden", "visibility": "hide", "priority": 0},
                    {"slug": "m2", "priority": 2},
                    {"slug": "m1", "priority": 1},
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test",
        models_manifest_url="https://manifest.test/models.json",
    )

    assert [model.id for model in client.models.list()] == ["m1", "m2"]
    assert [model.id for model in client.models.list()] == ["m1", "m2"]
    assert calls == 1
    assert [model.id for model in client.models.list(force_refresh=True)] == ["m1", "m2"]
    assert calls == 2
    http_client.close()


def test_chat_converter_handles_roles_images_and_tools() -> None:
    instructions, response_input = chat_messages_to_response_input(
        [
            {"role": "system", "content": "sys"},
            {"role": "developer", "content": [{"type": "text", "text": "dev"}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            },
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [{"id": "call_1", "function": {"arguments": "{bad-json"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        ]
    )

    assert instructions == "sys\n\ndev"
    assert response_input[0]["content"] == [
        {"type": "input_text", "text": "look"},
        {"type": "input_image", "image_url": "data:image/png;base64,abc"},
    ]
    assert response_input[1]["tool_calls"] == [
        {"id": "call_1", "function": {"arguments": "{bad-json"}}
    ]
    assert response_input[2]["type"] == "function_call_output"
    assert parse_tool_arguments("{bad-json") == "{bad-json"


def test_chat_completions_create(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        payload = {
            "response": {
                "id": "resp_1",
                "model": "m",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hello"}],
                    },
                    {"type": "function_call", "name": "lookup", "arguments": "{}"},
                ],
            }
        }
        body = f"event: response.completed\ndata: {json.dumps(payload)}\n\n"
        return httpx.Response(200, content=body.encode("utf-8"))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )

    completion = client.chat.completions.create(
        model="m",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[
            {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
        ],
        reasoning_effort="low",
    )

    assert isinstance(completion, ChatCompletion)
    assert completion.choices[0].message.content == "hello"
    assert completion.choices[0].message.tool_calls == [
        {"type": "function_call", "name": "lookup", "arguments": "{}"}
    ]
    assert seen["body"]["instructions"] == "sys"
    assert seen["body"]["tools"] == [
        {"type": "function", "name": "lookup", "parameters": {"type": "object"}}
    ]
    http_client.close()


@pytest.mark.asyncio
async def test_async_responses_and_models_lazy_auth(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "manifest.test":
            return httpx.Response(200, json={"models": [{"slug": "m1"}]})
        body = (
            'event: response.output_text.delta\ndata: {"delta":"async"}\n\n'
            "event: response.completed\n"
            'data: {"response":{"id":"resp_1","model":"m","status":"completed","output":[]}}\n\n'
        )
        return httpx.Response(200, content=body.encode("utf-8"))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncCodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test/backend-api/codex",
        models_manifest_url="https://manifest.test/models.json",
    )

    response = await client.responses.create(model="m", input="hi")
    assert response.output_text == "async"
    assert [model.id for model in await client.models.list()] == ["m1"]
    await http_client.aclose()


@pytest.mark.asyncio
async def test_async_stream_and_chat_chunk(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)
    content = (
        'event: response.output_text.delta\ndata: {"delta":"a"}\n\n'
        "event: response.completed\n"
        'data: {"response":{"id":"resp_1","model":"m","status":"completed",'
        '"output_text":"a"}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content.encode("utf-8"))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncCodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )
    stream = await client.chat.completions.create(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    chunks: list[ChatCompletionChunk] = []
    async with stream:
        async for chunk in stream:
            chunks.append(chunk)

    assert chunks[0].choices[0].delta.content == "a"
    await http_client.aclose()


def _token_file(tmp_path: Path) -> Path:
    token_path = tmp_path / "auth.json"
    save_token(Token(access_token="access", expires_at=time.time() + 3600), token_path)
    return token_path
