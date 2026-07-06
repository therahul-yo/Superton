<p align="center">
  <img src="docs/assets/superton-hero.png" alt="SuperTon black hole hero" width="720">
</p>

<h1 align="center">SuperTon</h1>

<p align="center">
  <b>A local memory palace for your scattered notes, docs, and AI chats.</b><br>
  Searchable, grounded, citations — and 100% yours.
</p>

<p align="center">
  <a href="https://github.com/therahul-yo/Superton/actions/workflows/ci.yml"><img src="https://github.com/therahul-yo/Superton/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
  <img src="https://img.shields.io/badge/status-beta-blue" alt="Status">
  <img src="https://img.shields.io/badge/tests-231%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/macOS-first-black?logo=apple&logoColor=white" alt="macOS-first">
</p>

<!-- Demo GIF lands here once recorded. See `docs/RECORDING.md` for the script + ffmpeg pipeline.
<p align="center">
  <img src="docs/assets/demo.gif" alt="SuperTon — install to first cited answer in 60 seconds" width="720">
</p>
-->

```bash
curl -fsSL https://raw.githubusercontent.com/therahul-yo/Superton/main/install.sh | sh
superton init                    # set up palace + Superton (~2 min, one-time)
superton add ~/Documents/notes   # ingest a folder
superton                         # start chatting with cited answers
```

**SuperTon** ingests your PDFs, notes, code, and AI-tool transcripts into a single
local knowledge base. A tiny custom local model (`Superton`) answers your questions
grounded in *your* data — with citations. No cloud. No API keys. No telemetry.

- 🧠 **Verbatim storage** — original text preserved; never summarized away
- 🔒 **Local-first** — SQLite + Ollama on your machine; works offline
- 📎 **Cited answers** — every reply footers with the drawers it pulled from
- 🔗 **Multi-source ingest** — PDFs, markdown, code, Claude Code / ChatGPT / Cursor / Amp transcripts
- 🔌 **MCP-ready** — expose your palace to Claude Code, Cursor, or Gemini CLI with one command

## Performance

Measured on Apple M4 MacBook Air (16 GB) with 2 000 synthetic drawers. Re-run via
[`scripts/bench.py`](scripts/bench.py):

| metric | value |
|---|---|
| CLI cold start (`superton --version`) | **~87 ms** |
| Ingest throughput | **~11 500 drawers/sec** |
| Retrieval latency p50 / p95 | **0.99 ms / 1.10 ms** |
| Storage per drawer | **~840 bytes** (SQLite + FTS) |
| Test suite | **231 passing**, mypy-strict core |

First-token latency from Superton itself depends on your Ollama setup and base
model — typically ~2 s on M4 MacBook Air with `openbmb/minicpm5`. Streaming starts as soon as the
first token is decoded.

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
  matching tokens in any retrieved drawer, Superton refuses rather than
  generating a plausible-but-wrong answer from the model's parametric
  memory. The user gets a "did you mean…" with the closest source files
  instead.
- **Themes as a UX commitment, not a skin.** Five hand-tuned palettes
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
  and a 231-test suite at ~50 % coverage gating CI on Linux + macOS ×
  Python 3.11 + 3.12.

## Tech stack

Python 3.11+, [Typer](https://typer.tiangolo.com) (CLI),
[Rich](https://rich.readthedocs.io) (output),
[prompt-toolkit](https://python-prompt-toolkit.readthedocs.io)
(interactive shell), SQLite + FTS5 (durable store),
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
curl -LsSf https://raw.githubusercontent.com/therahul-yo/Superton/main/install.sh | sh
superton init
```

The installer requires Python 3.11+. It installs `uv` if needed, then installs
SuperTon from GitHub as a uv tool.

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
custom `Superton` from the `Modelfile`, and — if it finds Claude Code sessions
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

# ask it — Superton streams tokens live and cites the drawers it used
superton ask "what did i decide about graphql last spring?"
superton ask "open issues in the auth refactor" --why

# explore
superton list
superton search "how did we handle request throttling?"
superton timeline                # what entered the palace, day by day
superton digest                  # generated brief: worked on / decided / open
superton sources
superton stats
superton doctor
superton reindex

# show model / switch theme / palette
superton model
superton theme crimson
superton welcome                 # anytime tour of what's installed

# power tools
superton mcp serve               # expose the palace to Claude / Cursor / Gemini
superton dedup --dry-run         # find near-duplicate drawers
superton export -o palace.jsonl  # back up every drawer (JSON Lines)
superton import-palace palace.jsonl   # restore on any machine
superton search "throttling" --json | jq .   # script-friendly output
superton close                   # stop local model runners

# or launch the interactive shell — type /stop to unload Superton, /quit to stop + exit
superton
```

Inside the interactive shell, paste a file path directly to ingest it. Superton
streams its reply with an inline cursor, renders the result as markdown, and
appends a `sources` footer listing every drawer it used:

```text
› /Users/you/Downloads/resume.pdf
✓ ingested 4 drawers from 1 file(s)
› gimme my projects from the resume

Superton
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
palette, and `/model` shows Superton's model configuration with a brief
confirmation flash. `/list` and `/recent` show what's in the palace, `/note
<text>` captures a quick thought, and `/why` toggles a retrieval trace under
every answer. Tab-completion covers slash commands, theme names, and file
paths after `/add` / `/refresh` — and a mistyped command gets a
"did you mean /search?" nudge instead of being sent to the model.

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
| `superton ask "..."` | Query Superton with palace context (streaming + citations) |
| `superton list` | Show recent drawers (`--json` for scripts) |
| `superton timeline [--days N]` | Day-by-day view of what entered the palace |
| `superton digest [--days N]` | Generated brief: worked on · decided · open threads |
| `superton search "..."` | Hybrid search via MemPalace with SQLite fallback |
| `superton open <id>` | Show the full drawer behind a citation (`--edit` opens the source) |
| `superton recall [--older-than N]` | Resurface random drawers — memory you forgot you had |
| `superton forget <id>` | Remove a drawer |
| `superton forget-source <path-or-name>` | Remove all drawers from one source |
| `superton refresh <path>` | Reingest a source and remove stale chunks |
| `superton sources` | List indexed source files |
| `superton stats` | Palace statistics (`--json` for scripts) |
| `superton doctor` | Check local runtime, memory, theme, and model setup |
| `superton reindex` | Rebuild semantic index from stored drawers |
| `superton model` | Show the Superton model configuration |
| `superton theme [ember\|crimson\|void\|ash\|aurora]` | Show or switch the CLI theme |
| `superton export [-o file]` | Back up every drawer as JSON Lines |
| `superton import-palace <file>` | Restore drawers from a `superton export` file |
| `superton dedup [--dry-run \| --apply]` | Find near-duplicate drawers (via MemPalace dedup) |
| `superton mcp serve` | Run the MemPalace MCP server against the SuperTon palace |
| `superton close` | Stop running SuperTon model runners |
| `/stop` or `/quit` in the shell | Stop Superton; `/quit` also exits |
| `superton uninstall --yes --tool` | Remove local SuperTon data, Ollama models, and CLI install |
| `superton import claude-code` | Import Claude Code session history |
| `superton import chatgpt <export>` | Import ChatGPT `conversations.json` exports |
| `superton import cursor` | Import readable Cursor thread/log files |
| `superton import amp` | Import readable Amp thread/log files |
| `superton tune` | Edit the Modelfile and rebuild Superton |
| `superton` | Launch the interactive CLI shell |

## Uninstall

For a full local cleanup, run:

```bash
superton uninstall --yes --tool
```

This removes:

- SuperTon palace data and config from the user data directory
- the `superton` Ollama model
- the configured base model, `openbmb/minicpm5`
- a legacy `nomic-embed-text` Ollama model, if a previous version pulled one
- the cached semantic embedding model and ChromaDB caches
- the installed `superton` CLI tool when it was installed through uv, pipx, or pip

Use `--keep-data` to keep the palace, `--keep-models` to skip all Ollama model
removal, or `--keep-base-models` to remove only `superton` while preserving the
base models.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  surfaces:  CLI · prompt_toolkit shell          │
├─────────────────────────────────────────────────┤
│  chat: plan_answer / stream_answer / refusal    │
├─────────────────────────────────────────────────┤
│  ui: themes (4) · spinner · cards · pills       │
│  errors: typed exceptions + recovery hints      │
│  logging: env-driven structured logs            │
├─────────────────────────────────────────────────┤
│  Superton (Ollama + Modelfile · HF fallback)     │
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

SuperTon ships with five hand-tuned CLI themes:

| Theme | Vibe |
|---|---|
| `ember` | burnt orange on black · default, embers-on-black identity |
| `crimson` | blood red on black · dark and sharp |
| `void` | dark violet · deep-space palette |
| `ash` | white on black · stark monochrome |
| `aurora` | teal on black · northern lights |

Each theme carries its own design language, not just colors: a unique
prompt glyph (`◉ ✦ ◈ › ❖`), spinner style, and rule character — `ember`
draws solid gradient rules, `crimson` dotted, `void` dashed. Section
headers sweep muted → primary as they appear, install stages tick in
with a 3-frame pulse, and the stage tracker shows `●●○○○` progress dots.
During `superton init` the theme picker is fully interactive: ↑/↓ to
move with a live color preview, Enter to select.

Switch any time:

```bash
superton theme                 # show all with color swatches
superton theme void            # switch; a 200 ms flash confirms the change
export SUPERTON_THEME=ash      # env override (useful in CI / screenshots)
```

All semantic output (paths, drawer ids, commands, key bindings) is styled
consistently per theme so switching looks intentional, not skinned.

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

`Superton` is SuperTon's local answer model. The default public/runtime tag is
`superton`; by default it is built from `openbmb/minicpm5` via Ollama. You can
override the base with `SUPERTON_BASE_MODEL`. Exact recall comes from the
palace drawers, not from model weights — the model only has to phrase the
answer.

### Base model

SuperTon ships with a single default base model:

| Ollama base | Params | Download | Context | Notes |
|---|---|---|---|---|
| `openbmb/minicpm5` | 1B | ~0.7 GB | 128K | small, fast, runs on any laptop |

The Modelfile wraps it with SuperTon's SYSTEM prompt and pins
`num_ctx 16384` and a low temperature so answers stay terse and
citation-friendly. Override the base with `SUPERTON_BASE_MODEL`
(e.g. `openbmb/minicpm5:q8_0` or `openbmb/minicpm5:fp16`).

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
SUPERTON_LOG_FILE=~/superton.log superton
```

Every known failure renders with a one-line recovery hint — start
Ollama, check `HF_TOKEN`, run `superton reindex`, etc. — instead of a
bare traceback. `superton doctor` masks `HF_TOKEN` to its first/last
four characters so the report is shareable.

### Environment variables

| variable | purpose | default |
|---|---|---|
| `SUPERTON_HOME` | override palace location | platform-specific |
| `SUPERTON_THEME` | `ember \| crimson \| void \| ash \| aurora` | `ember` |
| `SUPERTON_MODEL_BACKEND` | `auto \| ollama \| huggingface` | `auto` |
| `SUPERTON_MEMORY_BACKEND` | `hybrid \| semantic \| mempalace \| sqlite` | `hybrid` |
| `SUPERTON_BASE_MODEL` | override the Ollama base tag | `openbmb/minicpm5` |
| `SUPERTON_HF_MODEL` | override the Hugging Face fallback | `openbmb/MiniCPM5-1B` |
| `OLLAMA_HOST` | Ollama daemon URL | `http://127.0.0.1:11434` |
| `HF_TOKEN` | enables Hugging Face fallback | — |
| `SUPERTON_LOG` | `debug \| info \| warn \| error \| off` | `warn` |
| `NO_COLOR` / `SUPERTON_NO_COLOR` | disable ANSI color entirely | — |
| `SUPERTON_LOG_JSON` | one JSON record per line on stderr | off |
| `SUPERTON_LOG_FILE` | tee structured logs to a file | — |

Invalid values for the theme / model / memory backends fall back to
sane defaults and log a warning rather than crashing.

## Release Check

```bash
uv sync --extra dev
uv run pytest                       # 231 tests, ~50% coverage
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
  with recovery hints, mypy-strict core, 231-test suite, Linux+macOS CI,
  UI polish pass (verb-cycling spinners, cards, pills, diff refresh) ✅
- **Phase 2** *(current)* — `export` / `import-palace` ✅, JSON output
  mode ✅, `timeline` / `entities` via MemPalace knowledge graph, batched
  ingest via `mempalace.miner`, OCR fallback for image PDFs, file watcher,
  `sync`
- **Phase 3** — Gemini importer, browser extension, packaging polish
- **Phase 4** — `evolve` (LoRA fine-tune from your drawers), web UI

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Built on the shoulders of [Ollama](https://ollama.com),
[MemPalace](https://github.com/MemPalace/mempalace),
[Typer](https://typer.tiangolo.com), and [Rich](https://rich.readthedocs.io).

Development assistance from Claude Code and OpenAI Codex.
