"""Generic importer for agent thread stores with mixed JSON/JSONL/text files."""

from __future__ import annotations

import json
from pathlib import Path

from superton.ingest import chunk_text
from superton.memory import Memory

READABLE = {".json", ".jsonl", ".md", ".txt", ".log"}


def _extract_json_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_extract_json_text(v) for v in value)
    if isinstance(value, dict):
        parts = []
        for key in ("text", "content", "message", "prompt", "response", "answer"):
            if key in value:
                parts.append(_extract_json_text(value[key]))
        return "\n".join(p for p in parts if p)
    return ""


class GenericThreadImporter:
    def __init__(self, memory: Memory, name: str, default_root: Path):
        self.memory = memory
        self.name = name
        self.default_root = default_root

    def discover(self, root: Path | None = None) -> list[Path]:
        root = root or self.default_root
        if not root.exists():
            return []
        if root.is_file():
            return [root]
        return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in READABLE]

    def _read(self, path: Path) -> str:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".jsonl":
            parts = []
            for line in raw.splitlines():
                try:
                    parts.append(_extract_json_text(json.loads(line)))
                except json.JSONDecodeError:
                    continue
            return "\n\n".join(p for p in parts if p.strip())
        if path.suffix.lower() == ".json":
            try:
                return _extract_json_text(json.loads(raw))
            except json.JSONDecodeError:
                return raw
        return raw

    def import_all(self, root: Path | None = None) -> tuple[int, int]:
        files = 0
        drawers = 0
        for path in self.discover(root):
            text = self._read(path).strip()
            if not text:
                continue
            files += 1
            for chunk in chunk_text(text):
                self.memory.add(
                    text=chunk,
                    source=f"{self.name}:{path.name}",
                    wing=self.name,
                    room=path.parent.name or "threads",
                    metadata={"path": str(path)},
                )
                drawers += 1
        return files, drawers
