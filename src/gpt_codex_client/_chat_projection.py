from __future__ import annotations

from ._errors import StreamError
from ._types import (
    ChatChunkChoice,
    ChatCompletionChunk,
    ChatDelta,
    JsonObject,
    ResponseStreamEvent,
    chat_finish_reason,
)


class ChatProjection:
    def __init__(self, *, preserve_context: bool = False) -> None:
        self.preserve_context = preserve_context
        self.tools: dict[str, JsonObject] = {}
        self.text = ""

    def feed(self, event: ResponseStreamEvent) -> list[ChatCompletionChunk]:
        response = event.response
        if response is None:
            return []
        deltas: list[ChatDelta] = []
        # Snapshots are cumulative; project only the suffix not yet delivered.
        if not response.output_text.startswith(self.text):
            raise StreamError("Conflicting text output", partial_response=response)
        suffix = response.output_text[len(self.text) :]
        if suffix:
            deltas.append(ChatDelta(content=suffix))
            self.text = response.output_text
        terminal = event.type in {"response.completed", "response.incomplete"}
        for item in response.output:
            kind = item.get("type", "")
            if kind != "function_call":
                if isinstance(kind, str) and kind.endswith("_call"):
                    raise StreamError(
                        "Unsupported Chat tool output",
                        kind="unsupported",
                        partial_response=response,
                    )
                continue
            call_id, name = item.get("call_id"), item.get("name")
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                if terminal:
                    raise StreamError("Incomplete tool identity", partial_response=response)
                continue
            arguments = item.get("arguments", "")
            if not isinstance(arguments, str):
                raise StreamError("Invalid tool arguments", partial_response=response)
            previous = self.tools.get(call_id)
            if previous is None:
                previous = {"index": len(self.tools), "name": name, "arguments": ""}
                self.tools[call_id] = previous
                delta: JsonObject = {
                    "index": previous["index"],
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            else:
                if previous["name"] != name or not arguments.startswith(previous["arguments"]):
                    raise StreamError("Conflicting tool output", partial_response=response)
                remaining = arguments[len(previous["arguments"]) :]
                if not remaining:
                    continue
                delta = {"index": previous["index"], "function": {"arguments": remaining}}
            previous["arguments"] = arguments
            deltas.append(ChatDelta(tool_calls=[delta]))
        chunks = [
            ChatCompletionChunk(
                id=response.id,
                model=response.model,
                choices=[ChatChunkChoice(index=0, delta=delta)],
                raw=event.data,
            )
            for delta in deltas
        ]
        if terminal:
            finish = chat_finish_reason(response)
            context = (
                response.provider_context()
                if self.preserve_context and response.status == "completed"
                else None
            )
            chunks.append(
                ChatCompletionChunk(
                    id=response.id,
                    model=response.model,
                    choices=[
                        ChatChunkChoice(
                            index=0, delta=ChatDelta(provider_data=context), finish_reason=finish
                        )
                    ],
                    raw=event.data,
                    usage=response.usage,
                )
            )
        return chunks
