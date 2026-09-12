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
