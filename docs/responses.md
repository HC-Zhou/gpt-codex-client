# Responses

```python
from gpt_codex_client import CodexClient, FunctionTool, Reasoning

response = CodexClient().responses.create(
    model="gpt-5.5",
    input="Find the answer.",
    tools=[FunctionTool(name="lookup", parameters={"type": "object"})],
    reasoning=Reasoning(effort="medium"),
)
```

Use `client.models.list()` to discover model slugs in the public registry.
Registry presence does not establish account access.

## Native output replay

```python
history = [{"role": "user", "content": "Look up record 42"}]
response = client.responses.create(
    model="model", input=history, tools=[FunctionTool(name="lookup")],
    preserve_context=True,
)
history.extend(response.to_input_items())
for item in response.output:
    if item.get("type") == "function_call":
        # Validate and execute in your application; this is example output.
        history.append({"type": "function_call_output", "call_id": item["call_id"],
                        "output": "record 42: example result"})
next_response = client.responses.create(model="model", input=history)
```

`to_input_items()` returns a deep copy of completed output in its original order,
including reasoning, encrypted content, message phase, IDs and unknown fields.
Mutating the copy does not change the response. Incomplete responses are rejected
by this helper; inspect `output` and `raw` to decide explicitly how to proceed.
Keep the source model with stored history. Native raw-input replay leaves model
compatibility to the caller; Chat's versioned envelope validates the model itself.

`preserve_context=True` merges `reasoning.encrypted_content` into `include` without
removing existing values. It defaults to False and is supported by `create` and
`parse` on both clients. Encrypted context stays opaque and is excluded from
`output_text`. Native output preserves tool types unsupported by Chat.

These contracts have offline MockTransport coverage; no live Codex replay or
account availability is established by the test suite.

## Cache identity and optional WebSocket transport

Synchronous and asynchronous `responses.create`, `responses.parse`, and
`chat.completions.create` accept these keyword arguments:

| Argument | Default | Behavior |
| --- | --- | --- |
| `session_id` | `None` | Stable logical conversation identity; enables internal connection reuse on WebSocket calls. |
| `prompt_cache_key` | `None` | Explicit cache identifier; otherwise derived from `session_id`. |
| `transport` | `"sse"` | `"sse"`, `"websocket"`, or `"auto"`. |

An explicit cache key must be non-blank and at most 64 Unicode characters. A
session ID must be non-blank; IDs longer than 64 characters use a UTF-8 SHA-256
hex digest for the wire identifier, while the complete ID indexes local state.
Use ASCII session IDs for HTTP header compatibility. `session-id` and
`x-client-request-id` headers use the session identifier even when a different
cache key is supplied. These structured headers override custom headers without
regard to case. With neither argument, the SDK generates neither identifier.
Providing only a cache key does not create a persistent session. `None` means
use the session default, not disable server-side caching. No retention duration
or cache hit is guaranteed.

Install the optional transport:

```bash
pip install 'gpt-codex-client[websocket]'
```

```python
from gpt_codex_client import CodexClient

history = [{"role": "user", "content": "Explain this function."}]
with CodexClient(session_cache_max_size=32, session_cache_idle_timeout=300) as client:
    response = client.responses.create(
        model="your-model", input=history,
        session_id="conversation-42", prompt_cache_key="project-context",
        transport="websocket", preserve_context=True,
    )
    history.extend(response.to_input_items())
    history.append({"role": "user", "content": "Now summarize it."})
    followup = client.responses.create(
        model="your-model", input=history,
        session_id="conversation-42", prompt_cache_key="project-context",
        transport="websocket", preserve_context=True,
    )
    if followup.usage is not None:
        print(followup.usage.input_tokens, followup.usage.cached_tokens)
    client.close_session("conversation-42")
```

Always supply the complete history. The SDK sends `previous_response_id` plus
only the new items when the prior input and complete output are an exact prefix
and other request fields match. Otherwise it sends full context. It never edits
or automatically appends business history. For Chat, persist assistant messages
with `message.to_dict()` and keep `provider_data`; streaming clients must retain
the terminal delta's `provider_data`. Missing or edited context can prevent
incremental requests. `preserve_context` remains opt-in.

An explicitly supplied `previous_response_id` bypasses automatic planning and
uses a one-shot WebSocket without updating cached context. Such calls have no
SDK guarantee of full-history recovery. `store` remains `False` in all modes.

`websocket` exposes connection failures. `auto` falls back to SSE only before a
generation frame was submitted, such as a missing optional dependency or failed
connection. HTTP handshake rejections are surfaced. Ambiguous send failures and
interrupted output aren't replayed. An automatically generated continuation
rejected with `previous_response_not_found` before any generated output gets
at most one fresh-WebSocket full-context recovery.

### Resource ownership

Connections and prior-response snapshots belong to the client, indexed by
`session_id`; there is no public Session object. Default cache capacity is 32
entries and idle timeout is 300 seconds. Capacity must be a non-negative integer
(0 disables persistence); idle timeout must be finite and positive. Idle entries
expire automatically and are evicted in LRU order when full. Connections older
than 55 minutes are replaced before reuse. A busy session or a full cache with
no idle entry uses a one-shot full-context connection; these temporary connections
are outside the persistent cache limit. The application controls total concurrency.

`close_session(id)` / `await aclose_session(id)` clears the session's idle and
active connections, including one-shot connections. Clearing an active session
interrupts its stream. Repeated cleanup and unknown IDs are harmless.
`close()` / `await aclose()` clears all SDK-owned WebSockets and expiry tasks,
without closing a caller-supplied `httpx` client. Use an async client within one
event loop. Closing a stream early or cancelling it discards its continuation;
completed streams release their connection for reuse. Incomplete results are
returned by Responses but aren't cached for continuation.

WebSocket uses `websockets>=15,<16` independently of `httpx`. Its handshake and
receive operations use the request timeout; the close handshake is bounded to
five seconds. Environment/system proxy selection follows websockets, including
its optional SOCKS dependency requirements. Custom HTTPX transports, proxy and
TLS settings do not transfer to WebSocket. Keep `transport="sse"` when relying
on those settings. Changing the endpoint invalidates old WebSocket connections.
Account isolation and account rotation are outside this feature's scope.

## Typed usage

`Response.usage`, `ChatCompletion.usage`, and the terminal
`ChatCompletionChunk.usage` expose a public `Usage` object. Access parsed results
through `ParsedResponse.response.usage`. Intermediate Chat chunks have no usage.

| Field | Server source |
| --- | --- |
| `input_tokens` | `usage.input_tokens`, including cached input |
| `output_tokens` | `usage.output_tokens` |
| `cached_tokens` | `usage.input_tokens_details.cached_tokens` |
| `cache_write_tokens` | `usage.input_tokens_details.cache_write_tokens` |
| `reasoning_tokens` | `usage.output_tokens_details.reasoning_tokens` |
| `total_tokens` | `usage.total_tokens` |

Every counter is `int | None`: missing/null or malformed counters remain `None`,
while explicit zero remains `0`. If the server omits usage entirely, `.usage` is
`None`. Input totals are never reduced by cache counts, and total tokens aren't
computed locally. `Usage.raw` retains a deep copy including unknown fields;
`Response.raw` still retains the complete response. The SDK does not estimate
prices or infer a cache hit from connection reuse or incremental transport.
Automated regression tests verify these behaviors with offline mocks. A separate
[real protocol case](protocol.md) records synchronous WebSocket/SSE traffic; it
does not establish prompt-cache hits or latency savings.

## GPT reasoning effort

```python
response = client.responses.create(
    model="gpt-5.5",
    input="Explain the trade-offs in this design.",
    model_reasoning_effort="high",
)
```

`model_reasoning_effort` maps to the wire field `reasoning.effort`; it is not
sent as a top-level protocol field. It works with sync/async Responses `create`,
`parse`, streaming, and `chat.completions.create`. Existing `reasoning={"effort":
"high", "summary": "auto"}` and Chat `reasoning_effort="high"` remain supported.
Matching duplicate values are accepted; conflicting values raise `ValueError`
before network I/O. Other reasoning options are preserved without mutating inputs.

Omitting the option keeps the backend default. Non-empty strings are passed
through without model-name filtering or a hard-coded capability list; supported
levels depend on the model and backend. The [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
documents `minimal`, `low`, `medium`, `high`, and model-dependent `xhigh`.
This SDK does not read `model_reasoning_effort` from local Codex TOML automatically.
