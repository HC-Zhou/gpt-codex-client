# 流式响应

`stream=True` 和聚合模式 `stream=False` 使用同一套 SSE 传输和终止状态处理。同步与异步客户端共享响应累积逻辑。

```python
with client.responses.create(model="model", input="Say hi", stream=True) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.data["delta"], end="")
    response = stream.get_final_response()
```

使用 `AsyncCodexClient` 时，对应使用 `async with`、`async for` 和 `await stream.get_final_response()`。只有消费完终止响应后才能获取最终结果；提前访问会抛出 `StreamError`，流失败后再次访问会重新抛出原始错误。

`response.completed` 和 `response.incomplete` 会立即结束消费，并在交付最后一个事件之前关闭响应。客户端不会等待 EOF，也不会继续输出尾部的 `[DONE]`。`response.done` 根据响应状态归一化；原生 Responses 在 `raw` 中保留 `incomplete_details`。未知的合法事件仍可通过原生事件迭代器读取。

`error`、`response.failed`、取消状态、非法 JSON，以及缺少终止事件的 EOF 都视为失败。仅收到 `[DONE]` 不能证明完成。部分结果处理见[错误处理](errors.md)。

如果可能提前退出迭代，请使用上下文管理器；也可以显式调用 Responses 或 Chat 流的 `close()` / `aclose()`。重复关闭是安全的。异步任务取消会继续传播并关闭响应；调用者提供的 HTTP 客户端仍由调用者管理。

## 重试边界

`max_retries` 控制实际推理请求的重试次数，最多尝试 `max_retries + 1` 次，聚合调用同样适用。连接失败、响应头到达前的超时，以及临时 HTTP 408/429/500/502/503/504 响应可以重试；额度耗尽及其他确定性请求错误不会重试。

重试响应头支持毫秒、秒和 HTTP 日期；无效值回退到指数退避。`max_retry_delay=60.0` 限制单次等待时长。若服务端要求的等待时间超过上限，返回包含原因的 API 错误，不会提前重试。失败响应会在等待前关闭。

开始消费响应体后不再透明重试，即使尚未向调用方交付事件。这避免重放部分工作，但不保证响应头到达前失败的请求在服务端恰好执行一次。
