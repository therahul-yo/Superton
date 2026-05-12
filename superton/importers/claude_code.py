"""Claude Code session importer.

Reads transcripts from ~/.claude/projects/<project>/<session>.jsonl and
emits one drawer per user/assistant turn into the palace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from superton.memory import Drawer, Memory


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

    def import_session(self, path: Path, *, wing: str = "claude-code") -> int:
        room = path.parent.name
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
                self.memory.add(
                    text=f"[{role}] {text}",
                    source=f"claude-code:{path.name}",
                    wing=wing,
                    room=room,
                    metadata={"role": role, "session": path.stem},
                )
                count += 1
        return count

    def import_all(self, root: Path | None = None) -> tuple[int, int]:
        sessions = 0
        drawers = 0
        for session in self.discover(root):
            n = self.import_session(session)
            if n:
                sessions += 1
                drawers += n
        return sessions, drawers
