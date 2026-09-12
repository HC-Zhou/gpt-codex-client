# Errors

All package exceptions derive from `CodexError`.

- `AuthError`: OAuth, token cache, 401, or 403 failures.
- `InvalidRequestError`: other 4xx responses (temporary 408 can be retried).
- `RateLimitError`: 429 responses, including `retry_after`.
- `ServerError`: 5xx responses.
- `APITimeoutError` / `APIConnectionError`: opening the response failed.
- `StreamError`: protocol, provider, truncation or body-transport failure.

```python
from gpt_codex_client import StreamError

try:
    response = client.responses.create(model="model", input="Say hi")
except StreamError as error:
    print(error.kind, error.code)
    partial = error.partial_response
    if partial is not None:
        print(partial.output_text)
```

`StreamError.kind` distinguishes `failed`, `truncated`, `transport`, `protocol`,
`not_complete`, `incomplete` and `unsupported`. `raw_event` retains a provider
failure event when present. `partial_response` retains received text, identifiers
and output items; unfinished tool arguments are strings and must not be executed
as a completed call. Raw events and response data can contain opaque context and
should be handled as application data, not displayed by default.

Temporary opening failures use bounded retries; quota exhaustion is terminal.
See [Streaming](streaming.md) for exact retry and resource-lifecycle boundaries.
Async cancellation propagates as cancellation rather than a retried request.

## Migration

Previously, failure events or early EOF could produce an ordinary partial result.
They now raise `StreamError`. Catch it explicitly where partial output is useful.
The original error remains available through `get_final_response()` after failure.
