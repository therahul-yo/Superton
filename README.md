![SuperTon black hole hero](docs/assets/superton-hero.png)

# SuperTon

> A local memory palace for your scattered notes, docs, and AI chats — searchable, grounded, and 100% yours.

[![CI](https://github.com/therahul-yo/Superton/actions/workflows/ci.yml/badge.svg)](https://github.com/therahul-yo/Superton/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

SuperTon is a CLI-first personal knowledge system. Feed it your notes, docs,
PDFs, and conversations from other AI tools. It indexes everything verbatim
into a **palace of memories**, then your tiny custom local model (`Miniton`)
answers your questions grounded in what you've fed it.

- 🕳 **Black hole memory** — drawers go in, nothing comes out warped, nothing is forgotten
- 🧠 **Tiny local model** — Miniton, customizable via `Modelfile`
- 🔒 **100% local** — no API keys, no cloud, no telemetry
- 📚 **Verbatim storage** — original text preserved; nothing summarized away
- 🔗 **Multi-source** — import from Claude Code, ChatGPT, Cursor, Amp
- 🎨 **Four themes** — nebula, mono, solar, frost — production-feel CLI
- 🖥 **Full-screen TUI** — opt-in Textual app with palette, sidebar, modals (`superton tui`)
- 🔌 **MCP-ready** — one command exposes your palace to Claude Code, Cursor, and Gemini CLI
- 🛠 **Production-grade** — structured logging, typed errors with recovery hints, mypy-strict core, 187 tests
- 🪶 **Lightweight** — runs comfortably on a laptop

## Demo

> 🎬 **Demo video — recording soon.**
>
> A short clip showing ingestion → grounded answer with citations → theme
> switch will live at [`docs/assets/demo.gif`](docs/assets/demo.gif).
> Until then, the snippet in [Quickstart](#quickstart) shows a real
> session.

<!-- After recording, replace the block above with:
![SuperTon demo](docs/assets/demo.gif)
-->

## Why I built this

I was tired of my brain leaking. Notes scattered across Notion, Obsidian,
random `.md` files, screenshots, and Claude Code transcripts. Every AI
tool I used forgot the conversation the moment I closed the tab. Every
"second brain" app wanted me to file things — but the work of filing is
the work I was trying to avoid.

I wanted one place that:

1. **Eats everything I feed it** — PDFs, code, notes, AI transcripts —
   without making me file or summarize.
2. **Answers in my voice, from my data** — grounded in what *I* wrote,
   not in what a frontier model hallucinated about my domain.
3. **Stays on my laptop** — no API keys, no telemetry, no "your data
   helps us improve our service".

SuperTon is what I built. It's a CLI-first system because I live in the
terminal, a hybrid retrieval pipeline because pure-vector search misses
the times I half-remember a filename, and a Modelfile-driven local model
because I wanted the answer model to be *mine* — swappable, tuneable,
and free to forget the cloud existed.

Along the way I picked up a working theory of personal RAG: **verbatim
beats summarized**, **hybrid beats pure-vector**, and **source-filename
hints beat clever prompting** when the user is searching for something
they half-remember writing. The rest of this README is the receipts.

## Design decisions

The interesting choices, with the tradeoffs called out:

- **Verbatim storage, not summarized.** Drawers store the original text.
  Recall matters more than disk in a personal palace; a 50 MB SQLite file
  per year is fine. Summarization would have made the model fast at
  losing information.
- **SQLite as source of truth, MemPalace/Chroma as a sidecar.** SQLite
  owns listing, deletion, and exact fallback search. The vector index can
  be wiped and rebuilt from SQLite (`superton reindex`) without data
  loss. Durability > performance.
- **Hybrid retrieval with source-filename hoist.** Pure vector search
  misses queries like *"my resume"* — Claude Code transcripts of
  `ls -la` embed closer to the query than the actual `resume.pdf`. The
  retriever hoists drawers whose filename overlaps the query, then merges
  with the hybrid v4 (`candidate_strategy="union"`, BM25 ∪ vector) result
  from MemPalace. Raw R@5 is 96.6% on LongMemEval; tuned hybrid is 98.4%.
- **Insert-time dedup.** Drawer ids are content-addressed
  (`blake2b(source ⊕ text)`). Re-ingesting the same file is a no-op —
  the semantic upsert is skipped on a hit, so re-runs are cheap.
- **Refuse instead of confabulate.** For memory-specific queries with no
  matching tokens in any retrieved drawer, Miniton refuses rather than
  generating a plausible-but-wrong answer from the model's parametric
  memory. The user gets a "did you mean…" with the closest source files
  instead.
- **Themes as a UX commitment, not a skin.** Four hand-tuned palettes
  share an icon and styling vocabulary (✓ ! ✗ ℹ → ›). Paths, drawer ids,
  commands, and keyboard hints route through `ui.style_*` helpers so
  switching themes looks intentional, not skinned.
- **MCP-first integration.** `superton mcp serve` exposes the palace as
  29 MCP tools to Claude Code, Cursor, and Gemini CLI — the palace
  becomes the shared memory layer for every agent on the machine,
  instead of yet another tool with its own silo.
- **Production hardening over alpha polish.** Structured logging
  (`SUPERTON_LOG=debug|info|warn|error|off`, optional JSON via
  `SUPERTON_LOG_JSON=1`), typed errors that map known exceptions to
  one-line recovery hints, mypy-strict on the core modules
  (`memory`, `model`, `config`, `chat`, `errors`, `logging`, `ingest`),
  and a 187-test suite at ~50 % coverage gating CI on Linux + macOS ×
  Python 3.11 + 3.12.

## Tech stack

Python 3.11+, [Typer](https://typer.tiangolo.com) (CLI),
[Rich](https://rich.readthedocs.io) (output),
[prompt-toolkit](https://python-prompt-toolkit.readthedocs.io)
(interactive shell), [Textual](https://textual.textualize.io) (opt-in
TUI), SQLite + FTS5 (durable store),
[MemPalace](https://github.com/MemPalace/mempalace) + ChromaDB (semantic
sidecar + MCP), [Ollama](https://ollama.com) (local model runtime),
optional Hugging Face Inference fallback. Packaging with
[uv](https://docs.astral.sh/uv/) and `hatchling`. Lint with
[ruff](https://docs.astral.sh/ruff/), tests with
[pytest](https://docs.pytest.org), type-check with
[mypy](https://mypy.readthedocs.io).

## Install

### From GitHub

```bash
# requires Python 3.11+ and uv
uv tool install "git+https://github.com/therahul-yo/Superton.git"
superton init
```

### From A Local Checkout

```bash
git clone https://github.com/therahul-yo/Superton.git
cd Superton
uv tool install . --force
superton init
```

### From PyPI

```bash
uv tool install superton
superton init
```

The PyPI command works after the package is published. Until then, use the
GitHub install command.

`superton init` runs as a staged flow: it creates the palace, starts Ollama
when possible, asks before downloading missing model weights, builds your
custom `Miniton` from the `Modelfile`, and — if it finds Claude Code sessions
at `~/.claude/projects` — offers to import them right away. Use
`superton init --yes` for non-interactive setup. The palace lives at
`~/Library/Application Support/superton/palace`.

Ollama is the default local backend. If a user does not have Ollama, they can use
Hugging Face Inference instead:

```bash
export SUPERTON_MODEL_BACKEND=huggingface
export HF_TOKEN=...
superton ask "hello"
```

## Quickstart

```bash
# feed it
superton add ~/notes
superton add ~/research/paper.pdf --wing research --room nlp
superton import claude-code
superton import chatgpt ~/Downloads/chatgpt-export
superton import cursor
superton import amp

# ask it — Miniton streams tokens live and cites the drawers it used
superton ask "what did i decide about graphql last spring?"
superton ask "open issues in the auth refactor" --why

# explore
superton list
superton search "how did we handle request throttling?"
superton sources
superton stats
superton doctor
superton reindex

# switch model / theme / palette
superton model neutron
superton theme solar
superton welcome                 # anytime tour of what's installed

# full-screen TUI (opt-in, becomes default in 0.4.0 — see docs/TUI_ARCHITECTURE.md)
pip install 'superton[tui]'
superton tui

# power tools
superton mcp serve               # expose the palace to Claude / Cursor / Gemini
superton dedup --dry-run         # find near-duplicate drawers
superton close                   # stop local model runners

# or launch the interactive shell — type / to see all slash commands
superton
```

Inside the interactive shell, paste a file path directly to ingest it. Miniton
streams its reply with an inline cursor, renders the result as markdown, and
appends a `sources` footer listing every drawer it used:

```text
› /Users/you/Downloads/resume.pdf
✓ ingested 4 drawers from 1 file(s)
› gimme my projects from the resume

Miniton
- Built SmithWorks — a role-based freelance marketplace using React,
  Node.js, Socket.IO, JWT, and AWS EC2. [3beb9480]
- Built TopX AI Resume Analyzer — Flask + scikit-learn NLP pipeline
  with real-time progress via Socket.IO. [67b61316]
- ...

sources
  1. 3beb9480 Resume.pdf
  2. 67b61316 Resume.pdf
```

Inside the shell, `/clear` resets the conversation, `/theme <name>` swaps the
palette, and `/model <profile>` switches Miniton's base model with a brief
confirmation flash.

## Web Puller

SuperTon includes a native web puller (inspired by
[webpull](https://github.com/Dhravya/webpull)) that can ingest any public
website directly into your palace — no external tools required.

```bash
# Single page
superton add https://paulgraham.com/great.html

# Full site crawl
superton pull https://docs.example.com --max 200 --wing docs

# SPA with JavaScript rendering (requires: pip install 'superton[web]')
superton pull https://my-spa.dev --render-js
```

Features:
- Sitemap.xml discovery + BFS crawl fallback
- Parallel fetching (configurable concurrency)
- trafilatura content extraction (articles, docs, blogs)
- Optional Playwright Chromium for JS-rendered SPAs
- Pages stream directly into your palace as searchable drawers

## Commands

| Command | Purpose |
|---|---|
| `superton init` | One-time staged setup: palace + model + optional Claude Code import |
| `superton welcome` | Show the header + palace intro + next-steps card any time |
| `superton add <path>` | Ingest a file or directory |
| `superton ask "..."` | Query Miniton with palace context (streaming + citations) |
| `superton list` | Show recent drawers |
| `superton search "..."` | Hybrid search via MemPalace with SQLite fallback |
| `superton forget <id>` | Remove a drawer |
| `superton forget-source <path-or-name>` | Remove all drawers from one source |
| `superton refresh <path>` | Reingest a source and remove stale chunks |
| `superton sources` | List indexed source files |
| `superton stats` | Palace statistics |
| `superton doctor` | Check local runtime, memory, theme, and model setup |
| `superton reindex` | Rebuild semantic index from stored drawers |
| `superton model [photon\|proton\|neutron]` | Show or switch Miniton model profile |
| `superton theme [nebula\|mono\|solar\|frost]` | Show or switch the CLI theme |
| `superton dedup [--dry-run \| --apply]` | Find near-duplicate drawers (via MemPalace dedup) |
| `superton mcp serve` | Run the MemPalace MCP server against the SuperTon palace |
| `superton close` | Stop running SuperTon model runners |
| `superton uninstall --yes --tool` | Remove local SuperTon data, Ollama models, and CLI install |
| `superton import claude-code` | Import Claude Code session history |
| `superton import chatgpt <export>` | Import ChatGPT `conversations.json` exports |
| `superton import cursor` | Import readable Cursor thread/log files |
| `superton import amp` | Import readable Amp thread/log files |
| `superton tune` | Edit the Modelfile and rebuild Miniton |
| `superton tui` | Launch the full-screen Textual TUI (requires `[tui]` extra) |
| `superton` | Launch the interactive CLI shell |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  surfaces:  CLI · prompt_toolkit shell · TUI    │
├─────────────────────────────────────────────────┤
│  chat: plan_answer / stream_answer / refusal    │
│        — shared by shell & TUI in lockstep      │
├─────────────────────────────────────────────────┤
│  ui: themes (4) · spinner · cards · pills       │
│  errors: typed exceptions + recovery hints      │
│  logging: env-driven structured logs            │
├─────────────────────────────────────────────────┤
│  Miniton (Ollama + Modelfile · HF fallback)     │
├─────────────────────────────────────────────────┤
│  memory: SQLite + MemPalace semantic            │
│          + source-filename hoist re-rank        │
├─────────────────────────────────────────────────┤
│  ingest: parsers · chunkers · importers · web   │
├─────────────────────────────────────────────────┤
│  mcp: MemPalace MCP server (29 tools)           │
└─────────────────────────────────────────────────┘
```

## Themes

SuperTon ships with four hand-tuned CLI themes:

| Theme | Vibe |
|---|---|
| `nebula` | amber + violet accents · default, ties to the black-hole identity |
| `mono` | monochrome · bold white/grey only, Claude-code-style minimalism |
| `solar` | warm amber/orange · sunrise palette |
| `frost` | cool cyan/blue · arctic palette |

Switch any time:

```bash
superton theme                 # show all with color swatches
superton theme frost           # switch; a 200 ms flash confirms the change
export SUPERTON_THEME=mono     # env override (useful in CI / screenshots)
```

All semantic output (paths, drawer ids, commands, key bindings) is styled
consistently per theme so switching looks intentional, not skinned.

## TUI mode

A full-screen Textual interface ships under the optional `[tui]` extra.
The classic prompt-toolkit shell stays default for now; the TUI becomes
the default interactive mode in 0.4.0 per the rollout in
[`docs/TUI_ARCHITECTURE.md`](docs/TUI_ARCHITECTURE.md).

```bash
pip install 'superton[tui]'    # or: uv tool install 'superton[tui]'
superton tui
```

Layout: status pills along the top (theme · model · backend · palace
size), recent-sources sidebar with fuzzy filter on the left, scrollable
chat transcript with streaming + citation chips on the right, mode
breadcrumb and key hints in the footer.

| key | action |
|---|---|
| `Ctrl+K` | command palette (fuzzy across slash commands + actions) |
| `Ctrl+B` | toggle sidebar |
| `Ctrl+L` | clear conversation |
| `?` / `F1` | help modal |
| `Esc` | close modal / return to chat |
| `↑` / `↓` (input) | history navigation |
| `/cmd args` | slash commands work the same as the classic shell |
| `Ctrl+C` | quit |

Themes propagate live: `/theme solar` repaints the running app without a
restart. Same `superton.chat` orchestration backs both the TUI and the
classic shell, so retrieval, refusal logic, and prompt construction stay
in lockstep.

## MCP: plug SuperTon into your other AI tools

A single command exposes your SuperTon palace as a stdio MCP server powered
by MemPalace:

```bash
superton mcp serve
```

Claude Code, Cursor, Gemini CLI, and any other MCP-compatible client can
connect to it and get 29 tools for reading and writing drawers, navigating
the palace, and querying the knowledge graph — all backed by your local
SuperTon store. Your second brain becomes the memory layer for every AI
tool on your machine.

## Model Strategy

`Miniton` is SuperTon's local answer model. The default public/runtime tag is
`miniton`; by default it is built from `qwen3.5:4b` via Ollama. You can
override the base with `SUPERTON_BASE_MODEL`. Exact recall comes from the
palace drawers, not from model weights — the model only has to phrase the
answer.

### Model profiles

Particle-physics names rhyme with the SuperTon / Miniton vocabulary:

| Profile | Ollama base | Params | Download | RAM | Use case |
|---|---|---|---|---|---|
| `photon` | `qwen3.5:0.8b` | 0.8B | ~1.0 GB | 4 GB | runs anywhere, ideal for old laptops |
| `proton` *(default)* | `qwen3.5:4b` | 4B | ~3.4 GB | 8 GB | balanced everyday use |
| `neutron` | `qwen3.5:9b` | 9B | ~6.6 GB | 14 GB | best local quality, wants real RAM |

All three pull Qwen 3.5 weights (released Feb 2026 — native tool calling,
256K context, instruction-tuned). The Modelfile wraps them with SuperTon's
SYSTEM prompt and pins `think false`, `num_ctx 16384`, and a low
temperature so answers stay terse and citation-friendly.

Switch profile:

```bash
superton model neutron
superton init --yes
```

Users coming from the Qwen 2.5 era keep their old config keys — `fast`,
`better`, and `strong` are transparently migrated to `photon`, `proton`,
and `neutron` on next launch with a logged warning.

If Ollama is not available, SuperTon can use Hugging Face Inference as a fallback:

```bash
export SUPERTON_MODEL_BACKEND=huggingface
export HF_TOKEN=...
superton ask "what did I decide about the auth refactor?"
```

## Observability

Default level is `warn` so day-to-day use stays quiet. Crank it up
when something feels off:

```bash
SUPERTON_LOG=info superton search "auth refactor"
SUPERTON_LOG=debug SUPERTON_LOG_JSON=1 superton ask "..." 2>logs.jsonl
SUPERTON_LOG_FILE=~/superton.log superton tui
```

Every known failure renders with a one-line recovery hint — start
Ollama, check `HF_TOKEN`, run `superton reindex`, etc. — instead of a
bare traceback. `superton doctor` masks `HF_TOKEN` to its first/last
four characters so the report is shareable.

### Environment variables

| variable | purpose | default |
|---|---|---|
| `SUPERTON_HOME` | override palace location | platform-specific |
| `SUPERTON_THEME` | `nebula \| mono \| solar \| frost` | `nebula` |
| `SUPERTON_MODEL_PROFILE` | `photon \| proton \| neutron` | `proton` |
| `SUPERTON_MODEL_BACKEND` | `auto \| ollama \| huggingface` | `auto` |
| `SUPERTON_MEMORY_BACKEND` | `hybrid \| semantic \| mempalace \| sqlite` | `hybrid` |
| `SUPERTON_BASE_MODEL` | override the Ollama base tag | profile default |
| `SUPERTON_HF_MODEL` | override the Hugging Face fallback | profile default |
| `OLLAMA_HOST` | Ollama daemon URL | `http://127.0.0.1:11434` |
| `HF_TOKEN` | enables Hugging Face fallback | — |
| `SUPERTON_LOG` | `debug \| info \| warn \| error \| off` | `warn` |
| `SUPERTON_LOG_JSON` | one JSON record per line on stderr | off |
| `SUPERTON_LOG_FILE` | tee structured logs to a file | — |

Invalid values for the theme / model / memory backends fall back to
sane defaults and log a warning rather than crashing.

## Release Check

```bash
uv sync --extra dev
uv run pytest                       # 187 tests, ~50% coverage
uv run pytest --cov=superton --cov-fail-under=45
uv run mypy superton                # strict on core modules
uv run ruff check .
uv build
uv tool install dist/superton-0.1.0-py3-none-any.whl --force
superton --version
superton doctor
```

## Roadmap

- **Phase 0** — palace, ingest, ask, lexical search, Claude Code import ✅
- **Phase 1** — semantic search via MemPalace, hybrid SQLite fallback,
  source-filename hoist re-rank, themes, streaming answers with citations,
  staged init, `mcp serve`, `dedup`, multi-turn REPL ✅
- **Phase 1.5** — production hardening: structured logging, typed errors
  with recovery hints, mypy-strict core, 187-test suite, Linux+macOS CI,
  UI polish pass (verb-cycling spinners, cards, pills, diff refresh) ✅
- **Phase 1.6** — opt-in Textual TUI (`superton tui`) sharing the same
  `superton.chat` orchestration as the classic shell ✅
- **Phase 2** *(current)* — `timeline` / `entities` via MemPalace knowledge
  graph, batched ingest via `mempalace.miner`, OCR fallback for image PDFs,
  file watcher, `export` / `import-palace` / `sync`, promote TUI to default
  interactive mode (see [`docs/TUI_ARCHITECTURE.md`](docs/TUI_ARCHITECTURE.md))
- **Phase 3** — Gemini importer, browser extension, JSON output mode,
  packaging polish
- **Phase 4** — `evolve` (LoRA fine-tune from your drawers), web UI

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Built on the shoulders of [Ollama](https://ollama.com),
[MemPalace](https://github.com/MemPalace/mempalace),
[Typer](https://typer.tiangolo.com), [Rich](https://rich.readthedocs.io),
and [Textual](https://textual.textualize.io).
