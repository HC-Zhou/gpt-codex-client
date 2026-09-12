# Codex protocol: live capture

> This is a historical pre-release capture. Source digests and validation.json describe the capture-time snapshot, not the subsequently updated v1.0 sources.

Select 简体中文 in the site language selector for the complete reference covering SDK-to-wire
mapping, authentication headers, SSE and WebSocket event lifecycles, tool calls,
continuation state, usage, failure boundaries, and the actual payloads below.

This is a real synchronous Responses run on **2026-09-12 14:56 UTC** against
`chatgpt.com/backend-api/codex/responses`, using requested and returned model
`gpt-5.5`. The demonstration quote uses synthetic prices; the model inference and
local Decimal calculation are real. No order or payment was made.

| Turn | Transport | Full / sent input items | Sent JSON bytes | Input / output tokens | Cached / cache-write tokens |
| --- | --- | --- | ---: | --- | --- |
| 1 | WebSocket | 1 / 1 | 1,303 | 233 / 32 | 0 / 0 |
| 2 | Same WebSocket | 3 / 1 | 1,335 | 314 / 53 | 0 / 0 |
| 3 | Explicit SSE | 5 / 5 | 2,067 | 389 / 8 | 0 / 0 |

The model called `calculate_quote(unit_price=129.5, quantity=2, discount_rate=0.1)`.
The application returned a tool result of CNY 233.10. Turn 2 sent only the tool
result with `previous_response_id`, retaining `store:false`, and received the
correct explanation. Turn 3 explicitly selected SSE and replayed complete history;
it wasn't an automatic fallback.

Turn 2's equivalent full WebSocket JSON would be 1,780 bytes, versus 1,335 bytes
actually sent: **445 bytes / 25% less**. This is a same-request serialization
comparison, not a separately executed benchmark. It excludes protocol framing,
HTTP headers and TLS. Cache counters were zero, so this run demonstrates
connection reuse and incremental input, not prompt-cache hits or cost savings.

The raw `response.completed.response.output` arrays were empty in all three
turns. Tool calls and text arrived in preceding `response.output_item.done` events;
the SDK accumulated these into its final `Response`. The `turn-N-response.json`
attachments preserve raw terminal events, while `turn-N-sdk-response.json` files
are explicitly labeled offline reconstructions from the recorded events.

## Evidence

- [Manifest, timing, usage, source digests](artifacts/protocol-case-20260912-run2/manifest.json)
- [Full sanitized trace](artifacts/protocol-case-20260912-run2/trace.jsonl)
- [Summary](artifacts/protocol-case-20260912-run2/summary.json)
- [Turn 1 request](artifacts/protocol-case-20260912-run2/turn-1-request.json) / [response](artifacts/protocol-case-20260912-run2/turn-1-response.json)
- [Turn 2 request](artifacts/protocol-case-20260912-run2/turn-2-request.json) / [response](artifacts/protocol-case-20260912-run2/turn-2-response.json)
- [Turn 3 request](artifacts/protocol-case-20260912-run2/turn-3-request.json) / [response](artifacts/protocol-case-20260912-run2/turn-3-response.json)

Credentials, account identity/quota, and opaque routing state are redacted.
Encrypted reasoning would be replaced with a length and digest; none was returned
in this case. Byte counts and frame digests refer to application data before
redaction, not the pretty-printed attachments. The trace digest covers the final
sanitized JSONL. SDK events duplicate received WS frames; don't count both.

An initial capture failed while recording duplicate Set-Cookie handshake headers,
before a generation frame was sent. Its [separate failure manifest](artifacts/protocol-case-20260912/manifest.json)
is retained and excluded from the successful run's statistics.

## Reproduction

The repository script `scripts/capture_protocol_case.py` uses an existing,
unexpired SDK token and performs real model requests only when explicitly run:

```bash
uv sync --extra websocket
uv run python scripts/capture_protocol_case.py \
  --model gpt-5.5 \
  --output docs/artifacts/protocol-case-local-new
```

Use a new output directory. The script is not part of default tests. New runs may
produce different identifiers, text, token counts and timings. This case doesn't
establish real async/Chat behavior, encrypted reasoning replay, failure recovery,
other accounts/models, prompt-cache hits, or stable latency savings.
