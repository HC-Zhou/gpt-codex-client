## ADDED Requirements

### Requirement: Internal bounded session cache
客户端 SHALL 按 session_id 维护私有连接及上一轮状态，不自动追加业务历史。session_cache_max_size SHALL 默认 32、允许 0 禁用缓存；session_cache_idle_timeout SHALL 默认 300 秒且为有限正数。持久条目 SHALL 不超过上限，满时淘汰空闲 LRU，全部 busy 时使用一次性连接；空闲到期 SHALL 自动清理，达到 55 分钟连接年龄 SHALL 在下次空闲获取前更换。

#### Scenario: Busy concurrent session
- **WHEN** 同 session 已有正在使用的缓存连接
- **THEN** 额外请求使用一次性全量连接，用完关闭且不更新原续接状态

#### Scenario: Capacity and expiry
- **WHEN** 达到缓存上限或空闲超时
- **THEN** 仅淘汰可淘汰条目并关闭资源，不因新请求突破持久条目上限或淘汰 busy 连接

#### Scenario: Endpoint changed
- **WHEN** 客户端目标端点变化
- **THEN** 旧端点连接失效，不被发送到新端点的请求复用

### Requirement: Exact continuation planning
SDK SHALL 深拷贝完整请求，仅当除 input/previous_response_id 外其他字段一致且当前 input 以旧 full input + 完整 output 为精确前缀时发送 ID + 尾部增量。对象键顺序 SHALL 不影响比较，数组顺序、JSON 类型、字符串及未知字段 SHALL 保留。仅 completed 且带有效 ID 的响应 SHALL 提交状态。

#### Scenario: Tool continuation
- **WHEN** 成功响应包含推理和工具调用，下一轮完整历史追加工具结果
- **THEN** 匹配时仅发送新增工具结果及 previous_response_id，store 仍为 false

#### Scenario: Changed or mutated history
- **WHEN** 历史、配置、工具或协议字段发生变化，或调用者修改此前传入的对象
- **THEN** 原快照不被污染，不匹配时发送全量；不得按可见文字相同而误判

#### Scenario: Missing Chat provider context
- **WHEN** Chat 历史丢失原始 provider_data 而无法匹配完整输出
- **THEN** SDK 发送全量，不补回已删除字段，不改变 preserve_context 默认值

#### Scenario: Explicit manual continuation
- **WHEN** 调用者显式提供 previous_response_id
- **THEN** SDK 透传该 ID，绕过自动规划及状态提交；WS 使用一次性连接且不承诺全量恢复

### Requirement: Safe recovery boundaries
显式 websocket SHALL 不自动回退 SSE；auto SHALL 仅在确定生成请求尚未提交的连接/握手失败时回退，业务拒绝 SHALL 暴露。提交状态不明或消费响应后的传输错误 MUST NOT 自动重放。自动增量收到明确 previous_response_not_found 且尚无生成输出时 SHALL 允许一次新连接全量恢复，第二次失败 SHALL 报错。

#### Scenario: Missing continuation
- **WHEN** 自动增量收到明确缺失续接错误且无生成输出
- **THEN** 清理旧状态，保存的完整请求在新 WS 上恢复最多一次

#### Scenario: Ambiguous disconnect
- **WHEN** 请求已发送后连接断开而无法确认服务端是否处理
- **THEN** 暴露现有流异常及部分结果，不回退 SSE 或自动重放

### Requirement: Explicit cleanup and lease lifecycle
close_session/aclose_session SHALL 幂等清理指定 session 的缓存、定时任务及自有活动连接，包括一次性连接，禁止旧流重新提交状态。close/aclose SHALL 清理全部 SDK 自有 WS，且不关闭外部 httpx 客户端。成功终态 SHALL 在向外 yield 前释放 lease；失败、incomplete、取消、提前退出 SHALL 清除续接并关闭连接。

#### Scenario: Clear active session
- **WHEN** 调用者清理 busy session 或关闭客户端
- **THEN** 对应连接终止，旧请求无法重新插入缓存，未知 session 和重复清理无害

#### Scenario: Completed and aborted streams
- **WHEN** 流正常 completed 或提前关闭/异步取消
- **THEN** completed 可释放并复用连接，其余情形关闭连接，取消继续传播且不缓存部分输出
