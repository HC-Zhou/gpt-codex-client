# Authentication

The default token cache is `~/.codex/auth.json`. Tokens are saved with `0600`
permissions.

```python
from gpt_codex_client import login

login(no_browser=True)
```

Automation can provide a handler:

```python
login(login_handler=lambda url: input(f"Open {url}\nRedirect URL: "))
```

`finish_login()` validates OAuth `state` before exchanging an authorization
code. `get_token()` returns a cached token, refreshes expired tokens when a
refresh token exists, and falls back to login if refresh fails.

The default OAuth client id follows the ChatGPT/Codex sign-in flow used by the
official Codex clients. Override it only when you have a registered client id:

```bash
export GPT_CODEX_CLIENT_OAUTH_CLIENT_ID="app_..."
```

```python
client = CodexClient(auth_client_id="app_...")
```
