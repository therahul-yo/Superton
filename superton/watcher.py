"""Auto-ingest watcher — keeps the palace current without manual `add`s.

`superton watch` polls a user-managed watchlist of files/directories plus
the AI-tool transcript roots the importers already understand
(`~/.claude/projects`, `~/.cursor`, `~/.amp`). New files are ingested,
changed files are refreshed (forget + re-ingest), and files that
disappear keep their drawers — the palace is memory, not a mirror.

Design notes:
- Polling (mtime + size snapshot) instead of native FS events: zero new
  dependencies, identical behavior on macOS/Linux/CI, and a `--once`
  mode that is trivially cron-able and testable. Native events can land
  later behind the same `scan_once()` seam.
- State lives in `<home>/watch_state.json`; the watchlist in
  `<home>/watchlist` (one path per line, `#` comments allowed).
- Content-addressed drawer ids make the first scan of an
  already-ingested corpus a cheap all-dedup pass.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superton.config import Config
from superton.ingest import chunk_text, file_too_large, read_file, walk
from superton.logging import get_logger
from superton.memory import Memory

log = get_logger("watcher")

WATCHLIST_FILE = "watchlist"
STATE_FILE = "watch_state.json"

# (importer name, default root) — matched against the importers wired in
# `default_transcript_roots`.
TRANSCRIPT_DIRS: tuple[tuple[str, str], ...] = (
    ("claude-code", "~/.claude/projects"),
    ("cursor", "~/.cursor"),
    ("amp", "~/.amp"),
)

# File signature: (mtime, size). Size catches same-second appends;
# mtime catches same-size rewrites.
Signature = tuple[float, int]


# --- watchlist ------------------------------------------------------------


def watchlist_path(cfg: Config) -> Path:
    return cfg.home / WATCHLIST_FILE


def load_watchlist(cfg: Config) -> list[Path]:
    path = watchlist_path(cfg)
    if not path.exists():
        return []
    out: list[Path] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(Path(line).expanduser())
    return out


def save_watchlist(cfg: Config, paths: list[Path]) -> None:
    path = watchlist_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(str(p) for p in paths)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def add_watch(cfg: Config, target: Path) -> bool:
    """Add `target` to the watchlist. Returns False when already present."""
    resolved = target.expanduser()
    current = load_watchlist(cfg)
    if resolved in current:
        return False
    current.append(resolved)
    save_watchlist(cfg, current)
    return True


def remove_watch(cfg: Config, target: Path) -> bool:
    """Drop `target` from the watchlist. Returns False when not present."""
    resolved = target.expanduser()
    current = load_watchlist(cfg)
    if resolved not in current:
        return False
    save_watchlist(cfg, [p for p in current if p != resolved])
    return True


def default_transcript_roots() -> list[tuple[str, Path]]:
    """Transcript roots that exist on this machine."""
    out: list[tuple[str, Path]] = []
    for name, raw in TRANSCRIPT_DIRS:
        root = Path(raw).expanduser()
        if root.exists():
            out.append((name, root))
    return out


# --- scanning -------------------------------------------------------------


@dataclass
class ScanReport:
    """What one `scan_once()` pass did."""

    new_files: int = 0
    changed_files: int = 0
    skipped_files: int = 0
    drawers_added: int = 0
    drawers_deduped: int = 0
    transcript_files: int = 0
    transcript_drawers: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def activity(self) -> int:
        """Non-zero when the pass touched the palace at all."""
        return (
            self.new_files
            + self.changed_files
            + self.drawers_added
            + self.transcript_files
            + self.transcript_drawers
        )


def _snapshot(roots: list[Path]) -> dict[str, Signature]:
    """Signature map for every ingestable file under `roots`."""
    snap: dict[str, Signature] = {}
    for root in roots:
        if not root.exists():
            continue
        for f in walk(root):
            try:
                st = f.stat()
            except OSError:
                continue
            snap[str(f)] = (st.st_mtime, st.st_size)
    return snap


def _transcript_snapshot(roots: list[tuple[str, Path]]) -> dict[str, tuple[str, Signature]]:
    """Signature map for transcript files, tagged with their importer name."""
    snap: dict[str, tuple[str, Signature]] = {}
    for name, root in roots:
        if not root.exists():
            continue
        if name == "claude-code":
            files: list[Path] = list(root.rglob("*.jsonl"))
        else:
            from superton.importers.generic_threads import READABLE

            files = [
                p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in READABLE
            ]
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            snap[str(f)] = (name, (st.st_mtime, st.st_size))
    return snap


class Watcher:
    """Polls the watchlist + transcript roots and ingests what changed.

    `roots` / `transcript_roots` are injectable for tests; by default they
    come from the watchlist file and the standard transcript locations.
    """

    def __init__(
        self,
        cfg: Config,
        mem: Memory,
        *,
        roots: list[Path] | None = None,
        transcript_roots: list[tuple[str, Path]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.mem = mem
        self.roots = roots if roots is not None else load_watchlist(cfg)
        self.transcript_roots = (
            transcript_roots if transcript_roots is not None else default_transcript_roots()
        )
        self.state_path = cfg.home / STATE_FILE
        self._state = self._load_state()

    # -- state persistence ---------------------------------------------

    def _load_state(self) -> dict[str, dict[str, list[float]]]:
        if not self.state_path.exists():
            return {"files": {}, "transcripts": {}}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("watch state unreadable, starting fresh: %s", e)
            return {"files": {}, "transcripts": {}}
        return {
            "files": dict(raw.get("files") or {}),
            "transcripts": dict(raw.get("transcripts") or {}),
        }

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _unchanged(prev: Any, sig: Signature) -> bool:
        return prev is not None and tuple(prev) == sig

    # -- ingestion ------------------------------------------------------

    def _ingest_file(self, path: Path, report: ScanReport) -> None:
        if file_too_large(path):
            report.skipped_files += 1
            return
        try:
            text = read_file(path)
        except ValueError:
            # Unsupported file type (images, binaries) — routine in any
            # watched folder, not worth surfacing per-file.
            report.skipped_files += 1
            return
        except (RuntimeError, UnicodeDecodeError) as e:
            report.skipped_files += 1
            report.errors.append(f"{path.name}: {e}")
            return
        if not text.strip():
            return
        for chunk in chunk_text(text):
            self.mem.add(text=chunk, source=str(path), wing="watch", room=path.parent.name or "default")
            if self.mem.last_insert_was_new:
                report.drawers_added += 1
            else:
                report.drawers_deduped += 1

    def _import_transcript(
        self, name: str, path: Path, *, replace: bool, report: ScanReport
    ) -> None:
        try:
            if name == "claude-code":
                from superton.importers.claude_code import ClaudeCodeImporter

                drawers = ClaudeCodeImporter(self.mem).import_session(path, replace=replace)
            else:
                from superton.importers.generic_threads import GenericThreadImporter

                _files, drawers = GenericThreadImporter(
                    self.mem, name, path
                ).import_all(path, replace=replace)
        except (OSError, ValueError, RuntimeError) as e:
            report.errors.append(f"{name}:{path.name}: {e}")
            return
        if drawers:
            report.transcript_files += 1
            report.transcript_drawers += drawers

    # -- the scan pass ----------------------------------------------------

    def scan_once(self) -> ScanReport:
        """One polling pass: detect new/changed files, ingest, persist state.

        Files that disappeared since the last pass are dropped from the
        state but keep their drawers — deletion is not forgetting.
        """
        report = ScanReport()

        old_files = self._state["files"]
        snap = _snapshot(self.roots)
        for path_str, sig in snap.items():
            prev = old_files.get(path_str)
            if self._unchanged(prev, sig):
                continue
            changed = prev is not None
            if changed:
                # Refresh semantics: drop stale chunks before re-ingesting
                # so edits don't accumulate near-duplicate drawers.
                self.mem.forget_source(path_str)
                report.changed_files += 1
            else:
                report.new_files += 1
            self._ingest_file(Path(path_str), report)
        self._state["files"] = {k: list(v) for k, v in snap.items()}

        old_tx = self._state["transcripts"]
        tx_snap = _transcript_snapshot(self.transcript_roots)
        for path_str, (name, sig) in tx_snap.items():
            prev = old_tx.get(path_str)
            if self._unchanged(prev, sig):
                continue
            # A changed session must be replaced: the importers skip
            # already-indexed sources, so appended turns would otherwise
            # never land.
            self._import_transcript(
                name, Path(path_str), replace=prev is not None, report=report
            )
        self._state["transcripts"] = {k: list(sig) for k, (_n, sig) in tx_snap.items()}

        self._save_state()
        if report.activity:
            log.info(
                "watch pass: +%d new, ~%d changed, %d drawers, %d transcript drawers",
                report.new_files,
                report.changed_files,
                report.drawers_added,
                report.transcript_drawers,
            )
        return report

    def run(self, *, interval: float, on_report: Any = None) -> None:
        """Poll forever. `on_report(report)` fires after every pass; the
        caller decides how to render. KeyboardInterrupt exits cleanly."""
        while True:
            report = self.scan_once()
            if on_report is not None:
                on_report(report)
            time.sleep(max(interval, 1.0))
