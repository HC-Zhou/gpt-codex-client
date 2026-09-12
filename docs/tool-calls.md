# Tool Calls

Use `FunctionTool` for Responses-native tool definitions:

```python
from gpt_codex_client import FunctionTool

tool = FunctionTool(
    name="lookup",
    description="Look up a record.",
    parameters={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
)
```

Chat compatibility also accepts Chat Completions-style function tools.


## Two-turn Chat example

```python
messages = [{"role": "user", "content": "Look up record 42"}]
completion = client.chat.completions.create(
    model="model", messages=messages,
    tools=[{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}}
    }}],
    preserve_context=True,
)
assistant = completion.choices[0].message
messages.append(assistant.to_dict())
for call in assistant.tool_calls or []:
    # Your application validates arguments and executes its approved tool here.
    result = "record 42: example result"
    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
next_response = client.chat.completions.create(model="model", messages=messages)
```

The client encodes calls and results; it does not execute tools. For streaming,
assemble function arguments per tool index and wait for a terminal result before
executing them. See [Chat compatibility](chat-compatibility.md) for context storage
and [Responses](responses.md) for native item replay.
