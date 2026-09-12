# Streaming

Both `stream=True` and aggregated `stream=False` use the same selected transport (SSE by default,
optional WebSocket) and terminal-state handling. Sync and async clients share the response accumulator.

```python
with client.responses.create(model="model", input="Say hi", stream=True) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.data["delta"], end="")
    response = stream.get_final_response()
```

Use `async with` and `async for` with `AsyncCodexClient`, and await
`stream.get_final_response()`. A final result is available only after consuming a
terminal response. Access before completion raises `StreamError`; after a stream
failure it raises the original stream error again.

`response.completed` and `response.incomplete` terminate consumption immediately
and close the response before the final event is delivered. The client does not
wait for EOF or expose a trailing `[DONE]`. `response.done` is normalized using
its response status. Native Responses preserves `incomplete_details` in `raw`.
Unknown valid events remain available through the native event iterator.

`error`, `response.failed`, cancellation statuses, malformed JSON, and EOF without
a terminal event are failures. A bare `[DONE]` is not proof of completion. See
[Errors](errors.md) for partial results.

Always use a context manager if you might stop iteration early. Alternatively,
call `close()` / `aclose()` on the Responses or Chat stream. Repeated closure is
safe. An async task cancellation propagates and closes the response; a supplied
HTTP client remains owned by its caller.

## Retry boundary

`max_retries` controls actual inference attempts (at most `max_retries + 1`),
including aggregated calls. Connection failures and timeouts before response
headers, and temporary HTTP 408/429/500/502/503/504 responses, can be retried.
Quota exhaustion and other deterministic request errors are not retried.

Retry delay headers support milliseconds, seconds and HTTP dates; invalid values
fall back to exponential backoff. `max_retry_delay=60.0` limits each retry wait.
If a required delay exceeds the limit, the API error is returned with the reason;
the client never retries sooner than the server requested. Failed responses close
before waiting. After response-body consumption starts, there is no transparent
retry, even if no event has yet been delivered. This avoids replaying partial work;
it is not an exactly-once execution guarantee for requests failing before headers.

Optional WebSocket transport uses the same terminal-state accumulation. A completed
WebSocket stream releases the connection for reuse; early exit or failure closes it.
See the [live protocol capture](protocol.md) for actual event examples.
