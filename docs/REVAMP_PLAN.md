# SuperTon Revamp Plan

*The product bet, the feature tracks, and the release sequence.
Companion to `UX_PLAN.md` / `UX_ROADMAP.md`, which cover interaction
polish; this document covers what SuperTon becomes.*

## The positioning problem

Today SuperTon is a *tool you run*: you remember to `superton add`
things, then you ask. Khoj, mem0, AnythingLLM, and Obsidian-with-plugins
all live in that same "manual local RAG" space.

The unique ground SuperTon is closest to — and nobody owns yet — is:

> **The always-current, shared memory layer for every AI agent on your
> machine.** Claude Code, Cursor, and your own notes feed one palace
> automatically; every tool reads from it over MCP; and you can ask it
> about *time* ("what was I doing last Tuesday?"), not just topics.

Three properties make that defensible:

1. **Always current.** A palace you must feed by hand goes stale in a
   week; one that feeds itself becomes infrastructure.
2. **Shared.** The MCP server already exposes 29 tools — the palace is
   the one brain every agent on the machine can read and write.
3. **Temporal.** Verbatim drawers carry `created_at`; competitors
   summarize away exactly the provenance that makes time queries work.

Everything below is sequenced toward that.

## Phase 1 — "It stays current by itself" *(v0.5)*

The single biggest bet; it changes the product category from tool to
system.

- **`superton watch`** — a watcher that monitors configured folders
  *plus* the AI-tool transcript dirs the importers already understand
  (`~/.claude/projects`, `~/.cursor`, `~/.amp`). New or changed files
  auto-ingest within the polling interval.
  - `superton watch add|remove|list` manages the watchlist.
  - `superton watch --once` runs a single scan pass (cron-friendly and
    trivially testable).
- **Incremental refresh** — mtime + size snapshots detect changed
  files; a changed file is refreshed (forget + re-ingest) instead of
  duplicated. Content-addressed drawer ids already make unchanged
  chunks free.
- **Deletion is not forgetting.** A watched file that disappears keeps
  its drawers — the palace is memory, not a mirror. `superton
  forget-source` remains the explicit eviction path.
- Follow-ups: native FS events (watchfiles) instead of polling;
  `superton watch install` for launchd/systemd persistence.

## Phase 2 — Time & entities *(v0.6)*

The "wow" queries. MemPalace's knowledge graph is already a dependency
— use it.

- **`superton timeline [--days N]`** — chronological view of what
  entered the palace: per-day sections, per-source drawer counts.
- **`superton digest [--days N]`** — a generated brief: "what you
  worked on, decided, and left open," with citations. The
  screenshot-able demo feature. Falls back to a non-model source
  summary when no backend is available.
- **`superton about "person or project"`** — everything the palace
  knows about one entity, aggregated across sources.
- **Temporal retrieval** — parse "last spring", "in March" in questions
  and constrain retrieval by `created_at` before ranking.

## Phase 3 — Trust & recall UX *(v0.7)*

- **`superton open <drawer-id>`** — jump from a citation to the full
  drawer and its source file. Citations become actionable; that closes
  the loop that makes people trust answers.
- **`superton recall`** — resurface aged drawers ("from 42 days ago")
  — a second-brain feature no RAG competitor has.
- **Confidence surfacing** — a low-grounding banner instead of a
  confidently thin answer.
- **Ingest breadth** — OCR fallback for image PDFs and screenshots;
  Gemini CLI + Codex importers; browser bookmarks; `.mbox` email.
- **Plugin importers** via Python entry points so the community can add
  sources without touching core.

## Phase 4 — Sync & portability *(v0.8–0.9)*

- **`superton sync`** — palace sync through the user's own remote (a
  private git repo or any synced folder), built on the
  `export`/`import-palace` JSONL round-trip. Optional symmetric
  encryption. *Your memory follows you and still never touches our
  servers.*
- **Palace merge semantics** — content-addressed ids make union-merge
  safe by construction; conflicts cannot exist, only duplicates that
  dedupe.

## Phase 5 — The 1.0 headline

- **`superton evolve`** — LoRA fine-tune from your drawers, so the
  answer model gradually speaks in your voice. Ship last: it needs the
  always-on pipeline (Phase 1) supplying fresh training data and sync
  (Phase 4) to make the artifact portable.
- Hardening pass: crash-safe watcher state, palace integrity check
  (`superton doctor --deep`), packaging polish.

## What we explicitly will NOT do

- **No web UI before 1.0.** It dilutes the CLI identity and doubles the
  maintenance surface — the Textual TUI was removed for exactly this
  reason.
- **No screen-recording / keylogging capture.** That is Rewind's lane;
  the privacy blast radius conflicts with the local-first brand.
- **No cloud service of any kind.** Sync uses remotes the user already
  controls.

## Release mapping

| Release | Contents | Why this order |
|---|---|---|
| v0.5 | `watch` + incremental refresh | Changes the product category |
| v0.6 | `timeline`, `digest`, `about`, temporal queries | The demo-able magic |
| v0.7 | `open` / `recall` / confidence + importers + OCR | Depth and trust |
| v0.8–0.9 | `sync`, plugin importers | Multi-machine story |
| v1.0 | `evolve` + hardening | The headline |

## Sequencing rationale

`watch` comes first because it multiplies the value of everything after
it: `digest` is only interesting if the palace is current, `recall`
only if it is deep, `evolve` only if it is both. Each phase lands as an
independent branch + PR so releases can ship the moment their phase
merges.
