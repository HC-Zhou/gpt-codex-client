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

