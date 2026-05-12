# SuperTon

> A tiny local LLM with infinite memory. Your second brain that never forgets.

```
                    ⢀⣠⠤⠶⠒⠒⠒⠒⠶⠤⣄⡀
                ⢀⡴⠞⠉              ⠉⠳⢦⡀
              ⡰⠋   ░▒▓▓▓▒░    ░▒▓▓▓▒░   ⠙⢆
            ⢠⠞   ▒▓███████▓▒▒▓███████▓▒   ⠳⡄
          ⡜  ▓███⠋    ⢀⣀⣀⣀⣀⡀    ⠙███▓  ⢇
          ⡇ ▓██⠁  ⢠⣾█████████████⣷⡄  ⠈██▓ ⢸
          ⡇ █⠁  ⣸███████████████████⣇  ⠈█ ⢸
          ⢇ ⣿   ███████████████████████   ⣿ ⡸
           ⢣ ⠹⣷⡀ ⠉▀▀█████████████▀▀⠉ ⢀⣾⠏ ⡰
            ⠳⡄  ⠉⠳⣄⡀  ⠉⠉⠉⠉⠉  ⢀⣠⠞⠉  ⢠⠞
              ⠳⣄    ⠉⠓⠶⢤⣀⣀⡤⠶⠒⠉    ⣠⠞
                ⠈⠳⢦⣀⡀          ⢀⣠⡴⠞⠁
                    ⠉⠉⠛⠒⠒⠒⠒⠛⠉⠉
```

SuperTon is a CLI-first personal knowledge system. Feed it your notes, docs,
PDFs, and conversations from other AI tools. It indexes everything verbatim
into a **palace of memories**, then a tiny custom local model (`mini-ton`,
based on Qwen2.5-0.5B) answers your questions grounded in what you've fed it.

- 🕳 **Black hole memory** — drawers go in, nothing comes out warped, nothing is forgotten
- 🧠 **Tiny local model** — Qwen2.5-0.5B, customizable via `Modelfile`
- 🔒 **100% local** — no API keys, no cloud, no telemetry
- 📚 **Verbatim storage** — original text preserved; nothing summarized away
- 🔗 **Multi-source** — import from Claude Code, ChatGPT, Cursor and more
- 🪶 **Lightweight** — runs comfortably on a laptop

## Install

```bash
# requires python 3.10+ and ollama (https://ollama.com/download)
uv tool install superton
superton init
```

`superton init` will pull the base model + embeddings, build your custom
`mini-ton` from the `Modelfile`, and create the palace at
`~/Library/Application Support/superton/palace`.

## Quickstart

```bash
# feed it
superton add ~/notes
superton add ~/research/paper.pdf --wing research --room nlp
superton import claude-code

# ask it
superton ask "what did i decide about graphql last spring?"
superton ask "open issues in the auth refactor" --why

# explore
superton list
superton search "rate limiting"
superton stats
```

## Commands

| Command | Purpose |
|---|---|
| `superton init` | One-time setup: palace + model |
| `superton add <path>` | Ingest a file or directory |
| `superton ask "..."` | Query mini-ton with palace context |
| `superton list` | Show recent drawers |
| `superton search "..."` | Lexical search across drawers |
| `superton forget <id>` | Remove a drawer |
| `superton stats` | Palace statistics |
| `superton import claude-code` | Import Claude Code session history |
| `superton tune` | Edit the Modelfile and rebuild mini-ton |

## Architecture

```
┌─────────────────────────────────────────────┐
│   superton CLI (typer + rich)               │
├─────────────────────────────────────────────┤
│   mini-ton (Ollama, Qwen2.5-0.5B + Modelfile)│
├─────────────────────────────────────────────┤
│   memory: SQLite + FTS  (MemPalace planned) │
├─────────────────────────────────────────────┤
│   ingest: parsers + chunkers + importers    │
└─────────────────────────────────────────────┘
```

## Why?

ChatGPT forgets. Notion makes you file. Obsidian plugins call cloud APIs.
None of them give you a model that's *yours*, fed by a memory that's *yours*,
running on a machine that's *yours*. SuperTon does.

## Roadmap

- **Phase 0** *(current)* — palace, ingest, ask, lexical search, Claude Code import
- **Phase 1** — semantic search via embeddings, MemPalace integration, knowledge graph
- **Phase 2** — `recall` / `thread` / `forgot` / `contradict` / `timeline`, file watcher, TUI
- **Phase 3** — animated boot, importers for ChatGPT/Cursor/Amp/Gemini
- **Phase 4** — `evolve` (LoRA fine-tune from your drawers), web UI, browser extension

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Built on the shoulders of [Ollama](https://ollama.com),
[Qwen](https://github.com/QwenLM/Qwen2.5), [MemPalace](https://github.com/MemPalace/mempalace),
[Typer](https://typer.tiangolo.com), and [Rich](https://rich.readthedocs.io).
