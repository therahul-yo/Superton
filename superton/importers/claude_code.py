"""Claude Code session importer.

Reads transcripts from ~/.claude/projects/<project>/<session>.jsonl and
emits one drawer per user/assistant turn into the palace.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from superton.ingest import CHUNK_SIZE, chunk_text
from superton.memory import Memory


def _default_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool_use: {block.get('name', '?')}]")
                elif block.get("type") == "tool_result":
                    inner = block.get("content", "")
                    parts.append(f"[tool_result] {_extract_text(inner)}")
        return "\n".join(p for p in parts if p)
    return ""


class ClaudeCodeImporter:
    name = "claude-code"

    def __init__(self, memory: Memory):
        self.memory = memory

    def discover(self, root: Path | None = None) -> Iterator[Path]:
        root = root or _default_root()
        if not root.exists():
            return
        yield from root.rglob("*.jsonl")

    def import_session(
        self,
        path: Path,
        *,
        wing: str = "claude-code",
        replace: bool = False,
        known_sources: set[str] | None = None,
    ) -> int:
        room = path.parent.name
        source = f"claude-code:{path.name}"
        if replace:
            self.memory.forget_source(source)
        else:
            existing = known_sources if known_sources is not None else {
                row["source"] for row in self.memory.sources(limit=10_000)
            }
            if source in existing:
                # Source already indexed — skip rather than silently double up.
                return 0
        count = 0
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") or rec
                role = msg.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _extract_text(msg.get("content", ""))
                if not text.strip():
                    continue
                body = f"[{role}] {text}"
                # Long turns (large tool_result blobs, pasted files) embed
                # poorly as one drawer — chunk so each piece stays focused.
                pieces = [body] if len(body) <= CHUNK_SIZE else list(chunk_text(body))
                for piece in pieces:
                    self.memory.add(
                        text=piece,
                        source=f"claude-code:{path.name}",
                        wing=wing,
                        room=room,
                        metadata={"role": role, "session": path.stem},
                    )
                    count += 1
        return count

    def import_all(
        self, root: Path | None = None, *, replace: bool = False
    ) -> tuple[int, int]:
        sessions = 0
        drawers = 0
        known = {row["source"] for row in self.memory.sources(limit=10_000)}
        for session in self.discover(root):
            n = self.import_session(session, replace=replace, known_sources=known)
            if n:
                sessions += 1
                drawers += n
                known.add(f"claude-code:{session.name}")
        return sessions, drawers
