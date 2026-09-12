from __future__ import annotations

from typing import Any

import httpx
import pytest

from gpt_codex_client import AsyncCodexClient, CodexClient, Reasoning
from gpt_codex_client._converters import response_request_body


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "future"])
def test_effort_is_mapped_without_model_name_gating(effort: str) -> None:
    body = response_request_body(model="gpt-5.5", input="hi", model_reasoning_effort=effort)
    assert body["reasoning"] == {"effort": effort}
    assert "model_reasoning_effort" not in body


def test_alias_preserves_reasoning_options_without_mutation() -> None:
    reasoning: dict[str, Any] = {"summary": "auto", "future": {"value": 1}}
    body = response_request_body(
        model="gpt-5.5", input="hi", reasoning=reasoning, model_reasoning_effort="high"
    )
    assert body["reasoning"]["summary"] == "auto"
    body["reasoning"]["future"]["value"] = 2
    assert reasoning == {"summary": "auto", "future": {"value": 1}}
    assert response_request_body(
        model="gpt-5.5",
        input="hi",
        reasoning=Reasoning(effort="high", summary="auto"),
        model_reasoning_effort="high",
    )["reasoning"] == {"effort": "high", "summary": "auto"}
    assert "reasoning" not in response_request_body(model="gpt-5.5", input="hi")


@pytest.mark.parametrize("value", ["", " ", 1, False])
def test_invalid_alias_rejected(value: Any) -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        response_request_body(model="gpt-5.5", input="hi", model_reasoning_effort=value)


@pytest.mark.parametrize("entry", ["responses", "parse", "chat"])
def test_conflict_rejected_before_network(entry: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("conflicting reasoning settings must not reach the network")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        CodexClient(http_client=http) as client,
    ):
        opts: dict[str, Any] = {"model": "gpt-5.5", "model_reasoning_effort": "high"}
        with pytest.raises(ValueError, match="conflicts"):
            if entry == "chat":
                client.chat.completions.create(messages=[], reasoning_effort="low", **opts)
            elif entry == "parse":
                client.responses.parse(
                    input="hi", text_format={}, reasoning={"effort": "low"}, **opts
                )
            else:
                client.responses.create(input="hi", reasoning=Reasoning(effort="low"), **opts)


@pytest.mark.parametrize("entry", ["responses", "parse", "chat"])
async def test_async_conflict_rejected_before_network(entry: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("conflicting reasoning settings must not reach the network")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
        AsyncCodexClient(http_client=http) as client,
    ):
        opts: dict[str, Any] = {"model": "gpt-5.5", "model_reasoning_effort": "high"}
        with pytest.raises(ValueError, match="conflicts"):
            if entry == "chat":
                await client.chat.completions.create(messages=[], reasoning_effort="low", **opts)
            elif entry == "parse":
                await client.responses.parse(
                    input="hi", text_format={}, reasoning={"effort": "low"}, **opts
                )
            else:
                await client.responses.create(input="hi", reasoning={"effort": "low"}, **opts)
