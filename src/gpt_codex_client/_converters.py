from __future__ import annotations

import json
from typing import Any

from ._types import FunctionTool, JsonObject, Reasoning, TextConfig


def response_request_body(
    *,
    model: str,
    input: str | list[Any],
    instructions: str | None = None,
    stream: bool = False,
    tools: list[FunctionTool | JsonObject] | None = None,
    tool_choice: str | JsonObject | None = None,
    parallel_tool_calls: bool | None = None,
    reasoning: Reasoning | JsonObject | None = None,
    text: TextConfig | JsonObject | None = None,
    include: list[str] | None = None,
    previous_response_id: str | None = None,
) -> JsonObject:
    body: JsonObject = {"model": model, "input": input, "stream": stream}
    optional: dict[str, Any | None] = {
        "instructions": instructions,
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel_tool_calls,
        "include": include,
        "previous_response_id": previous_response_id,
    }
    for key, value in optional.items():
        if value is not None:
            body[key] = value
    if tools is not None:
        body["tools"] = [
            tool.to_dict() if isinstance(tool, FunctionTool) else tool for tool in tools
        ]
    if reasoning is not None:
        body["reasoning"] = reasoning.to_dict() if isinstance(reasoning, Reasoning) else reasoning
    if text is not None:
        body["text"] = text.to_dict() if isinstance(text, TextConfig) else text
    return body


def chat_messages_to_response_input(
    messages: list[JsonObject],
) -> tuple[str | None, list[JsonObject]]:
    instructions: list[str] = []
    input_items: list[JsonObject] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content")
        if role in {"system", "developer"}:
            text = _content_to_plain_text(content)
            if text:
                instructions.append(text)
            continue

        item: JsonObject = {"role": role}
        if role == "tool":
            item["type"] = "function_call_output"
            if isinstance(message.get("tool_call_id"), str):
                item["call_id"] = message["tool_call_id"]
            item["output"] = _content_to_plain_text(content)
        else:
            item["content"] = _content_to_response_content(content, role=role)
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                item["tool_calls"] = [call for call in tool_calls if isinstance(call, dict)]
        input_items.append(item)
    return ("\n\n".join(instructions) if instructions else None, input_items)


def chat_tools_to_response_tools(tools: list[JsonObject] | None) -> list[JsonObject] | None:
    if tools is None:
        return None
    converted: list[JsonObject] = []
    for tool in tools:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            item: JsonObject = {"type": "function", "name": str(function.get("name", ""))}
            if isinstance(function.get("description"), str):
                item["description"] = function["description"]
            parameters = function.get("parameters")
            if isinstance(parameters, dict):
                item["parameters"] = parameters
            converted.append(item)
        else:
            converted.append(tool)
    return converted


def chat_tool_choice_to_response(tool_choice: str | JsonObject | None) -> str | JsonObject | None:
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), dict):
        function = tool_choice["function"]
        name = function.get("name")
        if isinstance(name, str):
            return {"type": "function", "name": name}
    return tool_choice


def reasoning_from_effort(reasoning_effort: str | None) -> Reasoning | None:
    if reasoning_effort is None:
        return None
    return Reasoning(effort=reasoning_effort)


def parse_tool_arguments(arguments: Any) -> JsonObject | str | None:
    if arguments is None:
        return None
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        return parsed if isinstance(parsed, dict) else arguments
    return str(arguments)


def _content_to_plain_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _content_to_response_content(content: Any, *, role: str) -> str | list[JsonObject]:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    converted: list[JsonObject] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type in {"text", "input_text"} and isinstance(part.get("text"), str):
            converted.append(
                {"type": "input_text" if role == "user" else "output_text", "text": part["text"]}
            )
        elif part_type == "image_url":
            image_url = part.get("image_url")
            if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                converted.append({"type": "input_image", "image_url": image_url["url"]})
            elif isinstance(image_url, str):
                converted.append({"type": "input_image", "image_url": image_url})
        elif isinstance(part_type, str):
            converted.append(part)
    return converted
