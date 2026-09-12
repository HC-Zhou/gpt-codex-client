# Chat Compatibility

The chat layer accepts Chat Completions-style messages and function tools and
converts them into a Responses request.

```python
completion = client.chat.completions.create(
    model="model",
    messages=[
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
    ],
)
print(completion.choices[0].message.content)
```

System and developer messages are folded into `instructions`.


## Function calls and finish reasons

Assistant tool history is converted to independent Responses `function_call`
items. Tool results become `function_call_output` with the same call ID and no
Chat `role` field. Function tool `strict` is retained.

Returned `message.tool_calls` uses Chat format:

```json
{"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{}"}}
```

Arguments remain strings. Streaming chunks carry stable `index`, initial ID/name,
and incremental `function.arguments`; multiple calls can interleave. Concatenate
arguments per index, rather than parsing each fragment. Complete terminal data is
not emitted twice.

Finish reasons are `tool_calls` for completed function calls, `stop` for ordinary
completion, `length` for a token-limited incomplete response, and `content_filter`
for that incomplete reason. Other incomplete reasons raise `StreamError` with the
provider reason in `code`. Custom tool output that cannot be represented as a
Chat function is rejected; use native Responses for those items.

## Optional Codex context

Pass `preserve_context=True` to request encrypted reasoning context. The result's
assistant `ChatMessage.provider_data` is a versioned envelope containing
`version`, `provider`, `model`, and `output_items`. Use `message.to_dict()` when
saving or reusing it. The envelope is authoritative on replay; the client verifies
that the public text and tools still match it and does not duplicate the items.

For streaming, retain the final `ChatDelta.provider_data` on the assembled
assistant message alongside concatenated text and tools. It is a package extension,
not a standard Chat Completions field. Preserve it in your persistence layer.

Replay requires the same Codex provider and exact model ID. Unknown versions,
model changes, or edited messages raise `ValueError` before sending. To intentionally
edit ordinary Chat history, remove `provider_data`; this loses opaque reasoning
context. Do not decode or display `encrypted_content` as reasoning text.
Incomplete responses do not receive a replay envelope. Context preservation is
disabled by default. Both sync and async interfaces support the same options.

## Migration

Older versions returned native Responses tool objects in `message.tool_calls`.
Read `call["function"]["name"]` and `call["function"]["arguments"]` now, and use
`call["id"]` to link results. Streaming consumers must handle tool deltas and the
new finish reasons; `incomplete` is no longer always reported as `stop`.
