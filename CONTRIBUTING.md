# Contributing to SuperTon

Thanks for being here. SuperTon aims to be a delightful, top-tier OSS project —
that means small, well-tested PRs and a low barrier to your first contribution.

## Setup

```bash
git clone https://github.com/rahul/superton
cd superton
uv sync --extra dev
uv run pytest
```

That's it. If `uv run pytest` passes, you're set.

## What we'd love help with

- **Importers** — pull conversations from ChatGPT exports, Cursor, Amp, Cline,
  Windsurf, Gemini, etc. See `superton/importers/claude_code.py` as the template.
- **Parsers** — better handling for `.epub`, `.html`, code repos, email mboxes.
- **Black hole themes** — alternate palettes / shapes in `superton/blackhole.py`.
- **Tests** — anything in `superton/` that lacks coverage.

## Style

- `ruff` for linting + formatting (run via `uv run ruff check . && uv run ruff format .`)
- Type hints on public functions
- Docstrings on modules and public classes; comments only when the *why* is non-obvious
- Conventional-ish commits: `feat:`, `fix:`, `docs:`, `chore:`

## PR checklist

- [ ] Tests pass: `uv run pytest`
- [ ] Lint clean: `uv run ruff check .`
- [ ] New behavior has at least one test
- [ ] README updated if user-facing surface changed

## Bug reports

Please include:
- `superton --version`
- OS + Python version
- The full command that failed and its output
- A minimal reproduction if possible
