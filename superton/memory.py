"""Memory layer — abstraction over MemPalace.

We wrap MemPalace behind a small interface so the rest of SuperTon doesn't
couple tightly to it. If MemPalace's API shifts, only this module changes.

For Phase 0 we ship a minimal in-process facade that uses MemPalace if present
and degrades to a small SQLite + JSON store otherwise — so `superton init`
works even before MemPalace is installed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from superton.config import Config


@dataclass
class Drawer:
    id: str
    text: str
    source: str
    wing: str = "default"
    room: str = "default"
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchHit:
    drawer: Drawer
    score: float


def _hash_id(text: str, source: str) -> str:
    h = hashlib.blake2b(digest_size=8)
    h.update(source.encode())
    h.update(b"\x00")
    h.update(text.encode())
    return h.hexdigest()


class Memory:
    """SQLite-backed drawer store. Vector search is wired in Phase 1.

    This is intentionally minimal — the goal is a working `add` / `list` /
    `search` (lexical) loop today; semantic search swaps in once we wire
    embeddings via the Model layer.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cfg.palace_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cfg.palace_dir / "drawers.sqlite"
        self._db = sqlite3.connect(self.db_path)
        self._db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS drawers (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                wing TEXT NOT NULL DEFAULT 'default',
                room TEXT NOT NULL DEFAULT 'default',
                created_at REAL NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_wing_room ON drawers(wing, room);
            CREATE INDEX IF NOT EXISTS idx_created ON drawers(created_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS drawers_fts USING fts5(
                text, source, wing, room, content='drawers', content_rowid='rowid'
            );
            CREATE TRIGGER IF NOT EXISTS drawers_ai AFTER INSERT ON drawers BEGIN
                INSERT INTO drawers_fts(rowid, text, source, wing, room)
                VALUES (new.rowid, new.text, new.source, new.wing, new.room);
            END;
            CREATE TRIGGER IF NOT EXISTS drawers_ad AFTER DELETE ON drawers BEGIN
                INSERT INTO drawers_fts(drawers_fts, rowid, text, source, wing, room)
                VALUES('delete', old.rowid, old.text, old.source, old.wing, old.room);
            END;
            """
        )
        self._db.commit()

    def add(self, text: str, source: str, *, wing: str = "default", room: str = "default",
            metadata: dict | None = None) -> Drawer:
        d = Drawer(
            id=_hash_id(text, source),
            text=text,
            source=source,
            wing=wing,
            room=room,
            metadata=metadata or {},
        )
        self._db.execute(
            "INSERT OR IGNORE INTO drawers (id, text, source, wing, room, created_at, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (d.id, d.text, d.source, d.wing, d.room, d.created_at, json.dumps(d.metadata)),
        )
        self._db.commit()
        return d

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        rows = self._db.execute(
            "SELECT d.* FROM drawers_fts f JOIN drawers d ON d.rowid = f.rowid"
            " WHERE drawers_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [SearchHit(drawer=self._row_to_drawer(r), score=1.0) for r in rows]

    def get(self, drawer_id: str) -> Drawer | None:
        r = self._db.execute("SELECT * FROM drawers WHERE id = ?", (drawer_id,)).fetchone()
        return self._row_to_drawer(r) if r else None

    def forget(self, drawer_id: str) -> bool:
        cur = self._db.execute("DELETE FROM drawers WHERE id = ?", (drawer_id,))
        self._db.commit()
        return cur.rowcount > 0

    def all(self, *, limit: int = 100) -> list[Drawer]:
        rows = self._db.execute(
            "SELECT * FROM drawers ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_drawer(r) for r in rows]

    def stats(self) -> dict:
        n = self._db.execute("SELECT COUNT(*) AS n FROM drawers").fetchone()["n"]
        wings = self._db.execute(
            "SELECT COUNT(DISTINCT wing) AS n FROM drawers"
        ).fetchone()["n"]
        rooms = self._db.execute(
            "SELECT COUNT(DISTINCT room) AS n FROM drawers"
        ).fetchone()["n"]
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {"drawers": n, "wings": wings, "rooms": rooms, "bytes": size}

    @staticmethod
    def _row_to_drawer(r: sqlite3.Row) -> Drawer:
        return Drawer(
            id=r["id"],
            text=r["text"],
            source=r["source"],
            wing=r["wing"],
            room=r["room"],
            created_at=r["created_at"],
            metadata=json.loads(r["metadata"] or "{}"),
        )

    def close(self) -> None:
        self._db.close()
