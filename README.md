![SuperTon black hole hero](docs/assets/superton-hero.png)

# SuperTon

> A tiny local LLM with infinite memory. Your second brain that never forgets.

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
- 🔌 **MCP-ready** — one command exposes your palace to Claude Code, Cursor, and Gemini CLI
- 🪶 **Lightweight** — runs comfortably on a laptop

## Install

### From GitHub

```bash
# requires Python 3.10+ and uv
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
superton model better
superton theme solar
superton welcome                 # anytime tour of what's installed

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
| `superton model [fast\|better\|strong]` | Show or switch Miniton model profile |
| `superton theme [nebula\|mono\|solar\|frost]` | Show or switch the CLI theme |
| `superton dedup [--dry-run \| --apply]` | Find near-duplicate drawers (via MemPalace dedup) |
| `superton mcp serve` | Run the MemPalace MCP server against the SuperTon palace |
| `superton close` | Stop running SuperTon model runners |
| `superton import claude-code` | Import Claude Code session history |
| `superton import chatgpt <export>` | Import ChatGPT `conversations.json` exports |
| `superton import cursor` | Import readable Cursor thread/log files |
| `superton import amp` | Import readable Amp thread/log files |
| `superton tune` | Edit the Modelfile and rebuild Miniton |
| `superton` | Launch the interactive CLI shell |

## Architecture

```
┌─────────────────────────────────────────────┐
│   superton CLI (typer + rich + themes)      │
├─────────────────────────────────────────────┤
│   Miniton (Ollama + Modelfile)              │
├─────────────────────────────────────────────┤
│   memory: SQLite + MemPalace semantic       │
│           + source-filename hoist re-rank   │
├─────────────────────────────────────────────┤
│   ingest: parsers + chunkers + importers    │
├─────────────────────────────────────────────┤
│   mcp: MemPalace MCP server (29 tools)      │
└─────────────────────────────────────────────┘
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

## Why?

ChatGPT forgets. Notion makes you file. Obsidian plugins call cloud APIs.
None of them give you a model that's *yours*, fed by a memory that's *yours*,
running on a machine that's *yours*. SuperTon does.

## Model Strategy

`Miniton` is SuperTon's local answer model. The default public/runtime tag is
`miniton`; by default it is built from `qwen2.5:1.5b-instruct` via Ollama.
You can override the base with `SUPERTON_BASE_MODEL`. Exact recall comes from
the palace drawers, not from model weights.

Model profiles:

| Profile | Ollama base | Use case |
|---|---|---|
| `fast` | `qwen2.5:1.5b-instruct` | lowest memory, quickest startup |
| `better` | `qwen2.5:3b-instruct` | stronger answers on laptops |
| `strong` | `qwen2.5:7b-instruct` | best local quality, heavier |

Switch profile:

```bash
superton model better
superton init --yes
```

If Ollama is not available, SuperTon can use Hugging Face Inference as a fallback:

```bash
export SUPERTON_MODEL_BACKEND=huggingface
export HF_TOKEN=...
superton ask "what did I decide about the auth refactor?"
```

## Release Check

```bash
uv sync --extra dev
uv run pytest
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
- **Phase 2** *(current)* — `timeline` / `entities` via MemPalace knowledge
  graph, batched ingest via `mempalace.miner`, OCR fallback for image PDFs,
  file watcher, `export` / `import-palace` / `sync`
- **Phase 3** — Gemini importer, browser extension, JSON output mode,
  packaging polish
- **Phase 4** — `evolve` (LoRA fine-tune from your drawers), web UI

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Built on the shoulders of [Ollama](https://ollama.com),
[MemPalace](https://github.com/MemPalace/mempalace),
[Typer](https://typer.tiangolo.com), and [Rich](https://rich.readthedocs.io).
