from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Any, Literal, overload

from ._async_stream import AsyncResponseStream
from ._converters import (
    chat_messages_to_response_input,
    chat_tool_choice_to_response,
    chat_tools_to_response_tools,
    reasoning_from_effort,
)
from ._stream import ResponseStream
from ._types import (
    ChatChunkChoice,
    ChatCompletion,
    ChatCompletionChunk,
    ChatDelta,
    JsonObject,
    Response,
)


class ChatResource:
    def __init__(self, client: Any) -> None:
        self.completions = ChatCompletionsResource(client)


class ChatCompletionsResource:
    def __init__(self, client: Any) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: Literal[False] = False,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> ChatCompletion: ...

    @overload
    def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: Literal[True],
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> ChatCompletionStream: ...

    def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: bool = False,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> ChatCompletion | ChatCompletionStream:
        instructions, response_input = chat_messages_to_response_input(messages)
        response_tools = chat_tools_to_response_tools(tools)
        response_tool_choice = chat_tool_choice_to_response(tool_choice)
        result = self._client.responses.create(
            model=model,
            input=response_input,
            instructions=instructions,
            tools=response_tools,
            tool_choice=response_tool_choice,
            stream=stream,
            reasoning=reasoning_from_effort(reasoning_effort),
            timeout=timeout,
        )
        if isinstance(result, ResponseStream):
            return ChatCompletionStream(result)
        return ChatCompletion.from_response(result)


class AsyncChatResource:
    def __init__(self, client: Any) -> None:
        self.completions = AsyncChatCompletionsResource(client)


class AsyncChatCompletionsResource:
    def __init__(self, client: Any) -> None:
        self._client = client

    @overload
    async def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: Literal[False] = False,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> ChatCompletion: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: Literal[True],
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> AsyncChatCompletionStream: ...

    async def create(
        self,
        *,
        model: str,
        messages: list[JsonObject],
        tools: list[JsonObject] | None = None,
        tool_choice: str | JsonObject | None = "auto",
        stream: bool = False,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> ChatCompletion | AsyncChatCompletionStream:
        instructions, response_input = chat_messages_to_response_input(messages)
        result = await self._client.responses.create(
            model=model,
            input=response_input,
            instructions=instructions,
            tools=chat_tools_to_response_tools(tools),
            tool_choice=chat_tool_choice_to_response(tool_choice),
            stream=stream,
            reasoning=reasoning_from_effort(reasoning_effort),
            timeout=timeout,
        )
        if isinstance(result, AsyncResponseStream):
            return AsyncChatCompletionStream(result)
        return ChatCompletion.from_response(result)


class ChatCompletionStream:
    def __init__(self, stream: ResponseStream) -> None:
        self._stream = stream

    def __enter__(self) -> ChatCompletionStream:
        self._stream.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stream.__exit__(exc_type, exc, traceback)

    def __iter__(self) -> Iterator[ChatCompletionChunk]:
        for event in self._stream:
            chunk = _chunk_from_event(event.type, event.data, event.response)
            if chunk is not None:
                yield chunk


class AsyncChatCompletionStream:
    def __init__(self, stream: AsyncResponseStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> AsyncChatCompletionStream:
        await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._stream.__aexit__(exc_type, exc, traceback)

    def __aiter__(self) -> AsyncIterator[ChatCompletionChunk]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ChatCompletionChunk]:
        async for event in self._stream:
            chunk = _chunk_from_event(event.type, event.data, event.response)
            if chunk is not None:
                yield chunk


def _chunk_from_event(
    event_type: str,
    data: JsonObject,
    response: Response | None,
) -> ChatCompletionChunk | None:
    if event_type == "response.output_text.delta":
        delta = data.get("delta")
        if not isinstance(delta, str):
            return None
        choice = ChatChunkChoice(index=0, delta=ChatDelta(content=delta))
        return ChatCompletionChunk(
            id=response.id if response is not None else None,
            model=response.model if response is not None else None,
            choices=[choice],
            raw=data,
        )
    if event_type in {"response.completed", "response.incomplete"}:
        choice = ChatChunkChoice(index=0, delta=ChatDelta(), finish_reason="stop")
        return ChatCompletionChunk(
            id=response.id if response is not None else None,
            model=response.model if response is not None else None,
            choices=[choice],
            raw=data,
        )
    return None
