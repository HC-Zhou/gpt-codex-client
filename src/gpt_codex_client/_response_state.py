from __future__ import annotations

from copy import deepcopy
from typing import NoReturn

from ._errors import StreamError
from ._types import JsonObject, Response, ResponseStreamEvent


class ResponseState:
    """Transport-independent accumulation and terminal state."""

    def __init__(self) -> None:
        self.payload: JsonObject = {}
        self.items: dict[int, JsonObject] = {}
        self.final: Response | None = None
        self.error: StreamError | None = None

    def is_terminal(self) -> bool:
        return self.final is not None

    def snapshot(self) -> Response:
        payload = deepcopy(self.payload)
        payload["output"] = [deepcopy(item) for _, item in sorted(self.items.items())]
        return Response.from_dict(payload)

    def fail(
        self,
        message: str,
        *,
        kind: str = "protocol",
        code: str | None = None,
        raw_event: JsonObject | None = None,
    ) -> NoReturn:
        self.error = StreamError(
            message, kind=kind, code=code, partial_response=self.snapshot(), raw_event=raw_event
        )
        raise self.error

    def result(self) -> Response:
        if self.error is not None:
            raise self.error
        if self.final is None:
            raise StreamError(
                "Response has not reached a terminal event",
                kind="not_complete",
                partial_response=self.snapshot(),
            )
        return self.final

    def record(self, event: ResponseStreamEvent) -> ResponseStreamEvent:
        data = event.data
        payload = data.get("response")
        if isinstance(payload, dict):
            self.payload.update({k: deepcopy(v) for k, v in payload.items() if k != "output"})
            output = payload.get("output")
            if isinstance(output, list):
                for index, item in enumerate(output):
                    if isinstance(item, dict):
                        self.items[index] = {**self.items.get(index, {}), **deepcopy(item)}
        status = self.payload.get("status")
        if (
            event.type == "error"
            or event.type in {"response.failed", "response.cancelled"}
            or status in {"failed", "cancelled"}
        ):
            error = (
                data.get("error", data) if event.type == "error" else self.payload.get("error", {})
            )
            if not isinstance(error, dict):
                error = {}
            message = error.get("message")
            code = error.get("code")
            self.fail(
                message if isinstance(message, str) else "Codex response failed",
                kind="failed",
                code=code if isinstance(code, str) else None,
                raw_event=data,
            )
        if event.type == "response.done":
            if status not in {"completed", "incomplete"}:
                self.fail("response.done has no valid terminal status", raw_event=data)
            event.type = "response." + str(status)
        item_events = {
            "response.output_item.added",
            "response.output_item.done",
            "response.output_text.delta",
            "response.output_text.done",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }
        if event.type not in item_events and event.type not in {
            "response.completed",
            "response.incomplete",
        }:
            event.response = self.snapshot()
            return event
        index = data.get("output_index", 0)
        if not isinstance(index, int) or index < 0:
            self.fail("Invalid output index", raw_event=data)
        item_id = data.get("item_id")
        if isinstance(item_id, str):
            index = next((i for i, item in self.items.items() if item.get("id") == item_id), index)
        item = data.get("item")
        if event.type in {"response.output_item.added", "response.output_item.done"} and isinstance(
            item, dict
        ):
            self.items[index] = {**self.items.get(index, {}), **deepcopy(item)}
        if event.type in {"response.output_text.delta", "response.output_text.done"}:
            current = self.items.setdefault(
                index, {"type": "message", "role": "assistant", "content": []}
            )
            parts = current.setdefault("content", [])
            content_index = data.get("content_index", 0)
            if (
                not isinstance(parts, list)
                or not isinstance(content_index, int)
                or content_index < 0
            ):
                self.fail("Invalid text content index", raw_event=data)
            while len(parts) <= content_index:
                parts.append({"type": "output_text", "text": ""})
            value = data.get("delta" if event.type.endswith(".delta") else "text", "")
            if not isinstance(value, str):
                self.fail("Invalid text delta", raw_event=data)
            if not isinstance(parts[content_index], dict) or not isinstance(
                parts[content_index].get("text", ""), str
            ):
                self.fail("Invalid text content", raw_event=data)
            parts[content_index]["text"] = (
                parts[content_index].get("text", "") + value
                if event.type.endswith(".delta")
                else value
            )
        if event.type in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            current = self.items.setdefault(index, {"type": "function_call"})
            if item_id is not None:
                current.setdefault("id", item_id)
            value = data.get("delta" if event.type.endswith(".delta") else "arguments", "")
            if not isinstance(value, str):
                self.fail("Invalid function arguments", raw_event=data)
            if not isinstance(current.get("arguments", ""), str):
                self.fail("Invalid accumulated function arguments", raw_event=data)
            current["arguments"] = (
                current.get("arguments", "") + value if event.type.endswith(".delta") else value
            )
        if event.type in {"response.completed", "response.incomplete"}:
            self.payload["status"] = event.type.removeprefix("response.")
            self.final = self.snapshot()
            event.response = self.final
        else:
            event.response = self.snapshot()
        return event
