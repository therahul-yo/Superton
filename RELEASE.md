# Release Guide

SuperTon ships as a normal Python CLI package. The recommended install
path is `uv tool install`, with `pip install` and `pipx install` as
supported alternatives.

Current version: **0.2.0**. See [CHANGELOG.md](CHANGELOG.md) for what
landed.

## User Install

```bash
# one-liner installer (pulls the [tui] extra by default)
curl -fsSL https://raw.githubusercontent.com/therahul-yo/Superton/main/install.sh | sh

# or manually with uv
uv tool install --with "textual>=0.60.0" "git+https://github.com/therahul-yo/Superton.git"

superton init
superton            # interactive shell
superton tui        # full-screen Textual interface
```

Set `SUPERTON_NO_TUI=1` before running `install.sh` to skip the TUI
extra (saves ~20 MB of Textual + linkify deps).

After PyPI publishing:

```bash
uv tool install "superton[tui]"
superton init
```

## Local Release Check

Run before every tag:

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy superton
uv run pytest -q
uv run pytest --cov=superton --cov-fail-under=45
uv build
uv tool install dist/superton-0.2.0-py3-none-any.whl --force
superton --version          # expects "superton 0.2.0"
superton doctor             # every row should be ok or a known-warn
superton init --no-model -y # confirm preflight card + ready card render
```

## Publish

1. **Bump versions** in `pyproject.toml` and `superton/__init__.py` —
   they should match the new tag exactly.
2. **Add a new section** to `CHANGELOG.md` describing the release.
   Follow the existing format: Highlights → Added → Changed → Fixed →
   Breaking → Migration → Stats.
3. **Run the local release check** above. CI on the PR must be green
   (Linux + macOS × 3.11 + 3.12, plus the typecheck job).
4. **Tag the release** and push:

   ```bash
   git tag v0.2.0
   git push origin main --tags
   ```

5. **Publish to PyPI** once credentials are configured:

   ```bash
   uv publish
   ```

6. **Smoke-test the published wheel** in a clean environment:

   ```bash
   uvx --refresh "superton[tui]" --version
   uvx --refresh "superton[tui]" tui
   ```

## Versioning Policy

- `0.x.0` — minor releases. May include breaking changes; documented
  in the **Breaking** section of the changelog with a migration note.
- `0.x.y` — patch releases. Bug fixes only, no API or default changes.
- Pre-1.0.0 alpha/rc suffixes (`0.x.0a1`, `0.x.0rc1`) for staging
  releases before a public minor bump.

`0.2.0` is the first proper "production-grade alpha" release with a
real changelog and CI gates. Future versions should compound on this
foundation rather than rewrite it.

## Runtime Notes

`superton init` creates the local palace, starts Ollama when possible,
prompts before pulling model weights, and builds the local `miniton`
model from the packaged `superton/Modelfile`. The Modelfile pins
`num_ctx 16384` and a low temperature so RAG answers stay terse and
citation-friendly.

If Ollama is unavailable, users can set `SUPERTON_MODEL_BACKEND=huggingface`
and `HF_TOKEN` to use Hugging Face Inference.

## Hot Issues to Verify Before Tagging

These are the failure modes that have bitten releases in the past —
walk through each before pushing a tag:

- **Coverage gate**: `--cov-fail-under=45` is set in CI. Adding new
  un-tested code can drop below this. Run the cov check locally.
- **macOS CI**: textual + pytest-asyncio + Pilot occasionally trip on
  macOS GitHub runners. Tests must pass on both Linux and macOS.
- **TUI extra**: a vanilla `pip install superton` doesn't pull
  Textual. `superton tui` is supposed to print a clean recovery hint
  rather than crash — verify manually.
- **Uninstall leak**: `superton uninstall` must remove
  `~/.local/bin/superton`. The `os.execvp` path is fragile across
  installers — verify on at least uv + pipx.
- **Legacy profile migration**: users with
  `model_profile = "fast"` in their config must auto-upgrade to
  `photon` with a warning, not crash.

## Rollback

If a published release has a critical bug:

1. Yank the affected version from PyPI: `uv publish --yank superton==0.2.0`
2. Push a patch release (`0.2.1`) with the fix.
3. Add a "Known issues" note to the affected version in
   `CHANGELOG.md` linking to the patch.
