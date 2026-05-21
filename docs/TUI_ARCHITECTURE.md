# SuperTon TUI — Design Doc

> Status: design only · no code yet · target: become the default `superton` interactive mode

## 1. Why a TUI

The current `prompt_toolkit` shell is a polished REPL: prompt, slash commands,
bottom toolbar. It's fast, but it forces every action through a single line of
text. Even simple flows need typing:

- "what drawers do I have for resume.pdf?" → `/sources` then squint at table
- "scroll back through my last 6 questions" → re-run the same query
- "switch model and check it built ok" → `/model better` then `/doctor`
- "what's in this drawer?" → there is no way; only `search` shows previews

A TUI gives the same data **spatially** rather than sequentially. The user sees
the palace, the chat, and the active context **at the same time**, navigates
with arrows / fuzzy search, and stays in one screen.

### Goals

1. Make the palace **visible** — recent drawers, current source, retrieval state
   are always on screen.
2. Make chat **scrollable** — the answer history is a real widget, not console
   scrollback.
3. Make discovery **keyboard-driven** — every action reachable from the keyboard
   in ≤2 keystrokes; mouse is a nice-to-have, not the default.
4. Keep the existing **theme system** (`nebula / mono / solar / frost`) as the
   canonical visual identity. The TUI is the same brand, not a redesign.
5. Maintain feature parity with the shell so it can become the default.

### Non-goals

- Not a full IDE. No multi-tab, no editor pane, no plugin system.
- Not a redesign. The TUI inherits the existing icon vocabulary and color
  palette; only the layout is new.
- Not a graphical replacement for `superton add`, `superton import`, etc. The
  CLI subcommands stay shell-callable.

## 2. Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ❍ SuperTon · nebula · miniton:fast · ● online                  palace · 432  │  header
├─────────────────────────────────┬────────────────────────────────────────────┤
│  /  search drawers              │                                            │
│ ────────────────────────────    │  ▎ Miniton                                 │
│  ▸ 12 jan · resume.pdf          │                                            │
│       3 drawers · projects, …   │  The resume mentions three project areas:  │
│  ▸  9 jan · README.md           │  • SuperTon — local LLM palace…            │
│       7 drawers · architecture  │  • MemPalace — hybrid retrieval…           │
│  ▸  8 jan · claude-code:abc.jl  │  • Web puller — native Python crawl…       │
│      14 drawers · planning      │                                            │
│  ▸  6 jan · notes.md            │  sources  [ 1 ] abcd1234 resume.pdf        │
│       2 drawers · misc          │           [ 2 ] ef901234 README.md         │
│                                 │                                            │
│  …↓ 12 more                     │  ─────────────────────────────────────     │
│                                 │                                            │
│                                 │  > what about projects                     │
├─────────────────────────────────┴────────────────────────────────────────────┤
│ chatting · F1 help · F2 sources · F3 search · / cmd · ? bindings · Ctrl+C quit│  footer
└──────────────────────────────────────────────────────────────────────────────┘
```

### Three panes

| pane             | width        | purpose                                                   |
| ---------------- | ------------ | --------------------------------------------------------- |
| **header**       | full · 1 row | Theme/model/backend pills, palace size                    |
| **sidebar**      | left · 32 col| Source list, recent drawers, search input                 |
| **main**         | flex         | Scrollable chat transcript + input field at bottom        |
| **footer**       | full · 1 row | Mode breadcrumb + key bindings + connection state         |

Sidebar collapses below 80 col terminals; main pane becomes full-width with a
slide-out drawer (Ctrl+B) replacing it.

## 3. Screens / modes

Only **one screen** — but the focus changes which pane responds to typing.
Modes are visual signals (header pill turns primary) plus footer breadcrumb.

| mode        | when                       | what changes                                  |
| ----------- | -------------------------- | --------------------------------------------- |
| `chatting`  | input field focused        | Typing = message. ↑/↓ = history. Enter = ask. |
| `searching` | `/` pressed                | Sidebar becomes a fuzzy search of drawers.    |
| `palette`   | `Ctrl+K` pressed           | Modal slash-command palette (drop-down)       |
| `viewing`   | drawer selected in sidebar | Main pane shows the full drawer text + meta   |
| `help`      | `?` or F1                  | Modal cheatsheet                              |

## 4. Key bindings

### Global

| key             | action                                          |
| --------------- | ----------------------------------------------- |
| `Ctrl+C` × 2    | Quit (single press = cancel current operation)  |
| `Ctrl+B`        | Toggle sidebar                                  |
| `Ctrl+K`        | Open command palette                            |
| `Ctrl+L`        | Clear chat                                      |
| `?` or `F1`     | Show help modal                                 |
| `Esc`           | Cancel / close modal / return to chat input     |
| `Tab` / `Shift+Tab` | Cycle focus between panes                   |

### Sidebar (when focused)

| key          | action                                          |
| ------------ | ----------------------------------------------- |
| `↑` / `↓`    | Navigate drawers                                |
| `Enter`      | Open drawer in main pane (viewing mode)         |
| `/`          | Fuzzy search                                    |
| `d`          | Forget drawer (with confirm)                    |
| `r`          | Refresh source                                  |
| `g g` / `G`  | Jump to top / bottom (vim-style)                |

### Chat input (when focused)

| key          | action                                          |
| ------------ | ----------------------------------------------- |
| `Enter`      | Send message                                    |
| `↑` / `↓`    | History prev/next                               |
| `Ctrl+R`     | Reverse search through history                  |
| `Ctrl+U`     | Clear line                                      |
| `/cmd args`  | Run slash command (back-compat with shell)      |

### Command palette (`Ctrl+K`)

Fuzzy match across all slash commands plus high-level actions:
`switch theme · switch model · open doctor · import claude-code · refresh source`.

## 5. State model

```python
@dataclass
class AppState:
    cfg: Config
    mem: Memory
    model: Model
    chat: list[ChatTurn]          # (role, text, citations)
    sidebar: SidebarState
    focus: Literal["chat", "sidebar", "palette"]
    mode: Literal["chatting", "searching", "viewing", "help"]
    backend_online: bool          # cached, refreshed every 4s
    pending_op: str | None        # spinner label, None when idle

@dataclass
class SidebarState:
    items: list[SourceRow]        # sorted by recency
    cursor: int                   # selected index
    filter: str                   # fuzzy query
    selected_drawer: Drawer | None
```

Single source of truth. Widgets read from `AppState` via Textual's reactive
system; mutations happen in command handlers that post `RefreshState` messages.

## 6. Component breakdown

```
superton/tui/
├── __init__.py
├── app.py              # SupertonApp(textual.App), main entry
├── state.py            # AppState dataclasses + reactive bindings
├── widgets/
│   ├── header.py       # status pills row
│   ├── sidebar.py      # source/drawer list + search
│   ├── chat.py         # scrollable transcript + streaming
│   ├── input.py        # message input with history
│   ├── palette.py      # Ctrl+K modal
│   ├── drawer_view.py  # full-drawer reader
│   └── help.py         # cheatsheet modal
├── theme.py            # bridge from ui.Theme to Textual CSS
└── styles.tcss         # Textual CSS — sources from ui.theme()
```

### Why a `theme.py` bridge

Textual uses its own CSS-like styling (`.tcss`). We already have four themes
in `superton/ui.py`. The bridge generates a `.tcss` string from the active
`Theme` so `superton theme solar` immediately repaints the TUI without an
app restart.

### Reuse, don't fork

| existing module     | TUI consumption                                              |
| ------------------- | ------------------------------------------------------------ |
| `superton.memory`   | Used directly — no wrapping                                  |
| `superton.model`    | Used directly                                                |
| `superton.shell._answer`, `_is_meta_question`, etc. | Extracted to `superton.chat` as a pure module the TUI imports |
| `superton.errors`   | TUI renders `errors.hint_for(exc)` in a toast widget         |
| `superton.logging`  | Tail surfaced as an optional `log` pane (F4)                 |

The shell's `_answer()` is currently entangled with `ui.stream_answer`. Step 1
of the migration is to extract the pure logic into `superton/chat.py` so both
the shell and the TUI call the same function.

## 7. Becoming the default

Phased rollout so existing users aren't surprised:

| version | behavior                                                                                 |
| ------- | ---------------------------------------------------------------------------------------- |
| `0.2.0` | `superton tui` opt-in. Existing shell stays default. Doc the TUI in README.              |
| `0.3.0` | `superton` (no args) launches TUI **if** stdout is a TTY ≥ 80 cols and `textual` is importable. Otherwise falls back to the classic shell. `--classic` flag forces the shell. |
| `0.4.0` | TUI is the default unconditionally. Classic shell still available via `--classic` for one more minor version. |
| `0.5.0` | Classic shell removed. `superton --classic` prints a deprecation note and launches TUI.  |

Each step is a soft default change with a printed `note: TUI is now the default. Use --classic to keep the old shell.`

## 8. Open questions

1. **Mouse support** — Textual supports it for free, but it complicates focus
   semantics on terminals without mouse forwarding (mosh, some tmux configs).
   Default to *enabled*; expose `--no-mouse`.
2. **Wide terminal layout** — at ≥ 140 cols, do we add a third pane (drawer
   preview) or just stretch the chat? Recommend stretch — three panes start to
   feel like an IDE.
3. **Streaming inside a widget** — Textual's `RichLog` widget supports
   streaming updates but redraws the whole widget on each token. For long
   answers this could flicker on slow terminals. Mitigation: buffer tokens for
   ~50ms and flush in batches.
4. **Markdown rendering height** — Rich's `Markdown` renderable has variable
   height; the chat widget needs to know each turn's height for scroll
   anchoring. Use `console.measure()` per turn and cache.
5. **Modal vs inline palette** — Ctrl+K could open a centered modal (VS Code
   style) or expand the sidebar (Slack style). Recommend modal — simpler
   focus model.
6. **History persistence** — chat history currently lives in memory only. TUI
   makes it tempting to persist; recommend not yet (privacy default), but add
   a `[chat] persist = true` config option later.
7. **Concurrent ops** — TUI lets the user trigger an import while a chat is
   streaming. Either serialize (simpler) or use Textual's worker system. Start
   serial, surface "operation queued" toasts, upgrade later if it bites.

## 9. Test strategy

- **Unit tests** for `superton.chat` (the extracted pure logic).
- **Snapshot tests** via `pytest-textual-snapshot` for each widget at the four
  themes. ~12 snapshots total.
- **Integration tests** that drive the app with `Pilot` (Textual's testing
  harness): send keystrokes, assert visible state. Cover the five modes.
- **No new coverage floor** — the TUI lives in `superton/tui/` and is excluded
  from the strict mypy overrides; widget code is hard to mypy cleanly.

## 10. Risks

| risk                                                                 | mitigation                                                                 |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Textual is a heavy dep (5+ MB, transitive list)                      | Make it an `extra`: `pip install 'superton[tui]'`. Shell-only install stays lean. |
| Terminal compat (older xterm, Windows Conhost, Mosh)                 | Auto-fallback to classic shell when feature-probing fails.                  |
| User muscle memory from the shell breaks                             | Slash commands work identically. Footer always shows the next-step keys.    |
| TUI consumes more CPU on idle (Textual repaints animations)          | Pause non-essential animation timers when not focused; respect `--no-animation`. |
| Snapshot tests get flaky across Python / Textual versions            | Pin Textual minor version; regenerate snapshots in a single CI job.         |

## 11. Effort estimate

| milestone                                                  | effort  |
| ---------------------------------------------------------- | ------- |
| Extract `superton.chat` from `superton.shell._answer`      | 1 day   |
| App skeleton + header/footer + theme bridge                | 1 day   |
| Sidebar with sources + drawer view + fuzzy filter          | 2 days  |
| Chat widget with streaming + citation chips                | 2 days  |
| Command palette + slash-command back-compat                | 1 day   |
| Modes + key bindings + focus management                    | 1 day   |
| Snapshot tests + Pilot integration tests                   | 2 days  |
| Polish, docs update, packaging extra                       | 1 day   |
| **Total**                                                  | ~11 days|

## 12. Decision log

- **2026-05-21** — Chose Textual over urwid / blessed / pure prompt_toolkit
  layouts. Reason: matches existing Rich vocabulary, has built-in CSS theming,
  active maintenance.
- **2026-05-21** — Decided against three-pane layout at wide widths. Reason:
  starts to feel like an IDE; user feedback wanted "polished CLI", not a tool.
- **2026-05-21** — Decided against mouse-first design. Reason: target audience
  lives in tmux/mosh; keyboard-first is the cohesive choice.
