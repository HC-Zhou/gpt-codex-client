## ADDED Requirements

### Requirement: Bounded retries on the inference transport
同步和异步 Responses 请求 SHALL 在真实流打开路径应用 max_retries，最多尝试 max_retries + 1 次。建连或响应头前的可重试传输失败及 HTTP 408、429、500、502、503、504 SHALL 按策略重试；确定性额度耗尽及其他 4xx MUST 直接返回错误。响应体开始消费后 MUST NOT 自动重放。

#### Scenario: Temporary failure followed by success
- **WHEN** 首次请求返回临时 429，第二次返回完整终态，max_retries 为 1
- **THEN** 实际发送两次请求，关闭首个响应，仅返回第二次结果；stream=False 和 stream=True 均适用

#### Scenario: Quota exhausted
- **WHEN** HTTP 429 包含确定性额度耗尽错误码
- **THEN** 仅发送一次请求并保留服务端错误信息

#### Scenario: Retry delay and exhaustion
- **WHEN** 返回有效 retry-after-ms、Retry-After 秒数或日期，或连续失败耗尽预算
- **THEN** 使用对应等待时间，无有效头时指数退避，超过 max_retry_delay 时不提前重试并返回明确原因，预算耗尽时保留最终异常

#### Scenario: Failure after body consumption
- **WHEN** 响应体开始消费后连接中断，无论是否已经向调用者输出事件
- **THEN** 不创建第二次请求，并抛出携带已累积部分结果的 StreamError

### Requirement: Explicit terminal and failure semantics
流 SHALL 区分 completed、incomplete、failed 和 truncated，保留原始终态与原因。error、response.failed、cancelled、无效 JSON SHALL 暴露明确异常。缺少有效终止事件的 EOF SHALL 判定为 truncated；[DONE] 不构成 Responses 成功终态。未知合法事件 SHALL 保留透传。

#### Scenario: Provider reports failure after text
- **WHEN** 文本 delta 后收到 error 或 response.failed
- **THEN** 迭代及非流式聚合均抛出带 kind、code、raw_event 和 partial_response 的异常，部分文本仍可读取

#### Scenario: Stream ends early
- **WHEN** 文本或工具参数输出后发生 EOF，未收到有效终态
- **THEN** 抛出 truncated 错误，保留部分文本和未完成参数字符串，不返回伪造的成功结果

#### Scenario: Incomplete response
- **WHEN** 收到 response.incomplete 和 incomplete_details
- **THEN** 原生 Responses 返回 incomplete 状态与原始原因，不转换为 completed

#### Scenario: Terminal alias and malformed data
- **WHEN** 收到 response.done 或无效 JSON 数据帧
- **THEN** 前者依据 payload.status 归一化终态，后者产生协议错误；两者均不靠连接关闭推断成功

### Requirement: Final result and resource lifecycle
客户端 SHALL 在有效终态到达时关闭传输再交付终止事件，不等待服务端 EOF。最终结果在未完成消费时 MUST NOT 被伪造；失败后 get_final_response SHALL 继续暴露失败。关闭操作 SHALL 幂等，且 MUST NOT 关闭调用者拥有的 HTTP 客户端。

#### Scenario: Server keeps connection open
- **WHEN** 服务端发送 completed 或 incomplete 后保持连接
- **THEN** 调用立即完成并关闭响应，不再读取后续数据

#### Scenario: Premature final access
- **WHEN** 用户在流仍接收中调用 get_final_response
- **THEN** 返回明确 StreamError，而非缓存一个不完整最终结果

#### Scenario: Cancellation and consumer exit
- **WHEN** 异步任务取消，或消费者通过上下文管理器提前退出
- **THEN** 释放响应资源，取消异常继续传播且不重试，重复 close/aclose 无副作用

### Requirement: Shared accumulation semantics
同步与异步 SHALL 使用一致归约语义，以输出项身份累积文本和工具参数，终态数据合并后 MUST NOT 重复内容；部分结果 SHALL 保留响应 ID、模型和已经收到的输出。

#### Scenario: Deltas followed by full terminal output
- **WHEN** 同一输出先以 delta 到达，再以完整 output 到达
- **THEN** 最终文本和工具参数各出现一次，同步与异步结果一致
