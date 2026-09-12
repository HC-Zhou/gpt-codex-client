# Responses 接口

```python
from gpt_codex_client import CodexClient, FunctionTool, Reasoning

response = CodexClient().responses.create(
    model="gpt-5.5",
    input="Find the answer.",
    tools=[FunctionTool(name="lookup", parameters={"type": "object"})],
    reasoning=Reasoning(effort="medium"),
)
```

使用 `client.models.list()` 发现公开清单中的模型名称。清单中存在某个模型不代表当前账号有权调用。

## 原生输出回放

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

`to_input_items()` 按原始顺序返回已完成输出的深拷贝，保留推理项、加密内容、消息阶段、ID 和未知字段。修改副本不会影响原响应。未完成响应不能通过此辅助方法回放；请检查 `output` 和 `raw` 后显式决定如何继续。

保存历史时应记录来源模型。原生输入回放的模型兼容性由调用方负责，Chat 的版本化封套会自行校验模型。

`preserve_context=True` 将 `reasoning.encrypted_content` 合并进 `include`，不移除现有值。该选项默认关闭，在两个客户端的 `create` 和 `parse` 中均可使用。加密上下文保持不透明，不进入 `output_text`。原生输出保留 Chat 不支持的工具类型。

这些契约已通过离线 MockTransport 测试；测试不证明真实 Codex 回放或账号可用性。
