from __future__ import annotations

import json
from typing import Any, Literal, TypeVar, cast, overload

from ._converters import response_request_body
from ._stream import ResponseStream
from ._types import FunctionTool, JsonObject, ParsedResponse, Reasoning, Response, TextConfig

T = TypeVar("T")


class ResponsesResource:
    def __init__(self, client: Any) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        model: str,
        input: str | list[Any],
        instructions: str | None = None,
        stream: Literal[False] = False,
        tools: list[FunctionTool | JsonObject] | None = None,
        tool_choice: str | JsonObject | None = None,
        parallel_tool_calls: bool | None = None,
        reasoning: Reasoning | JsonObject | None = None,
        text: TextConfig | JsonObject | None = None,
        include: list[str] | None = None,
        previous_response_id: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Response: ...

    @overload
    def create(
        self,
        *,
        model: str,
        input: str | list[Any],
        instructions: str | None = None,
        stream: Literal[True],
        tools: list[FunctionTool | JsonObject] | None = None,
        tool_choice: str | JsonObject | None = None,
        parallel_tool_calls: bool | None = None,
        reasoning: Reasoning | JsonObject | None = None,
        text: TextConfig | JsonObject | None = None,
        include: list[str] | None = None,
        previous_response_id: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ResponseStream: ...

    def create(
        self,
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
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Response | ResponseStream:
        body = response_request_body(
            model=model,
            input=input,
            instructions=instructions,
            stream=True,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            reasoning=reasoning,
            text=text,
            include=include,
            previous_response_id=previous_response_id,
        )
        if stream:
            return cast(
                ResponseStream,
                self._client._stream(
                    "POST",
                    "/responses",
                    json=body,
                    timeout=timeout,
                    extra_headers=extra_headers,
                ),
            )
        response_stream = cast(
            ResponseStream,
            self._client._stream(
                "POST",
                "/responses",
                json=body,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )
        with response_stream as opened_stream:
            for _event in opened_stream:
                pass
            return opened_stream.get_final_response()

    def parse(
        self,
        *,
        model: str,
        input: str | list[Any],
        text_format: type[T] | JsonObject,
        instructions: str | None = None,
        tools: list[FunctionTool | JsonObject] | None = None,
        tool_choice: str | JsonObject | None = None,
        parallel_tool_calls: bool | None = None,
        reasoning: Reasoning | JsonObject | None = None,
        include: list[str] | None = None,
        previous_response_id: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ParsedResponse[T]:
        text_config = _text_config_for_format(text_format)
        response = self.create(
            model=model,
            input=input,
            instructions=instructions,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            reasoning=reasoning,
            text=text_config,
            include=include,
            previous_response_id=previous_response_id,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if isinstance(response, ResponseStream):
            raise TypeError("parse() does not support stream=True")
        return ParsedResponse(
            response=response, parsed=_parse_output(response.output_text, text_format)
        )


def _text_config_for_format(text_format: type[T] | JsonObject) -> TextConfig:
    if isinstance(text_format, dict):
        return TextConfig(format=text_format)
    model_json_schema = getattr(text_format, "model_json_schema", None)
    if callable(model_json_schema):
        schema = _strict_json_schema(model_json_schema())
        name = getattr(text_format, "__name__", "ParsedResponse")
        return TextConfig(
            format={
                "type": "json_schema",
                "name": str(name),
                "schema": schema,
                "strict": True,
            }
        )
    raise TypeError("text_format must be a Pydantic v2 model class or a JSON schema dict")


def _strict_json_schema(schema: Any) -> JsonObject:
    if not isinstance(schema, dict):
        raise TypeError("Pydantic model_json_schema() must return a dict")
    normalized = dict(schema)
    _add_additional_properties_false(normalized)
    return normalized


def _add_additional_properties_false(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "additionalProperties" not in value:
            value["additionalProperties"] = False
        for child in value.values():
            _add_additional_properties_false(child)
    elif isinstance(value, list):
        for item in value:
            _add_additional_properties_false(item)


def _parse_output(output_text: str, text_format: type[T] | JsonObject) -> T:
    if isinstance(text_format, dict):
        return cast(T, json.loads(output_text))
    model_validate_json = getattr(text_format, "model_validate_json", None)
    if callable(model_validate_json):
        parsed = model_validate_json(output_text)
        return cast(T, parsed)
    raise TypeError("text_format must be a Pydantic v2 model class or a JSON schema dict")
