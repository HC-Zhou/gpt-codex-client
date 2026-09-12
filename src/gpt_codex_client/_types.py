from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

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
    def from_response(cls, response: Response) -> ChatCompletion:
        tool_calls = _extract_tool_calls(response.output)
        message = ChatMessage(
            role="assistant",
            content=response.output_text or None,
            tool_calls=tool_calls or None,
        )
        choice = ChatChoice(index=0, message=message, finish_reason=_finish_reason(response.status))
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
        if item_type in {"message", "reasoning"}:
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
        item_type = item.get("type")
        if item_type in {"function_call", "tool_call"}:
            calls.append(item)
        nested = item.get("tool_calls")
        if isinstance(nested, list):
            calls.extend(call for call in nested if isinstance(call, dict))
    return calls


def _finish_reason(status: str | None) -> str | None:
    if status in {None, "completed"}:
        return "stop"
    if status == "incomplete":
        return "length"
    return status
