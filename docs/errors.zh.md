# 错误处理

所有软件包异常都继承自 `CodexError`。

- `AuthError`：OAuth、令牌缓存、401 或 403 错误。
- `InvalidRequestError`：其他 4xx 响应，其中临时 408 可以重试。
- `RateLimitError`：429 响应，包含 `retry_after`。
- `ServerError`：5xx 响应。
- `APITimeoutError` / `APIConnectionError`：打开响应失败。
- `StreamError`：协议、服务端、截断或响应体传输错误。

```python
from gpt_codex_client import StreamError

try:
    response = client.responses.create(model="model", input="Say hi")
except StreamError as error:
    print(error.kind, error.code)
    partial = error.partial_response
    if partial is not None:
        print(partial.output_text)
```

`StreamError.kind` 区分 `failed`、`truncated`、`transport`、`protocol`、`not_complete`、`incomplete` 和 `unsupported`。存在服务端失败事件时，`raw_event` 保留原始事件。

`partial_response` 保留已收到的文本、标识和输出项。未完成的工具参数仍是字符串，不能当作完整调用执行。原始事件和响应可能包含不透明上下文，应作为应用数据处理，不默认展示。

打开响应时的临时失败采用有界重试，额度耗尽直接失败。具体重试与资源生命周期边界见[流式响应](streaming.md)。异步取消按取消异常传播，不会触发重试。

## 迁移说明

旧版本可能把失败事件或提前 EOF 转为普通的部分结果。现在会抛出 `StreamError`；需要部分结果的调用方应显式捕获。流失败后，`get_final_response()` 会继续暴露原始异常。
