# SuperTon UI/UX Plan — Install → Daily Use

> A staged plan for tightening every moment a user spends with SuperTon,
> from the `curl | sh` line in the README to the 30th `superton ask`. Each
> stage names: the moment, what's wrong today, what to change, and why it
> matters. Ordered so the highest-leverage moments ship first.
>
> Companion to `docs/UX_ROADMAP.md` — the roadmap is a backlog; this doc
> is the *opinionated narrative* of how the product should feel end-to-end.

## Design principles

These are the rules every UX decision below has to obey.

1. **Tri-color signal palette during install.** Orange = progress / success.
   Yellow = attention without alarm (warnings, tight RAM, unknowns). Red =
   hard failure only. Everything else is muted grey or theme-neutral text.
   No green, no cyan, no fourth signal channel.
2. **Active theme owns post-install.** Once init finishes, the user's
   chosen theme (nebula / mono / solar / frost) is the source of truth.
   The install palette never appears in chat or search.
3. **Every prompt is preceded by a plan.** Users see the full sequence
   (`preflight_card`) before any prompt fires. No surprise dialogs.
4. **Every error carries a recovery hint.** `stage_warn(msg, hint=...)`
   is the only way to surface a problem. A warning without a hint is a bug.
5. **First 10 minutes are sacred.** Anything that delays the user's first
   successful `ask` is a regression — even if it's "technically correct".

## Install palette (current, after this PR)

| Color | Hex | Use |
|---|---|---|
| `INSTALL_ORANGE` | `#FFB02E` | `✓`, `→`, fits, headers, ready card, selected-card border |
| `INSTALL_YELLOW` | `#FFD93D` | `!`, tight RAM, hints — anything recoverable |
| `INSTALL_RED`    | `#F0471F` | `✗`, "stage failed", uncaught exception card |
| muted (theme)    | grey50    | `?` rows, dim copy, body text |

Rule of thumb: if removing the color leaves the message ambiguous, it
earned a slot. If the color is decoration, it's wrong.

---

## Stage 1 — discovery (the README & install.sh)

**Moment**: user lands on the GitHub repo, scrolls README, runs the curl line.

**What's wrong today**:
- README is 22 KB. The first install command is below the fold on most
  monitors. Newcomers scan and bounce.
- `install.sh` prints raw `echo` lines — no color, no progress, no fit
  with the in-product palette. Feels like a different product than init.
- No way to know what `install.sh` *will* do before running it. We tell
  users to pipe a remote script to `sh`; the friendly thing is to show
  what's about to happen.

**Change**:
- README: lead with a 60-second pitch + one install command, then the
  three-bullet "what is this". Push deep config below the fold.
- `install.sh`: ANSI-colorize using the install palette
  (`\033[38;2;255;176;46m` for orange, etc.). Show a preflight before
  doing anything: "will install uv, will install superton". Honor `--dry-run`.
- `install.sh`: detect existing install and say "you have N.N.N, upgrading
  to M.M.M" instead of silently re-running `uv tool install --force`.

**Why**: the install script is the first product surface. If it feels
careless, users assume the product is too.

---

## Stage 2 — `superton init` (the 90-second moment that decides retention)

**Moment**: user runs `superton init` after the shell installer finishes.

**What's already good**:
- `preflight_card` shows the plan before any prompt — keep it.
- `stage(step=N, total=M)` numbers each step — keep it.
- Model-profile picker uses cards with RAM-fit bars — keep it.
- Tri-color palette now consistent — keep it.

**What's wrong today**:
- Pre-flight card doesn't tell users they can `^C` out safely. People
  hesitate, fearing a partial install.
- Theme picker is a wall of swatches. The user has no way to *preview* a
  theme before committing — they pick a name and hope.
- After picker selections, init plows straight into model download. No
  "about to download ~2.1 GB, continue?" confirmation for the big-RAM
  profiles. Users on metered connections are surprised.
- Stage 5 (Modelfile build) is silent for 30–60 seconds. Looks frozen.
- When a stage warns, the `↳` recovery hint is dim grey. On low-contrast
  terminals it disappears. The most important text in the flow.

**Change** (in priority order):

1. **Show `^C` is safe** under the preflight card title: `▸ about to do · ^C safe at any prompt`.
2. **Live theme preview**: in `_pick_theme`, after each card render a
   2-line sample (a `hint()`, a `stage_ok()`, a `pill`) using *that*
   theme's colors. Users see the theme before typing its name.
3. **Download confirmation**: in stage 3, before pulling the base model,
   show a one-line confirm: `pulling 2.1 GB · proceed? [Y/n]`. Auto-yes
   under `--yes`. Saves users from accidental multi-GB pulls.
4. **Heartbeat during silent stages**: replace the Modelfile-build silence
   with a spinner that updates every 200 ms ("compiling system prompt…",
   "writing Modelfile…", "registering with ollama…"). Already have
   `Progress` in `ui.py`; wire it in.
5. **Bold the recovery hint**: bump `↳` lines from muted to
   `bold {INSTALL_YELLOW}` so they read as *the answer*, not footnote text.
6. **Resumable init**: write a `~/.superton/.init-state.json` marker after
   each stage. `superton init` resumes from the last completed stage.
   Today, an interrupted init re-runs every stage from scratch.

**Why**: this is the single screen where most users decide whether
SuperTon is "real software" or a weekend project. Every friction point
here costs an install.

---

## Stage 3 — the ready card & first ten seconds

**Moment**: init finishes, the ready card prints, the user reads "Start here:".

**What's wrong today**:
- The ready card lists 6 commands. Cognitive overload at minute zero.
- The card doesn't make it obvious that `superton add ~/notes` is *step 1*.
  All four commands look equal.
- There's no empty-palace hint. New users run `superton ask "hi"` and get
  a confused refusal because nothing's been ingested.

**Change**:
- Restructure the ready card into a **2-step ladder**:
  ```
  ▸ ready
    1.  superton add ~/notes        ← do this first
    2.  superton                    then chat
  ```
  Push `import claude-code`, `mcp serve`, `doctor` into a dim "also
  available:" footer under the ladder.
- Add a one-line **empty-palace hint** at the very bottom of the card,
  styled `muted italic`: *"your palace is empty — ingest something to
  ground answers."*
- Ship a **`superton demo`** subcommand (per UX roadmap → Soon). At the
  end of init, offer it as an opt-in: `seed a 3-drawer demo palace? [y/N]`.
  Users who say yes can `ask` immediately without finding their own data.

**Why**: this card is the bridge between "install worked" and "I see why
I want this". Right now the bridge is two short planks and a swarm of
options.

---

## Stage 4 — first interactive session (REPL)

**Moment**: user runs `superton` (no args) for the first time.

**What's wrong today**:
- The REPL drops straight to a prompt with no orientation. Most CLI users
  are conditioned to type `/help` or `--help`, but slash-mode is invisible
  until they discover it.
- `/help` is a wall of text. Hard to scan, no grouping.
- The streaming response shows a typing cursor (`▎`) — good — but no
  citation count or retrieval status. Users wonder "is it making this up?"

**Change**:
- On first-ever REPL invocation (gate via `cfg.first_repl_done` flag),
  show a **2-line onboarding banner** that auto-dismisses on first input:
  ```
  type / to see commands · type your question to chat · ^D to quit
  press ? any time for the cheatsheet
  ```
- Redesign `/help` as a **3-column card** grouped by `ingest / search /
  config`. Already in UX roadmap → Soon.
- During `ask`, show a **retrieval line** above the streaming response:
  `▸ found 4 drawers (avg score 0.81) · grounding…`. Builds trust by
  making the RAG step visible.
- Render **citations as numbered chips** under the answer, not as a
  trailing paragraph: `[1] ~/notes/india-trip.md  [2] claude:abc123`.

**Why**: retention happens here. If a user can't tell whether the answer
came from their data, they go back to ChatGPT.

---

## Stage 5 — errors, recovery, observability

Errors are part of the UX. Today's gaps:

- Unhandled exceptions print Python tracebacks. Should print a 4-line
  **crash card** via the existing `errors.render` path, with: one-line
  error, hint, recovery command, `--debug` suggestion.
- `superton doctor` shows status but doesn't tell users **how SuperTon
  was installed** (uv / pipx / pip) — support starts every thread with
  that question.
- `SUPERTON_LOG=debug` is invisible until a user reads the source. After
  any init warning, show a dim "rerun with `SUPERTON_LOG=info` for more
  detail" footer.
- `superton uninstall` should optionally archive the palace as a tarball
  before deleting — open question in UX roadmap, answer it: **yes,
  always, unless `--no-archive`**. Data loss is unrecoverable; an extra
  60 MB tarball isn't.

---

## Sequencing — what to ship in what order

Priority is: how much each change moves the **install → first-success**
funnel.

### Phase 1 — next PR (2–3 days)
- ✅ Tri-color install palette (this PR).
- README rewrite: 60-second pitch above the fold.
- Ready card → 2-step ladder + empty-palace hint.
- Live theme preview in `_pick_theme`.
- Bold the `↳` recovery hint.

### Phase 2 — week after (1 week)
- `superton demo` subcommand, offered at end of init.
- First-REPL onboarding banner.
- `/help` 3-column redesign.
- Download confirm before stage 3 model pull.

### Phase 3 — month two
- Resumable init (state marker file).
- Retrieval line + citation chips in REPL `ask`.
- Crash card via `errors.render` for unhandled exceptions.
- `superton uninstall --archive` default.

### Phase 4 — opportunistic
- `install.sh` colorized + `--dry-run`.
- Heartbeat spinner for the Modelfile build stage.
- `doctor` shows install method.
- `SUPERTON_LOG=info` discoverability footer after warned stages.

---

## How to measure each phase

We don't ship telemetry — by design. So measurement is qualitative:

- Run the install on a **clean machine** before each phase ships. Time
  the gap between `curl | sh` and the first successful `ask` that
  cites a real drawer.
- Read every new user issue / PR comment with the question: *"would
  this phase have prevented this thread?"*
- Once a month, do a **silent re-onboarding**: wipe `~/.superton`,
  re-install from main, narrate the experience into `docs/walkthroughs/`.
  Anything that made you wince is a Phase-1 candidate for the next cycle.

---

## Out of scope (deliberately)

These come up regularly. We're not doing them yet:

- **Telemetry / opt-in analytics** — privacy is the brand. Phase-4 at
  earliest, and only if every other lever has been pulled.
- **Web UI** — second frontend; not worth maintaining alongside the CLI yet.
- **Auto-update** — possible in Phase 3 via `uv tool install --upgrade`,
  but only as an explicit `superton update`, never silent.
- **Team palace / sharing** — undermines local-first. Revisit after 1.0.
