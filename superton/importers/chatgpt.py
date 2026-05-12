"""ChatGPT export importer.

Supports the official data export shape where conversations live in
``conversations.json`` and each conversation has a ``mapping`` of message nodes.
"""

from __future__ import annotations

import json
from pathlib import Path

from superton.memory import Memory


def _message_text(content: dict) -> str:
    parts = content.get("parts", [])
    if isinstance(parts, list):
        return "\n".join(str(p) for p in parts if p)
    return str(parts or "")


class ChatGPTImporter:
    name = "chatgpt"

    def __init__(self, memory: Memory):
        self.memory = memory

    def _export_file(self, root: Path) -> Path:
        if root.is_file():
            return root
        return root / "conversations.json"

    def import_all(self, root: Path, *, replace: bool = False) -> tuple[int, int]:
        path = self._export_file(root)
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        conversations = 0
        drawers = 0
        known = {row["source"] for row in self.memory.sources(limit=10_000)}
        for convo in data:
            title = convo.get("title") or "conversation"
            source = f"chatgpt:{title}"
            if replace:
                self.memory.forget_source(source)
            elif source in known:
                # Already imported — skip to avoid doubling the palace.
                continue
            mapping = convo.get("mapping") or {}
            added = 0
            for node in mapping.values():
                msg = (node or {}).get("message") or {}
                role = ((msg.get("author") or {}).get("role")) or ""
                if role not in {"user", "assistant"}:
                    continue
                text = _message_text(msg.get("content") or {})
                if not text.strip():
                    continue
                self.memory.add(
                    text=f"[{role}] {text}",
                    source=source,
                    wing="chatgpt",
                    room=title[:80],
                    metadata={"role": role, "conversation": title},
                )
                added += 1
            if added:
                conversations += 1
                drawers += added
                known.add(source)
        return conversations, drawers
