# Errors

All package exceptions derive from `CodexError`.

- `AuthError`: OAuth, token cache, 401, or 403 failures.
- `InvalidRequestError`: non-retryable 4xx request failures.
- `RateLimitError`: 429 responses, including `retry_after`.
- `ServerError`: 5xx responses.
- `APITimeoutError`: request timeout.
- `APIConnectionError`: transport-level failures.
- `StreamError`: stream lifecycle failures.

429 and 5xx responses are retried with exponential backoff up to
`max_retries`.

