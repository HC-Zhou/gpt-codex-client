## 1. 缓存参数与公开接口

- [x] 1.1 实现 session/key 校验、超长 session 摘要、大小写不敏感的保留头优先级，添加边界测试
- [x] 1.2 将 session_id、prompt_cache_key、transport 贯通同步/异步 Responses create、parse、Chat create 的签名、重载和转换，验证默认 SSE 与显式 key 覆盖
- [x] 1.3 使用 httpx.MockTransport 验证 store=false、无 session、不产生额外字段、显式 None 和手动 previous_response_id 的兼容性

## 2. 类型化 usage

- [x] 2.1 新增并导出 Usage，映射六字段及独立 raw，覆盖缺失/null/零/畸形计数和不扣缓存的 token 语义
- [x] 2.2 接入 Response、ChatCompletion、终态 ChatCompletionChunk；保持 ParsedResponse.response.usage 访问，补充同步/异步和流式/聚合一致性测试

## 3. 传输与纯增量规划

- [x] 3.1 核对 Python 3.10 兼容的 websockets 同步/异步 API、握手头及代理限制，增加可选 websocket extra、开发测试依赖和缺依赖测试
- [x] 3.2 从现有流封装抽离公共事件消费与 lease 生命周期，复用 ResponseState，确保 SSE 原有终态、错误、取消和所有权测试不退化
- [x] 3.3 实现可注入的同步/异步 WS 连接适配器、response.create 帧及共同事件解码；通过假连接覆盖工具、文本、reasoning、未知事件和终态
- [x] 3.4 实现深拷贝完整快照与严格前缀规划器，覆盖空增量、字段变化、对象键顺序、类型差异、调用者修改、Chat provider_data 缺失和手动 ID 绕过

## 4. 内部会话缓存与清理

- [x] 4.1 实现实例内 session 索引、busy lease、entry 代次及 completed-only 状态提交；端点变化使旧连接失效
- [x] 4.2 实现可配置容量、空闲定时过期、单调时钟、空闲 LRU 和连接年龄更换，以假时钟测试避免真实等待
- [x] 4.3 实现同 session 并发和容量全忙时的一次性全量连接，验证不覆盖原状态、不超持久容量及异常清理
- [x] 4.4 添加 close_session/aclose_session 及客户端整体清理，覆盖 busy/一次性连接、重复清理、未知 session、计时回调竞争与外部 httpx 所有权

## 5. 恢复与完整入口验收

- [x] 5.1 实现统一 transport 选择，auto 仅提交前安全回退；覆盖业务拒绝、握手失败、发送结果不明及输出后断流
- [x] 5.2 实现自动增量 previous_response_not_found 的一次全量恢复，测试有输出时不恢复、二次失败终止及不形成重试循环
- [x] 5.3 验证 completed 释放复用、incomplete/失败/提前关闭/异步取消的连接失效和部分结果契约
- [x] 5.4 使用离线连接夹具跑通 Responses 与 Chat 多轮工具回放，覆盖同步/异步、流式/聚合、usage 与 SSE/WS 语义一致性

## 6. 文档与项目检查

- [x] 6.1 更新中英文 README、API 文档和 CHANGELOG，说明完整历史责任、provider_data、显式 key、usage None 语义、清理和缓存上限，以及可选依赖和代理限制
- [x] 6.2 明确默认 SSE、无账户隔离范围、不承诺缓存命中/费用收益、无真实端点验证及手动 ID 无恢复保证
- [x] 6.3 运行 uv run ruff format --check、uv run ruff check src tests、uv run mypy src/gpt_codex_client tests --strict、uv run pytest -q、uv build；默认测试禁止真实 OAuth/Codex 请求
