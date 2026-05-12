# Release Guide

SuperTon ships as a normal Python CLI package.

## User Install

```bash
uv tool install "git+https://github.com/therahul-yo/Superton.git"
superton init
superton
```

After PyPI publishing:

```bash
uv tool install superton
superton init
```

## Local Release Check

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build
uv tool install dist/superton-0.1.0-py3-none-any.whl --force
superton --version
superton doctor
```

## Publish

1. Update `version` in `pyproject.toml` and `superton/__init__.py`.
2. Update the changelog/release notes.
3. Run the local release check.
4. Tag the release:

```bash
git tag v0.1.0
git push origin main --tags
```

5. Publish to PyPI when credentials are configured:

```bash
uv publish
```

## Runtime Notes

`superton init` creates the local palace, starts Ollama when possible, prompts
before pulling model weights, and builds the local `miniton` model from the
packaged `superton/Modelfile`.

If Ollama is unavailable, users can set `SUPERTON_MODEL_BACKEND=huggingface`
and `HF_TOKEN` to use Hugging Face Inference.
