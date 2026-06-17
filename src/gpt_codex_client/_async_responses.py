from __future__ import annotations

from typing import Any, Literal, TypeVar, cast, overload

from ._async_stream import AsyncResponseStream
from ._converters import response_request_body
from ._responses import _parse_output, _text_config_for_format
from ._types import FunctionTool, JsonObject, ParsedResponse, Reasoning, Response, TextConfig

T = TypeVar("T")


class AsyncResponsesResource:
    def __init__(self, client: Any) -> None:
        self._client = client

    @overload
    async def create(
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
    async def create(
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
    ) -> AsyncResponseStream: ...

    async def create(
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
    ) -> Response | AsyncResponseStream:
        body = response_request_body(
            model=model,
            input=input,
            instructions=instructions,
            stream=stream,
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
                AsyncResponseStream,
                await self._client._stream(
                    "POST",
                    "/responses",
                    json=body,
                    timeout=timeout,
                    extra_headers=extra_headers,
                ),
            )
        payload = cast(
            JsonObject,
            await self._client._request(
                "POST",
                "/responses",
                json=body,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )
        return Response.from_dict(payload)

    async def parse(
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
        response = await self.create(
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
        if isinstance(response, AsyncResponseStream):
            raise TypeError("parse() does not support stream=True")
        return ParsedResponse(
            response=response, parsed=_parse_output(response.output_text, text_format)
        )
