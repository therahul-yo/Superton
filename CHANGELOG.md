# Changelog

All notable changes to SuperTon are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches 1.0.0. Until then, every minor bump may include breaking
changes — they are called out in the **Breaking** section.

## [Unreleased]

### Removed (BREAKING)

- **Textual TUI.** `superton tui`, the `[tui]` optional extra, the
  `superton/tui/` module, and all related docs (`docs/TUI_ARCHITECTURE.md`,
  TUI sections in README/RELEASE/UX_PLAN/UX_ROADMAP) are gone. The
  classic prompt-toolkit shell (`superton`) is now the only interactive
  surface. Reasoning: the TUI duplicated maintenance against the shell
  without earning sticky usage. If you were running `superton tui`,
  switch to plain `superton`; retrieval, slash commands, and theming
  are identical.

### Changed

- `install.sh` no longer offers a `[tui]` extra path. `SUPERTON_NO_TUI`
  is also removed — the variable is now a no-op.
- `pyproject.toml`: dropped the `tui` optional-dependencies entry and
  the dev-extra `textual` pin.
- `superton/chat.py`, `superton/shell.py`, `superton/ui.py`: scrubbed
  TUI references from docstrings, comments, and the `ready_card` install
  ladder.

## [0.3.0-beta.1] — 2026-05-23

First **beta** release — graduation from "production-grade alpha" to
something I'm comfortable recommending people install on their own
machines without hand-holding. The 0.2.0 alpha shipped the bones of the
product; this beta lands the install-to-first-success polish, the
retrieval performance work, and the actually-clean uninstall that the
alpha promised but didn't quite deliver.

### Highlights

- **Tri-color install palette + Miniton loading animation.** The init
  flow now uses orange / yellow / red / purple as a self-contained
  signal vocabulary — orange for forward motion, yellow for warnings,
  red for hard failure, purple for the affirmative "fits" RAM chip. The
  REPL's gap between `Enter` and the first streamed token now fills
  with a `searching palace…` spinner during retrieval and a Rich dots
  `thinking…` spinner during time-to-first-token, animated on a daemon
  thread so the UI keeps ticking while `model.generate()` blocks.
- **First-run onboarding rewrite.** `install.sh` gets ANSI colour, a
  `--dry-run` preflight, and existing-install detection. `superton
  init` shows that `^C` is safe, offers a 3-drawer demo seed, and
  surfaces an "your palace is empty" hint instead of running an empty
  retrieval. First REPL invocation shows a 2-line quick-start panel.
- **Retrieval + model perf.** New `source_terms` table indexes path
  tokens so `source_matches` and `_hoist_source_matches` hit an indexed
  lookup instead of scanning + tokenising every distinct source per
  call. `Model._tags` and `backend()` are cached with a 4-second TTL so
  the daemon isn't hammered on every chat turn. Schema migration is
  one-shot via `PRAGMA user_version`.
- **New daily-workflow commands.** `superton note "..."` for quick
  capture, `superton recent` / `superton today` for what landed in the
  last week / day, and `superton sources --health` to spot missing
  files or stuck semantic-index entries.
- **Diagnostics + uninstall.** `superton doctor --json` for
  machine-readable output. `superton errors.hint_for` distinguishes
  "Ollama not installed" from "installed but daemon down". `superton
  uninstall` now uses `subprocess.run` instead of `os.execvp` and
  defensively sweeps `~/.local/share/uv/tools/superton` plus the bin
  shim, so a follow-up `find ~ -iname '*superton*'` is genuinely
  clean.
- **TUI polish.** The footer now shows theme · model · drawer count so
  the active state is visible at a glance.

### Pill contrast fix (visible during init)

The selected model-profile card (`● proton` by default) used to render
as white-on-yellow — unreadable on most terminals. Unselected pills
(`○ photon`, `○ neutron`) were dim white-on-grey50. `pill()` now uses
the same dark-text-on-accent pattern for primary / secondary that
success / warning / info already used, and the neutral pill background
moves from `muted` (grey50) to `rule` (grey30) for sharper contrast.

### New commands

- `superton note <text> [--tag]` — quick text drawer without a file
- `superton recent [--days N]` / `superton today` — sources by recency
- `superton sources --health` — index + path-existence health
- `superton demo` — seed a 3-drawer demo palace
- `superton doctor --json` — machine-readable diagnostics

### Tests

218 tests pass under `pytest --ignore=tests/test_tui.py`. New coverage
for the orphan-sweep paths in `uninstall`, the `source_terms` backfill
gate, the cached-tags model behaviour, the empty-palace `ask` short
circuit, the `today` command, and the install-flow purple chip.

### Migration

- `pyproject.toml` version bumped `0.2.0` → `0.3.0b1`; classifier
  flipped from `Development Status :: 3 - Alpha` to
  `Development Status :: 4 - Beta`.
- Existing palaces upgrade in place — the new `source_terms` table is
  created lazily and back-filled once per palace via a `PRAGMA
  user_version` gate.
- `INSTALL_GREEN` is still exported but now aliases `INSTALL_PURPLE`
  instead of `INSTALL_ORANGE`; legacy callers keep working.

## [0.2.0] — 2026-05-22

The "production-grade alpha" release. SuperTon goes from a thoughtful
prototype to something I'm comfortable shipping to friends: structured
logging, typed errors with one-line recovery hints, mypy-strict on the
core modules, a 218-test suite, a full Textual TUI as opt-in, Qwen 3.5
as the default model, a deliberate staged install flow, and a complete
uninstall that actually unlinks the binary.

### Highlights

- **Qwen 3.5 default model**, with three particle-named profiles —
  `photon` (0.8B), `proton` (4B, default), `neutron` (9B). The
  Modelfile pins `num_ctx 16384` and a low temperature so answers stay
  terse and citation-friendly. Legacy `fast`/`better`/`strong` profile
  names migrate automatically with a logged warning.
- **Full-screen Textual TUI** — `superton tui` ships under the
  optional `[tui]` extra. Three-pane layout (header pills · sidebar ·
  scrollable chat), command palette on `Ctrl+K`, help modal on `?`,
  themes propagate live without restart. Same `superton.chat`
  orchestration as the classic shell so retrieval + refusal logic
  stay in lockstep.
- **Deliberate install flow** — `superton init` opens with a rounded
  "about to do" card listing every stage with `✓`/`→`/`?` icons.
  Stage headers carry `[N/total]` progress. New per-profile cards
  with marker pills, base-model tag, download-size chip, and a visual
  RAM-fit bar. Closing "ready" panel is a hero moment with status
  pills + two columns of next-step commands.
- **Complete uninstall** — `superton uninstall` removes the palace,
  the Ollama tags, **and** the CLI binary itself by default. The
  binary-removal step uses `os.execvp` so the installer (uv / pipx /
  pip) can safely unlink the binary that was holding the process's
  PID — previously left a stale `~/.local/bin/superton` shim.
- **Production hardening** — structured `superton.logging`
  (`SUPERTON_LOG=debug|info|warn|error|off`, JSON via
  `SUPERTON_LOG_JSON=1`, file output via `SUPERTON_LOG_FILE`),
  `superton.errors` mapping known exceptions to one-line recovery
  hints, mypy-strict on `memory`/`model`/`config`/`chat`/`errors`/
  `logging`/`ingest`. CI on Linux + macOS × Python 3.11 + 3.12 with
  a 45% coverage floor.

### Added

- `superton/chat.py` — pure chat orchestration extracted from
  `shell._answer`. Shell and TUI both call `chat.plan_answer()` /
  `chat.stream_answer()` / `chat.answer()` so retrieval, refusal,
  and prompt building stay in lockstep.
- `superton/logging.py` — env-driven structured logger
  (`SUPERTON_LOG`, `SUPERTON_LOG_JSON`, `SUPERTON_LOG_FILE`).
- `superton/errors.py` — typed exceptions
  (`SupertonError`, `ConfigError`, `IngestError`, `ImportError_`)
  plus `hint_for()` and `errors.render()` so every failure ends
  with a "try this next" line.
- `superton/tui/` — full Textual app:
  - `app.py` `SupertonApp` with worker-driven streaming
  - `state.py` `AppState` with bounded chat history
  - `theme.py` live bridge from `ui.Theme` → `.tcss`
  - `widgets/`: header, sidebar, chat, input, palette, help,
    drawer view
- `superton/Modelfile` parameters: `num_ctx 16384`,
  `PARAMETER stop "<|im_end|>"`. (`PARAMETER think false` was added
  then removed in favour of an explicit SYSTEM-prompt instruction.)
- New CLI commands:
  - `superton tui` — launch the full-screen TUI
  - `superton uninstall` — proper full cleanup (palace + models + binary)
  - `superton welcome` — replay the ready card any time
- New UI primitives in `superton.ui`:
  - `card(title, body, *, status=...)` — rounded tool-result panels
  - `pill(label, kind=...)` + `status_pills(cfg, stats)` — pill chips
  - `preflight_card(title, rows)` — staged-flow plan view
  - `ready_card(cfg, stats)` — hero finale used by init + welcome
  - `profile_card(...)` + `ram_bar(used, recommended)` — profile picker
  - `theme_picker_card(active)` — full theme grid with swatches
  - `diff_summary(removed, added)` — red/green diff render for refresh
  - `shimmer(label)` — brief pulse for empty-state messages
  - `numbered_chip(n, id, source)` — pill-style citation footer
  - `maybe_pager(text)` — auto-paginate long answers
  - `farewell_card(removed, manual_step)` — closes uninstall
  - `pt_bg()` and `pt_raw_color()` — prompt_toolkit theme helpers
- `install.sh` — curl-friendly installer that bundles the `[tui]`
  extra by default (`SUPERTON_NO_TUI=1` opts out).
- `docs/TUI_ARCHITECTURE.md` — design doc for the TUI, including the
  four-version roadmap toward becoming the default interactive mode.
- `docs/UX_ROADMAP.md` — living plan for Now / Soon / Later /
  Speculative UX work.

### Changed

- **Default model**: `qwen2.5:1.5b-instruct` → `qwen3.5:4b`.
- **Default profile**: `fast` → `proton`.
- **`Memory.add()`** now exposes `Memory.last_insert_was_new`
  alongside the returned Drawer so ingest callers can count dedup
  hits without a second query.
- **`ui.spinner()`** now accepts `phases=[...]` and rotates through
  the verbs every ~850 ms via a daemon thread. Yields a
  `set_status(label)` callable for mid-stream updates.
- **`ui.section()`** sweeps the prefix glyph muted → secondary →
  primary on TTYs for a deliberate visual beat per section.
- **`ui.stream_answer()`** retires the `▎` cursor by fading it to
  muted → rule → erased over ~150 ms so answers don't end on a
  hard cut.
- **`ui.citations()`** renders pill-style chips with background
  tinting instead of plain bracketed numbers.
- **Install palette**: bicolor **orange + red** only (was
  yellow + green + orange + red).
  - Orange `#FFB02E` for progress / positive (`→`, `✓`, fits, headers).
  - Red `#F0471F` for negative (`!`, `✗`, tight RAM).
- **Slash-command completer** now uses an explicit
  `bg:<theme.primary> fg:#0a0a0a bold` selection style — the old
  `reverse <fg>` pattern was near-invisible on dark terminals.
- **`superton uninstall`** defaults flipped: `--tool` is now **True**
  by default, so a vanilla `superton uninstall` removes the binary.
  Pass `--keep-tool` to opt out.
- **CI**: Linux + macOS matrix × Python 3.11 + 3.12, plus a
  dedicated `typecheck` job. Coverage floor at 45%.

### Fixed

- `_detect_preflight` no longer instantiates `Model(cfg)` — preflight
  is now network-free. The old code triggered slow connect-refused
  stalls on macOS CI runners where the `ollama` binary was on PATH
  but the daemon wasn't running.
- `superton uninstall` no longer leaves a stale
  `~/.local/bin/superton` shim. The new flow uses `os.execvp` so
  the installer's uninstall command replaces the running process and
  can unlink the binary safely.
- `install.sh` now pulls the `[tui]` extra by default so
  `superton tui` works after a fresh install — previously errored
  with "textual is not installed".
- `superton tui` error path detects uv / pipx / pip installs and
  prints the matching recovery command, plus an `install.sh` rerun
  hint.
- Config validation: `model_backend`, `memory_backend`, and `theme`
  invalid values now fall back to sane defaults with a logged warning
  instead of silently propagating.
- Bare `except Exception` boundaries replaced with specific types
  across `memory`, `model`, `ingest`, `cli`, `shell`, `config`.

### Breaking

- **Default model swap** (Qwen 2.5 → Qwen 3.5) means existing users
  must re-pull weights on next `superton init`. Disk savings on the
  small tier (`photon`: 1.5B → 0.8B) more than make up for it.
- **Profile rename** `fast`/`better`/`strong` → `photon`/`proton`/
  `neutron`. Legacy names auto-migrate with a logged warning.
- **`Memory.add()`** return type contract: still returns `Drawer`,
  but `last_insert_was_new` is the source of truth for "was this a
  new insert" (previously could be inferred from re-querying).
- **`superton uninstall`** default behaviour is more aggressive
  (removes the CLI binary). Pass `--keep-tool` to preserve the
  pre-0.2.0 behaviour.

### Migration

- **From 0.1.x:** Run `superton init --yes` after upgrading to pull
  Qwen 3.5 and rebuild Miniton. Your palace data is preserved.
  Config profile names auto-migrate. No manual edit required.

### Stats

- Tests: 34 → **218 passing**, 1 skipped.
- Coverage: ~10% → **50.6%**.
- Type-checked modules: 0 → **6** (mypy-strict).
- LOC: ~5.5k → ~9.5k (about half is new tests + docs).
- Commits since 0.1.x: ~25 logical changes across 6 merged PRs.

---

## [0.1.x] — earlier alphas

Initial CLI, palace, ingest, ask, lexical search, Claude Code import,
multi-turn REPL, MemPalace semantic sidecar, native Python web puller,
four-theme system. See `git log v0.1.0..v0.2.0` for the detailed
history.

[0.2.0]: https://github.com/therahul-yo/Superton/compare/v0.1.0...v0.2.0
[0.1.x]: https://github.com/therahul-yo/Superton/releases/tag/v0.1.0
