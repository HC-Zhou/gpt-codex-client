from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Generic, TypeVar

from ._errors import StreamError

T = TypeVar("T")


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class FunctionTool:
    name: str
    description: str | None = None
    parameters: JsonObject | None = None
    strict: bool | None = None

    def to_dict(self) -> JsonObject:
        body: JsonObject = {"type": "function", "name": self.name}
        if self.description is not None:
            body["description"] = self.description
        if self.parameters is not None:
            body["parameters"] = self.parameters
        if self.strict is not None:
            body["strict"] = self.strict
        return body


@dataclass(frozen=True)
class TextConfig:
    format: JsonObject | None = None
    verbosity: str | None = None

    def to_dict(self) -> JsonObject:
        body: JsonObject = {}
        if self.format is not None:
            body["format"] = self.format
        if self.verbosity is not None:
            body["verbosity"] = self.verbosity
        return body


@dataclass(frozen=True)
class Reasoning:
    effort: str | None = None
    summary: str | None = None

    def to_dict(self) -> JsonObject:
        body: JsonObject = {}
        if self.effort is not None:
            body["effort"] = self.effort
        if self.summary is not None:
            body["summary"] = self.summary
        return body


@dataclass
class Response:
    id: str | None
    model: str | None
    output_text: str
    status: str | None = None
    output: list[JsonObject] = field(default_factory=list)
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: JsonObject) -> Response:
        output = _list_of_objects(payload.get("output"))
        output_text = _extract_output_text(payload, output)
        return cls(
            id=_str_or_none(payload.get("id")),
            model=_str_or_none(payload.get("model")),
            output_text=output_text,
            status=_str_or_none(payload.get("status")),
            output=output,
            raw=payload,
        )

    def to_input_items(self) -> list[JsonObject]:
        if self.status != "completed":
            raise StreamError("Only completed responses can be replayed", partial_response=self)
        return deepcopy(self.output)

    def provider_context(self) -> JsonObject:
        return {
            "version": 1,
            "provider": "codex",
            "model": self.model,
            "output_items": self.to_input_items(),
        }


@dataclass
class ParsedResponse(Generic[T]):
    response: Response
    parsed: T


@dataclass
class ResponseStreamEvent:
    type: str
    data: JsonObject
    response: Response | None = None


@dataclass
class Model:
    id: str
    created: int | None = None
    owned_by: str | None = None
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: JsonObject) -> Model:
        created = payload.get("created")
        model_id = payload.get("id") or payload.get("slug")
        return cls(
            id=str(model_id or ""),
            created=created if isinstance(created, int) else None,
            owned_by=_str_or_none(payload.get("owned_by")) or "openai",
            raw=payload,
        )


@dataclass
class ChatMessage:
    role: str
    content: str | None = None
    tool_calls: list[JsonObject] | None = None
    provider_data: JsonObject | None = None

    def to_dict(self) -> JsonObject:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class ChatChoice:
    index: int
    message: ChatMessage
    finish_reason: str | None = None


@dataclass
class ChatDelta:
    role: str | None = None
    content: str | None = None
    tool_calls: list[JsonObject] | None = None
    provider_data: JsonObject | None = None


@dataclass
class ChatChunkChoice:
    index: int
    delta: ChatDelta
    finish_reason: str | None = None


@dataclass
class ChatCompletion:
    id: str | None
    model: str | None
    choices: list[ChatChoice]
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion"
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_response(cls, response: Response, *, preserve_context: bool = False) -> ChatCompletion:
        tool_calls = _extract_tool_calls(response.output)
        message = ChatMessage(
            role="assistant",
            content=response.output_text or None,
            tool_calls=tool_calls or None,
            provider_data=response.provider_context()
            if preserve_context and response.status == "completed"
            else None,
        )
        choice = ChatChoice(index=0, message=message, finish_reason=chat_finish_reason(response))
        return cls(
            id=response.id,
            model=response.model,
            choices=[choice],
            raw=response.raw,
        )


@dataclass
class ChatCompletionChunk:
    id: str | None
    model: str | None
    choices: list[ChatChunkChoice]
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion.chunk"
    raw: JsonObject = field(default_factory=dict)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _list_of_objects(value: Any) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_output_text(payload: JsonObject, output: list[JsonObject]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct

    chunks: list[str] = []
    for item in output:
        item_type = item.get("type")
        if item_type == "message":
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
            elif isinstance(content, str):
                chunks.append(content)
        elif item_type in {"output_text", "text"} and isinstance(item.get("text"), str):
            chunks.append(item["text"])
    return "".join(chunks)


def _extract_tool_calls(output: list[JsonObject]) -> list[JsonObject]:
    calls: list[JsonObject] = []
    for item in output:
        kind = item.get("type", "")
        if kind == "function_call":
            if not all(
                isinstance(item.get(k), str) and item.get(k) for k in ("call_id", "name")
            ) or not isinstance(item.get("arguments"), str):
                raise StreamError("Invalid function call output")
            calls.append(
                {
                    "id": item["call_id"],
                    "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]},
                }
            )
        elif isinstance(kind, str) and (kind.endswith("_call") or kind == "tool_call"):
            raise StreamError(
                "Tool output cannot be represented as a Chat function", kind="unsupported"
            )
    return calls


def chat_finish_reason(response: Response) -> str:
    if response.status == "incomplete":
        details = response.raw.get("incomplete_details", {})
        reason = details.get("reason") if isinstance(details, dict) else None
        if reason == "max_output_tokens":
            return "length"
        if reason == "content_filter":
            return "content_filter"
        raise StreamError(
            "Unsupported incomplete response reason",
            kind="incomplete",
            code=reason if isinstance(reason, str) else None,
            partial_response=response,
        )
    if response.status != "completed":
        raise StreamError("Chat response is not completed", partial_response=response)
    return "tool_calls" if _extract_tool_calls(response.output) else "stop"
