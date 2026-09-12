## Context

现有客户端通过 httpx SSE 实现流式与聚合接口；ResponseState 已独立于传输。Response.to_input_items() 和 Chat provider_data 支持无损回放。已有协议加固设计要求消费响应后不自动重放、仅 completed 默认可回放、调用者提供的 httpx 客户端不由 SDK 关闭。本变更沿用这些约束，Pi 仅为实现参考而非真实端点验证证据。

## Goals / Non-Goals

**Goals:** 请求参数驱动内部会话缓存、完整历史到增量的透明转换、明确资源上限与清理、六字段类型化 usage、所有入口一致。

**Non-Goals:** 账户隔离及轮换策略、公开 Session 对象、自动保存或追加业务历史、工具执行、zstd、费用估算、真实服务测试及发布。

## Decisions

### 1. 请求参数与兼容默认值

同步/异步 Responses.create、Responses.parse、Chat.completions.create 接受 session_id: str | None、prompt_cache_key: str | None、transport: Literal['sse', 'websocket', 'auto']，默认 sse。session_id 保留原值用于内部索引，不能为空白；prompt_cache_key 若提供则必须为非空白且至多 64 个 Unicode 字符。未提供 key 时，由 session_id 得到 key：不超过 64 字符原样使用，超长使用 SHA-256 十六进制摘要，避免简单截断碰撞。显式 None 与省略均表示使用会话默认，不承诺关闭服务端缓存。

请求体发送有效 prompt_cache_key；session_id 存在时，session-id 与 x-client-request-id 使用规范化后的 session 标识（不是显式覆盖的 cache key）。没有 session 时不添加会话头或建立持久会话状态；只有 cache key 仍可发送。合并头时大小写不敏感，结构化 session 参数对这两个保留头拥有优先级。不发送 session_id 到请求体，不新增 prompt_cache_retention。

替代方案：全客户端生成一个会话会混合多段对话；每请求生成新 key 失去稳定性，因此均不采用。transport 只在一处归一化，避免 Pi 的省略与显式 auto 差异。

### 2. 传输分层与内部会话状态

Chat 转为 Responses items 后，创建完整深拷贝请求快照，再由共同规划器选择全量或增量。SSE/WS 解码为共同事件，交给现有 ResponseState；同步与异步共享比较、usage 和事件语义，I/O 与锁分别实现。WS 使用可选 extra `websocket`，采用支持 Python 3.10 同步/异步接口的 websockets 版本；实施时核对版本 API 并锁定兼容下限。未安装时显式 websocket 给出安装提示，auto 在发送前回退 SSE，默认安装保持仅 httpx。

每个客户端实例内部按原始 session_id 索引连接；客户端目标端点固定，修改 base_url 后必须失效旧连接。entry 包括 busy、socket、last_used、created_at、深拷贝 full_body、response_id 和完整 output_items。无 session 使用一次性连接。缓存只在 completed 且有非空 response id 后提交，incomplete、错误、提前关闭或取消均不建立续接状态。

第一版不引入 Session 包装层，调用方始终提交完整 input/messages。显式 previous_response_id 原样透传，并绕过自动规划及状态提交、使用一次性 WS（SSE 保持现状）；不承诺手动 ID 的全量恢复。

### 3. 严格增量和无损历史

去掉 input/previous_response_id 后的请求字段必须一致；current input 必须以 last full input + last output 为精确前缀。使用保留 JSON 类型的递归比较或规范 JSON 比较：对象键顺序忽略，数组顺序、数值类型、字符串内容、未知字段均保留，不改写工具 arguments 字符串。不同则清除 baseline 并发送全量；匹配则发送 previous_response_id 与尾部 input，空尾部也合法。

缓存输出使用完整原始 output，不只保存可见文字。保留现有 preserve_context=False 默认，不自动补回调用方删除的内容。文档推荐 Agent 使用 preserve_context=True，并保留 Chat provider_data；缺失这些字段导致不匹配时透明退回全量。快照与输出均深拷贝，避免调用方后续修改污染基线。

### 4. 资源预算与并发

构造参数 session_cache_max_size 默认 32（非负整数，0 禁用缓存），session_cache_idle_timeout 默认 300 秒（有限正数）。容量指持久缓存条目，包括 busy 条目；满时淘汰最久未用的空闲条目，全部 busy 则新请求使用一次性连接，不超出缓存上限。一次性并发连接不计入缓存容量，整体并发仍由调用者控制。

获取/释放缓存时加短时锁，网络操作不持有全局锁。同 session 已 busy 时，新请求使用一次性全量连接且不更新原 entry。空闲采用定时到期清理，并在获取时检查过期；连接达到 55 分钟时在下次空闲获取前换新。计时使用单调时钟；过期回调校验 entry 身份和代次，不能关闭替换后的连接。

公开 close_session(session_id) / async aclose_session(session_id)，清除指定连接、baseline、定时器；重复调用无害。清理 busy session 会中止其活动流并禁止该流重新提交缓存，影响范围包含该 session 的一次性连接。client.close()/aclose() 清理所有 SDK 自有 WS、一次性连接及计时任务；仍不关闭外部 httpx 客户端。未知 session 为 no-op。

### 5. 有界恢复和流生命周期

显式 websocket 不自动改走 SSE。auto 仅在请求帧发送前且确定未提交生成请求的连接/握手失败时回退 SSE；认证、额度等明确业务拒绝直接暴露。发送失败但提交情况不明、任意响应消费后的传输错误均不重放。

唯一协议级恢复例外：SDK 自动生成的增量请求收到明确 previous_response_not_found，且无任何生成输出时，清理连接并用保存的完整请求在新 WS 上恢复一次。已经有输出或第二次失败直接报错，恢复不重置一般重试预算或形成循环。SSE 保持既有重试语义，store 始终 false。

流 close 释放 lease 而非无条件关闭可复用 WS；completed 时在终态事件对外 yield 前提交状态并释放 lease。incomplete 可返回原生结果但清除续接并关闭连接。提前退出、取消、失败关闭连接并保留现有 partial_response/异常语义，避免未读事件污染下次请求。

### 6. Usage 是服务端计量的类型化投影

公开 Usage 数据类，六个字段均为 int | None，缺失/null 保留 None、零保留 0；非负整数之外的畸形值不强制转换，类型化字段为 None，原数据仍保留。路径为 usage.input_tokens、output_tokens、total_tokens、input_tokens_details.cached_tokens、input_tokens_details.cache_write_tokens、output_tokens_details.reasoning_tokens。

Response.usage 在无 usage 时为 None；有 usage 对象时构造 Usage，并保留独立的 Usage.raw。input_tokens 不减缓存，total_tokens 不自行求和。ParsedResponse 通过 response.usage 访问。ChatCompletion.usage 与终态 ChatCompletionChunk.usage 暴露相同对象语义，非终态 chunk 为 None；流聚合与同步/异步一致。不捏造命中率或价格，也不将缺失解释为零。

## Risks / Trade-offs

- WS 后端兼容性未经实测 → 默认 SSE，使用可注入假连接验证契约，文档明确证据范围。
- 缓存占用历史内存与连接 → 有限条目、深拷贝、过期与显式清理；第一版不额外做压缩或字节预算。
- 同步/异步清理竞争与超时 → entry 代次、短时锁、假时钟及 busy 清理测试。
- 标准 Chat 历史可能丢失原始项 → 推荐 provider_data，无匹配则全量，不静默修补。
- 自定义 httpx 代理/证书配置不会自动迁移到 WS → 文档明确 WS 连接选项和依赖的独立性；不支持的配置保持 SSE，不承诺透明继承。

## Migration Plan

先添加缓存参数和 Usage（均向后兼容），再引入可选传输与内部缓存，最后贯通各入口及文档。默认 SSE 和 preserve_context 默认不变。全部仓库检查通过后方可单独考虑发布；本变更不自动发布。回滚可移除新参数、固定 transport=sse 或退回前一版本，无持久数据迁移。

## Open Questions

无阻塞产品决策。实施时核对 websockets 的 Python 3.10 兼容版本、握手头和代理接口，并用假连接固定契约；真实 Codex 对 WS 的可用性不属于本变更离线验收证明。
