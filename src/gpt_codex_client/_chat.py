from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Any, Literal, overload

from ._async_stream import AsyncResponseStream
from ._chat_projection import ChatProjection
from ._converters import (
    chat_messages_to_response_input,
    chat_tool_choice_to_response,
    chat_tools_to_response_tools,
    reasoning_from_effort,
)
from ._stream import ResponseStream
from ._types import (
    ChatCompletion,
    ChatCompletionChunk,
    JsonObject,
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
        include: list[str] | None = None,
        preserve_context: bool = False,
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
        include: list[str] | None = None,
        preserve_context: bool = False,
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
        include: list[str] | None = None,
        preserve_context: bool = False,
        timeout: float | None = None,
    ) -> ChatCompletion | ChatCompletionStream:
        instructions, response_input = chat_messages_to_response_input(messages, model=model)
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
            include=include,
            preserve_context=preserve_context,
            timeout=timeout,
        )
        if isinstance(result, ResponseStream):
            return ChatCompletionStream(result, preserve_context=preserve_context)
        return ChatCompletion.from_response(result, preserve_context=preserve_context)


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
        include: list[str] | None = None,
        preserve_context: bool = False,
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
        include: list[str] | None = None,
        preserve_context: bool = False,
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
        include: list[str] | None = None,
        preserve_context: bool = False,
        timeout: float | None = None,
    ) -> ChatCompletion | AsyncChatCompletionStream:
        instructions, response_input = chat_messages_to_response_input(messages, model=model)
        result = await self._client.responses.create(
            model=model,
            input=response_input,
            instructions=instructions,
            tools=chat_tools_to_response_tools(tools),
            tool_choice=chat_tool_choice_to_response(tool_choice),
            stream=stream,
            reasoning=reasoning_from_effort(reasoning_effort),
            include=include,
            preserve_context=preserve_context,
            timeout=timeout,
        )
        if isinstance(result, AsyncResponseStream):
            return AsyncChatCompletionStream(result, preserve_context=preserve_context)
        return ChatCompletion.from_response(result, preserve_context=preserve_context)


class ChatCompletionStream:
    def __init__(self, stream: ResponseStream, *, preserve_context: bool = False) -> None:
        self._stream = stream
        self._projection = ChatProjection(preserve_context=preserve_context)

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

    def close(self) -> None:
        self._stream.close()

    def __iter__(self) -> Iterator[ChatCompletionChunk]:
        for event in self._stream:
            try:
                yield from self._projection.feed(event)
            except Exception:
                self._stream.close()
                raise


class AsyncChatCompletionStream:
    def __init__(self, stream: AsyncResponseStream, *, preserve_context: bool = False) -> None:
        self._stream = stream
        self._projection = ChatProjection(preserve_context=preserve_context)

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

    async def aclose(self) -> None:
        await self._stream.aclose()

    def __aiter__(self) -> AsyncIterator[ChatCompletionChunk]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ChatCompletionChunk]:
        async for event in self._stream:
            try:
                for chunk in self._projection.feed(event):
                    yield chunk
            except Exception:
                await self._stream.aclose()
                raise
