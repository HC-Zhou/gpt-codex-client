# Release

1. Update `CHANGELOG.md`.
2. Ensure `src/gpt_codex_client/__init__.py` and `pyproject.toml` versions match.
3. Run:

```bash
uv run ruff format --check
uv run ruff check src tests
uv run mypy src/gpt_codex_client tests --strict
uv run pytest -q
uv build
```

4. Tag `vX.Y.Z` and push the tag.

