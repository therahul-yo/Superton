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
- 🔗 **Multi-source** — import from Claude Code, ChatGPT, Cursor and more
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

`superton init` will create the palace, start Ollama when possible, ask before
downloading missing model weights, and build your custom `Miniton` from the
`Modelfile`. Use `superton init --yes` for non-interactive setup. The palace lives at
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

# ask it
superton ask "what did i decide about graphql last spring?"
superton ask "open issues in the auth refactor" --why

# explore
superton list
superton search "how did we handle request throttling?"
superton stats
superton doctor
superton reindex
superton
superton close
```

Inside the interactive shell, paste a file path directly to ingest it:

```text
› /Users/you/Downloads/resume.pdf
✓ ingested 4 drawers from 1 file(s)
› gimme my projects from the resume
```

## Commands

| Command | Purpose |
|---|---|
| `superton init` | One-time setup: palace + model |
| `superton add <path>` | Ingest a file or directory |
| `superton ask "..."` | Query Miniton with palace context |
| `superton list` | Show recent drawers |
| `superton search "..."` | Semantic search across drawers with lexical fallback |
| `superton forget <id>` | Remove a drawer |
| `superton stats` | Palace statistics |
| `superton doctor` | Check local runtime, memory, and model setup |
| `superton reindex` | Rebuild semantic index from stored drawers |
| `superton close` | Stop running SuperTon model runners |
| `superton import claude-code` | Import Claude Code session history |
| `superton import chatgpt <export>` | Import ChatGPT `conversations.json` exports |
| `superton import cursor` | Import readable Cursor thread/log files |
| `superton import amp` | Import readable Amp thread/log files |
| `superton` | Launch the interactive CLI shell |
| `superton tune` | Edit the Modelfile and rebuild Miniton |

## Architecture

```
┌─────────────────────────────────────────────┐
│   superton CLI (typer + rich)               │
├─────────────────────────────────────────────┤
│   Miniton (Ollama + Modelfile)                │
├─────────────────────────────────────────────┤
│   memory: SQLite + MemPalace semantic index │
├─────────────────────────────────────────────┤
│   ingest: parsers + chunkers + importers    │
└─────────────────────────────────────────────┘
```

## Why?

ChatGPT forgets. Notion makes you file. Obsidian plugins call cloud APIs.
None of them give you a model that's *yours*, fed by a memory that's *yours*,
running on a machine that's *yours*. SuperTon does.

## Model Strategy

`Miniton` is SuperTon's local answer model. The default public/runtime tag is
`miniton`; by default it is built from `qwen2.5:1.5b-instruct` via Ollama.
You can override the base with `SUPERTON_BASE_MODEL`. Exact recall comes from
the palace drawers, not from model weights.

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

- **Phase 0** — palace, ingest, ask, lexical search, Claude Code import
- **Phase 1** *(current)* — semantic search via MemPalace, hybrid SQLite fallback
- **Phase 2** — `recall` / `thread` / `forgot` / `contradict` / `timeline`, file watcher
- **Phase 3** — Gemini importer, packaging polish, browser extension
- **Phase 4** — `evolve` (LoRA fine-tune from your drawers), web UI, browser extension

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Built on the shoulders of [Ollama](https://ollama.com),
[MemPalace](https://github.com/MemPalace/mempalace),
[Typer](https://typer.tiangolo.com), and [Rich](https://rich.readthedocs.io).
