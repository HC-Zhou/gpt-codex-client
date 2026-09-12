from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from gpt_codex_client import (
    CodexClient,
    FunctionTool,
    InvalidRequestError,
    ParsedResponse,
    RateLimitError,
    Reasoning,
    TextConfig,
    Token,
)
from gpt_codex_client._config import save_token
from gpt_codex_client._stream import parse_sse_lines


def test_responses_create_serializes_body(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return _sse_response("ok")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )

    response = client.responses.create(
        model="m",
        input="hello",
        instructions="be terse",
        tools=[FunctionTool(name="lookup", parameters={"type": "object"})],
        tool_choice="auto",
        parallel_tool_calls=True,
        reasoning=Reasoning(effort="low"),
        text=TextConfig(verbosity="low"),
        include=["output"],
        previous_response_id="resp_prev",
    )

    assert response.output_text == "ok"
    assert seen["headers"]["authorization"] == "Bearer access"
    assert seen["body"] == {
        "model": "m",
        "input": [{"role": "user", "content": "hello"}],
        "stream": True,
        "store": False,
        "instructions": "be terse",
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low"},
        "include": ["output"],
        "previous_response_id": "resp_prev",
    }
    http_client.close()


def test_sse_parser_and_stream_final_response(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)
    body = (
        'event: response.created\ndata: {"type":"response.created"}\n\n'
        'event: response.output_text.delta\ndata: {"delta":"hel"}\n\n'
        'event: response.output_text.delta\ndata: {"delta":"lo"}\n\n'
        "event: response.completed\n"
        'data: {"response":{"id":"resp_1","model":"m","status":"completed","output":[]}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )

    with client.responses.create(model="m", input="hello", stream=True) as stream:
        events = list(stream)
        final = stream.get_final_response()

    assert [event.type for event in events] == [
        "response.created",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.completed",
        "done",
    ]
    assert final.output_text == "hello"
    http_client.close()


def test_parse_sse_unknown_event() -> None:
    events = list(parse_sse_lines(["event: custom.event", 'data: {"value": 1}', ""]))

    assert events[0].type == "custom.event"
    assert events[0].data == {"value": 1}


def test_responses_parse_pydantic_model(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)

    class Payload(BaseModel):
        title: str

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        return _sse_response('{"title":"ok"}')

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )

    parsed = client.responses.parse(model="m", input="json", text_format=Payload)

    assert parsed.parsed.title == "ok"
    http_client.close()


def test_responses_parse_manual_schema(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response('{"ok": true}')

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path, http_client=http_client, base_url="https://example.test"
    )

    parsed: ParsedResponse[dict[str, Any]] = client.responses.parse(
        model="m",
        input="json",
        text_format={"type": "json_schema", "name": "Manual", "schema": {"type": "object"}},
    )

    assert parsed.parsed == {"ok": True}
    http_client.close()


def test_retry_for_429_and_no_retry_for_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = _token_file(tmp_path)
    monkeypatch.setattr(time, "sleep", lambda delay: None)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"error": {"message": "slow"}}
            )
        return httpx.Response(200, json={"models": [{"slug": "m"}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test",
        models_manifest_url="https://example.test/models.json",
        max_retries=1,
    )

    assert [model.id for model in client.models.list()] == ["m"]
    assert calls == 2
    http_client.close()

    def bad_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad"}})

    http_client = httpx.Client(transport=httpx.MockTransport(bad_request))
    client = CodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test",
        models_manifest_url="https://example.test/models.json",
        max_retries=2,
    )

    with pytest.raises(InvalidRequestError):
        client.models.list()
    http_client.close()


def test_invalid_request_error_uses_detail_message(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Input must be a list"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test",
        models_manifest_url="https://example.test/models.json",
        max_retries=0,
    )

    with pytest.raises(InvalidRequestError, match="Input must be a list"):
        client.models.list()
    http_client.close()


def test_rate_limit_error_keeps_retry_after(tmp_path: Path) -> None:
    token_path = _token_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"retry-after": "3"}, json={"error": {"message": "slow"}}
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexClient(
        token_path=token_path,
        http_client=http_client,
        base_url="https://example.test",
        max_retries=0,
    )

    with pytest.raises(RateLimitError) as exc_info:
        client.responses.create(model="m", input="hello")
    assert exc_info.value.retry_after == 3
    http_client.close()


def _token_file(tmp_path: Path) -> Path:
    token_path = tmp_path / "auth.json"
    save_token(Token(access_token="access", expires_at=time.time() + 3600), token_path)
    return token_path


def _sse_response(output_text: str, *, model: str = "m") -> httpx.Response:
    completed = {
        "response": {
            "id": "resp_1",
            "model": model,
            "status": "completed",
            "output": [],
        }
    }
    body = (
        f"event: response.output_text.delta\ndata: {json.dumps({'delta': output_text})}\n\n"
        "event: response.completed\n"
        f"data: {json.dumps(completed)}\n\n"
    )
    return httpx.Response(200, content=body.encode("utf-8"))
