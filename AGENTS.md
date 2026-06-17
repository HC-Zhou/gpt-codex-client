# AGENTS.md

This repository is a typed Python package using a `src/` layout and `uv`.

## Local Checks

Run these before publishing:

```bash
uv run ruff format --check
uv run ruff check src tests
uv run mypy src/gpt_codex_client tests --strict
uv run pytest -q
uv build
```

Default tests must not call live OAuth or ChatGPT/Codex endpoints. Use `httpx.MockTransport` for integration-style coverage.

