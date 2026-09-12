# Chat 兼容接口

Chat 层接收 Chat Completions 风格的消息与函数工具，并将它们转换为 Responses 请求。

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

System 和 developer 消息合并为 `instructions`。

## 函数调用与结束原因

Assistant 工具历史转换为独立的 Responses `function_call` 项。工具结果转换为 `function_call_output`，使用相同的调用 ID，且不附带 Chat `role` 字段。函数工具的 `strict` 设置会保留。

返回的 `message.tool_calls` 使用 Chat 结构：

```json
{"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{}"}}
```

参数保持字符串。流式 chunk 包含稳定的 `index`、首次出现的 ID/名称以及增量 `function.arguments`，多个调用可以交错。请按索引拼接参数，不要逐片段解析。终态中的完整数据不会重复输出。

函数调用完成时结束原因为 `tool_calls`；普通完成为 `stop`；输出 token 达到上限而未完成时为 `length`；内容过滤导致未完成时为 `content_filter`。其他未完成原因抛出 `StreamError`，其 `code` 保留服务端原因。不能表示为 Chat 函数的自定义工具输出会被拒绝，请使用原生 Responses 处理。

## 可选的 Codex 上下文

传入 `preserve_context=True` 请求加密推理上下文。返回的 assistant `ChatMessage.provider_data` 是包含 `version`、`provider`、`model` 和 `output_items` 的版本化封套。保存或复用时使用 `message.to_dict()`。

回放时以封套为准，客户端会检查公开文本和工具信息是否仍与之匹配，并避免重复生成输出项。

流式调用需把最终 `ChatDelta.provider_data` 与拼接后的文本、工具信息一起保存到 assistant 消息。这是本软件包的扩展字段，不属于标准 Chat Completions 字段；持久化层必须保留它。

回放要求相同的 Codex 提供商和精确匹配的模型 ID。未知版本、模型变化或消息被编辑时，在发送前抛出 `ValueError`。如果需要编辑普通 Chat 历史，请移除 `provider_data`；这会丢失不透明推理上下文。不要将 `encrypted_content` 解码或展示为推理文本。

未完成响应不附带回放封套。上下文保留默认关闭，同步与异步接口支持相同选项。

## 迁移说明

旧版本把原生 Responses 工具对象放在 `message.tool_calls` 中。现在应读取 `call["function"]["name"]` 和 `call["function"]["arguments"]`，使用 `call["id"]` 关联结果。流式调用方需要处理工具增量和新的结束原因；`incomplete` 不再总被报告为 `stop`。
