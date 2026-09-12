# Release

1. Update `CHANGELOG.md` and `CHANGELOG.zh-CN.md`.
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

## Bilingual documentation

English source pages use `docs/<page>.md`; Chinese translations use
`docs/<page>.zh.md`. Shared images belong in `docs/assets/`. Keep internal links
language-neutral (for example, `responses.md`); the build resolves them to the
current language.

English remains at the site root and Chinese lives under `/zh/`. The header's
language menu links to the corresponding translation of the current page. Add
both languages for new pages and update navigation translations in `mkdocs.yml`.

Run `uv run mkdocs build --strict` before publishing. Preview locally with
`uv run mkdocs serve`.
