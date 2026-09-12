## Context

Responses 的 stream=False 实际也通过 SSE 聚合。当前 `_request` 重试未覆盖 `_stream`；同步与异步流各自累积文本，缺少错误与 EOF 契约。Chat 转换没有完整实现工具调用双向映射。Pi 本地适配可参考其事件归一化、工具回放和失败边界，但不作为 Codex 后端兼容性的实测证明。

## Goals / Non-Goals

**Goals:**
- 四种同步/异步、流式/聚合组合共享相同失败、结束及工具回放语义。
- 明确可重试边界，失败时可检查部分结果，终止时及时释放连接。
- 保留不透明推理项及来源模型，支持显式的同模型回放。

**Non-Goals:**
- WebSocket、后台刷新、真实账号探测、自动模型切换、工具执行器、多提供商统一内核。
- 本轮不构建完整模型能力规则库，不从模型名猜测能力，不执行真实 OAuth 或推理测试。

## Decisions

### 1. 将重试放入实际打开流的路径

使用可重复创建 HTTP 请求上下文的工厂，统一重试分类与延迟计算；同步和异步仅区别 I/O 与等待。总尝试次数为 max_retries + 1。重试范围限建连失败、响应头前超时，以及 HTTP 408、429、500、502、503、504；额度耗尽的结构化错误码优先排除，已知额度错误文本仅作兼容补充，其余 4xx 不重试。

支持 retry-after-ms、Retry-After 秒数/HTTP 日期；无有效值时使用当前指数退避。新增 max_retry_delay 默认 60 秒，服务端要求超过上限时返回原 API 错误并说明停止重试原因，禁止缩短服务端要求后提前重试。每次失败尝试关闭响应后再等待。

一旦响应体开始消费，不自动重试，包括首个事件之前的异常 EOF；更保守的边界避免已处理但尚未发出事件的请求被重放。中途断流使用带部分结果的 StreamError，异步取消继续传播 CancelledError，finally 负责关闭。替代方案“完整请求失败后重跑”无法避免重复生成，因此不采用。

### 2. 共享事件归约器，分离传输和语义

引入内部纯状态归约器，供同步/异步流及 Chat 投影共用。保留 response id/model、按 output_index/item id 累积文本与工具参数、原始输出项及终态。终态完整输出优先合并，避免 delta/done 重复累加。

状态为 receiving、completed、incomplete、failed、truncated。response.done 按 payload.status 归一化；completed 与 incomplete 为可返回终态，保留 incomplete_details。error、response.failed 与 cancelled 状态转为异常；有效终止事件之前的 EOF（含仅收到 [DONE]）为 truncated。无效 JSON 数据帧产生协议错误；未知但合法事件保留透传，不默认为成功。

扩展 StreamError，提供 kind、code、partial_response、raw_event；沿用原异常继承兼容 catch。HTTP 失败继续使用 APIError 类型。get_final_response 在未消费至终态时抛出 StreamError，禁止伪造最终结果；失败后再次调用仍暴露原失败。合法终态处理时在向外 yield 最后事件之前关闭传输；不关闭调用者提供的 httpx.Client。消费者提前退出应使用上下文管理器或 close/aclose，文档明确这一责任。

### 3. Chat 是严格协议投影

assistant 文本转换为消息项，tool_calls 转换为独立 function_call（call_id、name、arguments）；工具结果仅包含 function_call_output 所需字段，不附带 role。Chat 函数工具声明的 strict 字段保留。缺失必要 ID、名称或非字符串 arguments 以本地校验错误暴露。

反向工具结构使用 {id: call_id, type: function, function: {name, arguments}}，arguments 保持 JSON 字符串。流式按输出项维护稳定 Chat tool index，首次发送 id/type/name，随后发送 arguments 片段；交错工具独立累积，done 的完整参数不重复发出。仅终态包含工具信息时补发缺失片段；无法与已有片段一致合并则报协议错误。

结束原因优先处理 incomplete：max_output_tokens→length，content_filter→content_filter，其他原因保留并抛出明确错误；completed 含工具调用→tool_calls，否则 stop。Responses 原生 incomplete 仍返回其完整状态，Chat 不将未知 incomplete 伪装成 stop。自定义工具等无法表达为 Chat function 的输出明确报不支持，原生 Responses 保留原始项。

### 4. 显式、无损、可序列化的回放契约

新增 Response.to_input_items() 返回可独立修改的 output 深拷贝，保留推理项、encrypted_content、消息 phase、调用 ID 和未知字段；仅成功 completed 响应可直接回放，失败或 incomplete 结果须由调用方显式处理。调用方拼接原始输入、这些输出和 function_call_output，工具执行仍由上层负责。

新增显式 preserve_context 参数（默认 False），启用时在请求 include 中合并 reasoning.encrypted_content，保留调用方已有 include。该参数对原生 Responses 和 Chat 同步/异步入口一致可用。

ChatMessage 增加可选 provider_data，并提供 to_dict() 作为支持往返的序列化入口。扩展采用版本化封套：version=1、provider=codex、model、output_items。启用 preserve_context 时，非流式 assistant 消息和流式最终 ChatDelta 承载该封套，业务方负责在多轮历史中保留。回放时封套作为该 assistant 的权威输出，不再重复生成同一条文本/工具项；校验公开文本及工具投影一致，编辑过的消息拒绝回放并提示移除扩展。

封套只保证同 provider、同 model 回放；跨模型或未知版本明确拒绝，不自动丢弃加密项或修改调用 ID。加密内容仅存在原始数据和 provider_data，不进入 content/output_text，也不写入默认错误消息。保留 Model.raw 原始能力字段，文档说明缺失字段代表未知、目录不证明账号可用；不新增未经证实的能力推断。

替代方案“所有 Chat 消息默认携带原始数据”增加体积和隐式行为，因此采用显式开关；“仅保留文字推理摘要”不能保证协议回放，不采用。

## Risks / Trade-offs

- 错误行为和 Chat 工具结构改变 → 发布迁移说明，列出旧/新返回与捕获异常示例。
- 中断前部分参数可能不是合法 JSON → 保留字符串，不自动执行或伪造完整参数。
- 原始回放数据增加内存与持久化体积 → preserve_context 默认关闭，深拷贝避免别名修改。
- Codex 服务端协议可能漂移 → 用版本化夹具与未知字段保留验证本地契约，离线测试不宣称真实端点验证。
- 同步/异步资源生命周期差异 → 共用归约器，分别验证关闭、取消和所有权。

## Migration Plan

先建立失败和工具回放的离线回归用例，再实现共享状态与传输重试，完成 Chat 投影及可选回放扩展，最后更新文档和 CHANGELOG。运行仓库规定的全部检查后按发布策略发布；本变更不自动发布。回滚采用恢复先前包版本，新增 provider_data 为可选且无存储迁移；文档明确旧版无法提供新增可靠性保证。

## Open Questions

无阻塞设计问题。真实端点对加密推理回放的可用性需未来另行授权验证；本变更验收以离线协议契约为准，不自动触发该验证。
