# 更新日志

本文件记录项目的所有重要变更。

条目遵循 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 格式。

## [未发布]

## [1.0.0] - 2026-09-12

### 新增

- 同步、异步 Responses、parse、流式和 Chat 接口支持 `model_reasoning_effort`，映射为 `reasoning.effort`，保留现有写法并检测冲突。
- 请求级 `session_id`、显式 `prompt_cache_key` 和可选 WebSocket 传输；SSE 仍为默认。
- 有容量上限和空闲过期的内部连接缓存、严格前缀增量续接、按会话清理，以及并发请求的一次性连接，不引入公开 Session 对象。
- auto 模式提交前安全回退 SSE，自动续接明确失效时恢复一次全量上下文；不重放结果不明的请求。
- 类型化 `Usage` 暴露六项服务端计数，缺失保留 `None`，输入总量不扣减缓存计数，并保留 raw 数据。
- 全新项目图标、中英文协议说明、脱敏的真实三轮工具调用记录，以及需显式运行的采集脚本。

### 验证与升级

- 224 项离线测试通过，覆盖 SSE/WebSocket 推理参数映射；格式、lint、严格类型检查、包构建及中英文文档严格构建均通过。

- 自动化回归使用离线模拟；另一次同步真实案例验证了 WebSocket 复用、增量提交和 SSE 回放。
- 实测第二轮 JSON 请求比同轮全量序列化减少 25%；三轮缓存读取均为零，不据此承诺缓存命中或延迟收益。
- 0.2.0 调用语法继续可用；WebSocket 需安装 `gpt-codex-client[websocket]` 并显式选择，通过 `close()` / `aclose()` 释放自有连接。
- 1.0 表示 SDK 的正式版本，私有后端协议和模型可用性仍由服务端控制。

## [0.2.0] - 2026-09-12

本版本包含自 `v0.1.1` 以来的协议可靠性和会话回放改进。

### 新增

- 同步与异步 Responses、Chat 调用支持可选的 `preserve_context`，保留不透明的推理上下文，不将其作为展示文本输出。
- 新增 `Response.to_input_items()`，通过深拷贝回放已完成的输出，保留推理项、消息阶段、工具调用 ID 和未知字段。
- 新增带版本信息的 `provider_data`、`ChatMessage.to_dict()` 和 Chat 流最终上下文，支持同模型会话回放，并校验被编辑或不兼容的历史记录。
- 为 `StreamError` 增加结构化详情：`kind`、`code`、`partial_response` 和 `raw_event`。

### 变更

- **破坏性变更：** 服务端流失败、JSON 格式错误，以及未收到终止响应就到达 EOF 的情况，现在会抛出 `StreamError`，不再返回普通的部分结果。
- **破坏性变更：** Chat 工具调用采用标准的 `id` / `type` / `function` 结构。流式调用通过稳定索引传递工具标识和参数增量。
- **破坏性变更：** Chat 结束原因区分 `tool_calls`、`stop`、`length` 和 `content_filter`；无法支持的未完成原因会触发明确错误。
- `get_final_response()` 要求已消费终止响应，并会重新抛出已记录的流失败异常。终止事件到达后立即关闭响应，不再等待 EOF，也不再输出尾部的 `[DONE]`。

### 修复

- 对齐 Codex 认证请求元数据，并通过流式后端处理聚合模式的 Responses 调用。
- 将 `max_retries` 应用于实际推理请求的打开阶段，覆盖同步、异步、流式和聚合调用。临时失败遵循重试响应头和 `max_retry_delay`；额度耗尽时不重试。
- 开始消费响应体后禁止透明重放，流中断时保留部分输出。
- 将 Chat assistant 工具调用历史转换为独立的 Responses 函数调用项，并移除工具结果项中的 Chat 角色字段。
- 保留函数工具的严格模式设置，避免参数增量后收到完整工具输出时重复交付参数。
- 统一同步与异步响应累积和资源清理逻辑，覆盖提前退出和异步取消。

### 迁移说明

- 捕获 `StreamError` 以检查部分结果；不要使用未完成的工具参数执行调用。
- 从 `call["function"]` 读取工具名称和参数，并使用 `call["id"]` 关联工具结果。
- 流式调用方必须按索引累积工具参数，并检查最终结束原因。
- 使用 `message.to_dict()` 保留可选的 `provider_data`。回放数据封套要求使用相同的提供商和模型；编辑普通 Chat 历史时，需要显式移除该封套。
- 示例见[流式接口](docs/streaming.md)、[Chat 兼容接口](docs/chat-compatibility.md)和 [Responses 回放](docs/responses.md)。

### 验证

- 135 项离线测试通过；格式检查、lint、严格类型检查和包构建均通过。
- 未对真实 OAuth 或 Codex 端点进行验证。

## 0.1.1

- 为仓库 README 和文档站点新增项目图标。
- 优化中英文 README 顶部内容，补充徽章和软件包链接。

## 0.1.0

- 初始化软件包基础结构。
- 新增 OAuth PKCE 令牌生命周期辅助功能。
- 新增同步与异步 Codex 客户端，支持 Responses、Chat 兼容接口、模型列表和 SSE 流式响应。

[未发布]: https://github.com/HC-Zhou/gpt-codex-client/compare/v1.0.0...HEAD

[0.2.0]: https://github.com/HC-Zhou/gpt-codex-client/compare/v0.1.1...v0.2.0

[1.0.0]: https://github.com/HC-Zhou/gpt-codex-client/compare/v0.2.0...v1.0.0
