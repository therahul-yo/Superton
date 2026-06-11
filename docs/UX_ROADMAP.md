# SuperTon UX Roadmap

> A living plan for evolving SuperTon's user experience. Each entry has a
> problem, a sketch of the solution, a rough effort estimate, and an
> impact band so we can sort by where to spend time first.
>
> Layout:
> - **Now** — bugs and rough edges that block today's user. Ship first.
> - **Soon** — focused improvements that compound (better defaults, fewer surprises).
> - **Later** — bigger bets that unlock new workflows.
> - **Speculative** — interesting but untested.

## Now (ship in the next 1–2 PRs)

| Item | Problem | Sketch | Effort |
|---|---|---|---|
| **Complete uninstall** ✅ | `superton uninstall` left the `~/.local/bin/superton` shim behind. | `--tool` default flipped to True; `os.execvp` so the binary can replace itself. Preflight card + per-stage progress. | 1 PR (done) |
| **First-run sanity check** ✅ | New users run `superton init` then `superton ask "hi"` before ingesting anything → confused refusal. | Ready card is now a 2-step ladder and empty-palace asks point to `superton add ~/notes` or `superton demo`. | 1 PR (done) |
| **Better Ollama-not-running error** | `superton ask "..."` with Ollama installed but daemon not running just shows `cannot reach Ollama`. | The `errors.hint_for` mapping already exists — chain a `pgrep ollama` probe so the hint distinguishes "not installed" vs "installed but not started". | 1 hour |
| **`superton doctor` shows install method** | When users hit issues, support starts with "how did you install it?" → friction. | Add an "install method" row showing uv / pipx / pip + the active path so users can paste their doctor output and we know everything. | 30 min |
| **Slash-menu legibility** ✅ | The highlighted completion row was near-invisible on dark themes (used prompt_toolkit's flaky `reverse`). | Explicit `bg:<theme.primary> fg:#0a0a0a bold` + nested overrides. New `pt_bg`/`pt_raw_color` helpers in `ui.py`. | 1 PR (done) |
| **Install palette consolidation** ✅ | Init flow used four colors (yellow/green/orange/red) that fought with the theme. | Tri-color orange/yellow/red: progress, recoverable warning, hard failure. | 1 PR (done) |

## Soon (next month)

### Onboarding

| Item | Sketch | Effort |
|---|---|---|
| **Demo mode** ✅ | `superton demo` populates the palace with 3 stable sample drawers so new users can `ask` immediately. Offered after interactive init when the palace is empty. | 1 PR (done) |
| **Smart Ollama discovery** | Look in `/Applications/Ollama.app` (macOS), `~/snap/ollama`, `/opt/homebrew/bin/ollama` in addition to PATH. Display in doctor as "found at <path>". | 2 hours |
| **Hardware fit check** | At init, refuse `neutron` profile when RAM < 14 GB (today we warn). Allow `--force`. Prevent failed model pulls. | 2 hours |
| **First-run welcome animation** | On the very first `superton` invocation after init, show a 1-second wordmark fade + a "type / for commands" hint that auto-dismisses. | 4 hours |

### Daily workflows

| Item | Sketch | Effort |
|---|---|---|
| **Quick capture** ✅ | `superton note "thought" --tag idea` for one-line notes without files. Stores as wing=notes, room=daily/tag, source=`note:<timestamp>`. | 1 PR (done) |
| **Project-aware retrieval** | `superton ask` detects current cwd; if it's inside a git repo whose name matches a wing, bias retrieval to that wing. | 1 day |
| **`superton today` / `superton recent`** ✅ | List sources added in the last 24h / 7d, including drawer counts and latest timestamp. | 1 PR (done) |
| **`superton tag`** | Add a tag to drawers from one source. Stored in metadata; surfaces in `superton list` as colored chips. | 1 day |

### Search & discovery

| Item | Sketch | Effort |
|---|---|---|
| **Highlight matched terms** | In `superton search` results, paint matched query tokens in `primary` color inside the preview. | 4 hours |
| **`superton related <drawer-id>`** | Given a drawer, find semantically similar ones. Single mempalace search using the drawer's text as the query. | 2 hours |
| **Score bars not numbers** | Replace `0.87` with `■■■■□` colored by band. Already proposed in earlier roadmap. | 2 hours |
| **Time-since stamps** | `superton list` → `12 jan`, `3d ago`, `2h ago` instead of raw timestamps. | 3 hours |
| **Smart path truncation** | `…/projects/superton/cli.py` for long paths. Helper in `ui.py`. | 2 hours |

### REPL polish

| Item | Sketch | Effort |
|---|---|---|
| **Slash help redesign** | `/help` becomes a card grouped by category (ingest / search / config / system) with kbd-styled hints instead of a wall of text. | 4 hours |

### Errors & observability

| Item | Sketch | Effort |
|---|---|---|
| **`SUPERTON_LOG=debug` discoverability** | When init's `_finish_init` runs and any stage warned, show a dim "run `SUPERTON_LOG=info` next time for more detail" line. | 1 hour |
| **Crash report card** | On unhandled exception in the shell, print a 4-line card with: error, hint, recovery cmd, and `--debug` flag suggestion. Already partially exists via `errors.render`; standardize. | 4 hours |
| **`superton doctor --json`** ✅ | Machine-readable doctor output for bug reports, including install method and executable path without exposing secrets. | 1 PR (done) |

## Later (next quarter)

### Performance & scale

- **Background reindexing** — `superton add` returns immediately; embedding happens in a daemon thread / asyncio worker. `superton stats` shows "indexing: 423/2107 drawers".
- **Lazy semantic indexing** ✅ — Drawers now track `semantic_status` / `indexed_at`; full background workers remain follow-up work.
- **Disk compression** — Optional zstd compression for drawers older than 30 days. Saves disk for heavy users.
- **Parallel ingest** — `superton add ~/big-folder` uses asyncio + a worker pool similar to the web puller's. Currently serial; this phase added large-file guards first.

### Privacy & security

- **Encrypted palace at rest** — Optional `--encrypted` flag at init that wraps the sqlite + chroma in a sqlcipher equivalent. Password held in OS keychain.
- **Redaction layer** — `superton config redact emails phone_numbers ssn` — applies regex masks to drawers before they're sent to the model. Originals stay in storage.
- **`--show-prompt` flag** — Before each `ask`, show the full prompt that will be sent to the model. Useful for debugging and for trust.
- **Audit log** — Append-only log of what was retrieved and sent to the model. Inspectable via `superton audit`.

### Sharing & lifecycle

- **`superton export <wing>`** — Write a wing to a portable archive (zip of markdown). Easy backup, easy "send to teammate".
- **`superton import-palace <archive>`** — Restore an exported archive into the local palace.
- **`superton sync <remote>`** — Pull updated source files from a remote (S3, scp, …) and re-ingest only the changed ones.
- **Auto-update channel** — `superton update` runs `uv tool install --upgrade`. Notifies when a new release exists.

### Multi-source intelligence

- **Cross-source synthesis** — `ask --span "all my notes about graphql across last year"` explicitly tells the retriever to widen the source pool and prefer chronological synthesis over single-doc answers.
- **Source health card** ✅ — `superton sources --health` shows drawer count, semantic index status, and missing/virtual source path state.
- **Auto-refresh watcher** — `superton watch ~/Documents` runs in the background and ingests new/changed files automatically (debounced).
- **Importer plug-ins** — `superton import` becomes pluggable so third parties can write `superton-import-notion`, `superton-import-roam`, etc.

### AI quality

- **`--reason` flag for `ask`** — Swap in DeepSeek R1 distill or QwQ just for that call when the question is multi-step. Default model stays terse Qwen 3.5.
- **Self-verification step** — After Superton answers, run a tiny "does the citation actually back this claim?" check on each cited drawer. Strip claims that fail.
- **Confidence bands per answer** — `superton ask --confidence` returns a 0–1 score per claim alongside the answer.
- **Conversation summarization** — `/clear --summarize` writes the current conversation as a single drawer before resetting.

## Speculative

| Item | Why it's interesting | Risk |
|---|---|---|
| **Voice input** | `superton ask --voice` uses whisper.cpp. Great for ambient capture while walking. | Whisper.cpp install is heavy; macOS-only Q1. |
| **Browser extension** | A "save to palace" button on every page. | Maintenance burden of a JS codebase. |
| **`superton evolve`** | LoRA fine-tune Superton on the user's writing style from drawers. | Quality unpredictable on small datasets. |
| **Team palace** | Shared palace with optimistic conflict resolution. | Privacy is the brand — could undermine the local-first promise. |
| **Web UI** | Browser-based variant of the CLI. | Two frontends to keep in sync. |

## How to use this doc

- Anything in **Now** should be in the next PR.
- **Soon** items should be picked off one or two per release.
- **Later** items become Phase 3 work after the current Phase 2 roadmap items ship.
- **Speculative** items get a one-week prototype before any further investment.

When in doubt, optimize for the user's first 10 minutes — that's where most installs decide whether to keep using SuperTon.

## Open questions

1. Do we publish to PyPI under `superton` or `super-ton`? PyPI namespace check needed.
2. Do we adopt an actual versioning policy (semver) before 0.2.0?
3. Do we add a `superton config edit` that opens `$EDITOR` on the TOML config, or stick with one-off `--theme` / `--model` flags?
5. Should `superton uninstall` archive the palace as a tarball before deletion, so users have a recovery path?
