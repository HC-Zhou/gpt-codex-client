# 工具调用

使用 `FunctionTool` 定义原生 Responses 工具：

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

Chat 兼容接口也接受 Chat Completions 风格的函数工具。

## 两轮 Chat 示例

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

客户端负责调用与结果的编码，不执行工具。流式调用需按工具索引拼接函数参数，并等待终止结果后再执行。上下文保存方式见[Chat 兼容接口](chat-compatibility.md)，原生项回放见[Responses 接口](responses.md)。
