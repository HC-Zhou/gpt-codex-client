## ADDED Requirements

### Requirement: Consistent cache parameters across SDK entrypoints
同步/异步 Responses create、parse 和 Chat create SHALL 接受 session_id、prompt_cache_key、transport。默认 transport SHALL 为 sse，store SHALL 保持 false；不得新增公开 Session 对象。

#### Scenario: Default compatibility
- **WHEN** 现有调用没有传入新参数
- **THEN** 仍使用 SSE，不自动生成会话或缓存 key，现有结果与异常语义保持一致

#### Scenario: Explicit cache key
- **WHEN** 调用方指定 session_id 和 prompt_cache_key
- **THEN** 所有入口发送显式 prompt_cache_key，会话索引仍使用 session_id

### Requirement: Deterministic identity normalization
SDK SHALL 拒绝空白 session_id 及空白或超过 64 Unicode 字符的显式 prompt_cache_key。未指定 key 时 SHALL 使用 session_id，超过 64 字符的 session_id SHALL 以 UTF-8 SHA-256 十六进制摘要规范化到线上标识。内部索引 SHALL 保留完整 session_id。

#### Scenario: Long session identifier
- **WHEN** 同一超长 session_id 被重复使用且没有显式 key
- **THEN** 线上 key 与会话头使用一致稳定摘要，内部索引不截断

#### Scenario: Header precedence
- **WHEN** session_id 存在且自定义头含任意大小写的 session-id 或 x-client-request-id
- **THEN** SDK SHALL 大小写不敏感地覆盖这两个头为规范化 session 标识，显式 cache key 不改变会话头

#### Scenario: Cache key without session
- **WHEN** 仅提供 prompt_cache_key
- **THEN** 请求体包含 key，但不产生持久会话或 SDK 会话头

### Requirement: Explicit transport selection
SDK SHALL 支持 sse、websocket、auto；websocket 缺少可选依赖时 SHALL 明确报安装错误，auto SHALL 在发送前退回 SSE。省略参数和显式 sse SHALL 等价。SDK MUST NOT 宣称 cache key 控制服务端缓存保留时长或保证命中。

#### Scenario: Missing optional dependency
- **WHEN** 未安装 WebSocket extra
- **THEN** 默认 SSE 不受影响，显式 websocket 报可操作错误，auto 使用 SSE
