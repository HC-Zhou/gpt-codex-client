# 身份认证

默认令牌缓存路径为 `~/.codex/auth.json`，保存时使用 `0600` 文件权限。

```python
from gpt_codex_client import login

login(no_browser=True)
```

自动化流程可以提供登录处理函数：

```python
login(login_handler=lambda url: input(f"Open {url}\nRedirect URL: "))
```

`finish_login()` 在交换授权码之前校验 OAuth `state`。`get_token()` 优先返回缓存令牌；令牌过期且存在刷新令牌时尝试刷新，刷新失败后回退到登录流程。

默认 OAuth 客户端 ID 遵循官方 Codex 客户端使用的 ChatGPT/Codex 登录流程。只有持有已注册的客户端 ID 时才覆盖该值：

```bash
export GPT_CODEX_CLIENT_OAUTH_CLIENT_ID="app_..."
```

```python
client = CodexClient(auth_client_id="app_...")
```
