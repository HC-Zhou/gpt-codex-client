# Changelog

All notable changes to this project are documented in this file.

Entries follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.0.0] - 2026-09-12

### Added

- `model_reasoning_effort` on all Responses and Chat request entrypoints, mapped to `reasoning.effort` with conflict detection and existing option compatibility.
- A new generated project icon for README and documentation.
- A detailed protocol reference with a sanitized real three-turn tool-use trace and an opt-in capture script.

- Request-level `session_id`, explicit `prompt_cache_key`, and optional WebSocket transport across synchronous/asynchronous Responses, parsing, and Chat APIs; SSE remains the default.
- Bounded internal session connection reuse, strict full-history-to-delta planning, idle expiry, per-session cleanup, and one-shot connections for concurrent requests without a public Session object.
- Safe pre-submission SSE fallback in auto mode and one full-context recovery for an explicitly missing automatic continuation; ambiguous failures aren't replayed.
- Public typed `Usage` with six server counters, unknown values preserved as `None`, unmodified input totals, and raw usage retention across Responses and terminal Chat results.

### Fixed

- Preserved asynchronous WebSocket cancellation on Python 3.10/3.11 when cancellation races with completed I/O; timed-out child operations are cancelled and drained before releasing the session.

### Validation and upgrade

- 226 offline tests passed, including reasoning alias mapping across SSE and WebSocket entrypoints; formatting, lint, strict typing, package build, and strict bilingual documentation build passed.

- Automated tests use offline mocks; the recorded synchronous real case separately verifies WebSocket reuse, delta submission, and SSE replay.
- The real second request used 25% fewer JSON bytes than its full equivalent; all three requests reported zero cache-read tokens. No prompt-cache or latency benefit is claimed.
- Existing 0.2.0 call syntax remains valid. WebSocket is opt-in: install `gpt-codex-client[websocket]` and close owned connections with `close()` / `aclose()`.
- This is the SDK's 1.0 release; the private backend protocol and model availability remain server-controlled.

## [0.2.0] - 2026-09-12

This version includes protocol reliability and conversation replay improvements since `v0.1.1`.

### Added

- Optional `preserve_context` support on synchronous and asynchronous Responses and Chat calls, retaining opaque reasoning context without exposing it as display text.
- `Response.to_input_items()` for deep-copy replay of completed output, preserving reasoning items, message phases, tool-call IDs, and unknown fields.
- Versioned `provider_data`, `ChatMessage.to_dict()`, and final Chat stream context for same-model conversation replay, with validation of edited or incompatible history.
- Structured `StreamError` details: `kind`, `code`, `partial_response`, and `raw_event`.

### Changed

- **Breaking:** provider stream failures, malformed JSON, and EOF without a terminal response now raise `StreamError` instead of returning an ordinary partial result.
- **Breaking:** Chat tool calls now use the standard `id` / `type` / `function` structure. Streaming calls deliver tool identity and argument deltas with stable indexes.
- **Breaking:** Chat finish reasons distinguish `tool_calls`, `stop`, `length`, and `content_filter`; unsupported incomplete reasons raise an explicit error.
- `get_final_response()` requires a consumed terminal response and re-raises a recorded stream failure. Terminal events close the response immediately, without waiting for EOF or emitting a trailing `[DONE]`.

### Fixed

- Aligned Codex authentication request metadata and routed aggregated Responses calls through the streaming backend.
- Applied `max_retries` to actual inference opening requests, including synchronous, asynchronous, streamed, and aggregated calls. Temporary failures honor retry headers and `max_retry_delay`; quota exhaustion is not retried.
- Prevented transparent replay after response-body consumption begins, preserving partial output when a stream is interrupted.
- Converted Chat assistant tool history into independent Responses function-call items and removed the Chat role field from tool-result items.
- Preserved function-tool strictness and avoided duplicate argument delivery when deltas are followed by complete tool output.
- Unified synchronous and asynchronous response accumulation and resource cleanup, including early exit and asynchronous cancellation.

### Migration

- Catch `StreamError` to inspect partial results; do not execute incomplete tool arguments.
- Read tool names and arguments from `call["function"]`, and associate results using `call["id"]`.
- Streaming consumers must accumulate tool arguments per index and inspect the final finish reason.
- Use `message.to_dict()` to retain optional `provider_data`. Replay envelopes require the same provider and model; remove the envelope explicitly when editing ordinary Chat history.
- See [streaming](docs/streaming.md), [Chat compatibility](docs/chat-compatibility.md), and [Responses replay](docs/responses.md) for examples.

### Validation

- 135 offline tests passed; formatting, lint, strict type checking, and package builds passed.
- No live OAuth or Codex endpoint validation was performed.

## 0.1.1

- Added a project icon for the repository README and documentation site.
- Improved the English and Chinese README headers with badges and package links.

## 0.1.0

- Initial package scaffold.
- Added OAuth PKCE token lifecycle helpers.
- Added sync and async Codex clients with Responses, chat compatibility, models, and SSE streaming.

[Unreleased]: https://github.com/HC-Zhou/gpt-codex-client/compare/v1.0.0...HEAD

[0.2.0]: https://github.com/HC-Zhou/gpt-codex-client/compare/v0.1.1...v0.2.0

[1.0.0]: https://github.com/HC-Zhou/gpt-codex-client/compare/v0.2.0...v1.0.0
