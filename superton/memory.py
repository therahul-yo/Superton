"""Memory layer — SQLite metadata plus optional MemPalace semantic search.

SQLite remains the source of truth for listing, deletion, and exact fallback
search. When enabled, drawers are also mirrored into a local MemPalace/Chroma
collection so natural-language questions can retrieve semantically relevant
source text instead of relying only on exact keyword matches.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

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
    """Drawer store with semantic retrieval and SQLite fallback."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cfg.palace_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cfg.palace_dir / "drawers.sqlite"
        self._db = sqlite3.connect(self.db_path)
        self._db.row_factory = sqlite3.Row
        self._semantic_collection: Any | None = None
        self._semantic_error: str | None = None
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
        self._index_semantic(d)
        return d

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        semantic_hits = self._search_semantic(query, limit=limit)
        if semantic_hits:
            return semantic_hits
        return self._search_sqlite(query, limit=limit)

    def _search_sqlite(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        try:
            rows = self._db.execute(
                "SELECT d.* FROM drawers_fts f JOIN drawers d ON d.rowid = f.rowid"
                " WHERE drawers_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            tokens = [t for t in query.split() if len(t) > 1]
            if not tokens:
                return []
            clauses = " AND ".join(["text LIKE ?"] * len(tokens))
            rows = self._db.execute(
                f"SELECT * FROM drawers WHERE {clauses} ORDER BY created_at DESC LIMIT ?",
                (*[f"%{t}%" for t in tokens], limit),
            ).fetchall()
        return [SearchHit(drawer=self._row_to_drawer(r), score=1.0) for r in rows]

    def get(self, drawer_id: str) -> Drawer | None:
        r = self._db.execute("SELECT * FROM drawers WHERE id = ?", (drawer_id,)).fetchone()
        return self._row_to_drawer(r) if r else None

    def forget(self, drawer_id: str) -> bool:
        cur = self._db.execute("DELETE FROM drawers WHERE id = ?", (drawer_id,))
        self._db.commit()
        self._delete_semantic(drawer_id)
        return cur.rowcount > 0

    def reindex_semantic(self, *, batch_size: int = 64) -> int:
        """Mirror every SQLite drawer into the semantic index.

        SQLite is the durable source of truth. This lets users rebuild the
        MemPalace/Chroma sidecar after changing machines, clearing caches, or
        switching semantic backends.
        """
        if not self._semantic_enabled():
            return 0
        col = self._semantic(create=True)
        if col is None:
            return 0

        rows = self.all(limit=1_000_000)
        total = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            ids = [d.id for d in batch]
            documents = [d.text for d in batch]
            metadatas = [
                {
                    "id": d.id,
                    "source": d.source,
                    "source_file": d.source,
                    "wing": d.wing,
                    "room": d.room,
                    "created_at": d.created_at,
                    "metadata_json": json.dumps(d.metadata),
                }
                for d in batch
            ]
            try:
                col.upsert(documents=documents, ids=ids, metadatas=metadatas)
                total += len(batch)
                self._semantic_error = None
            except Exception as e:
                self._semantic_error = str(e)
                break
        return total

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
        return {
            "drawers": n,
            "wings": wings,
            "rooms": rooms,
            "bytes": size,
            "backend": self.cfg.memory_backend,
            "semantic_enabled": self._semantic_enabled(),
            "semantic_error": self._semantic_error,
        }

    def _semantic_enabled(self) -> bool:
        return self.cfg.memory_backend in {"hybrid", "semantic", "mempalace"}

    def _semantic(self, *, create: bool = True):
        if not self._semantic_enabled():
            return None
        if self._semantic_collection is not None:
            return self._semantic_collection
        try:
            from mempalace.palace import get_collection

            self.cfg.semantic_dir.mkdir(parents=True, exist_ok=True)
            self._semantic_collection = get_collection(
                str(self.cfg.semantic_dir),
                collection_name=self.cfg.semantic_collection,
                create=create,
            )
            self._semantic_error = None
            return self._semantic_collection
        except Exception as e:
            self._semantic_error = str(e)
            return None

    def _index_semantic(self, drawer: Drawer) -> None:
        col = self._semantic(create=True)
        if col is None:
            return
        metadata = {
            "id": drawer.id,
            "source": drawer.source,
            "source_file": drawer.source,
            "wing": drawer.wing,
            "room": drawer.room,
            "created_at": drawer.created_at,
            "metadata_json": json.dumps(drawer.metadata),
        }
        try:
            col.upsert(documents=[drawer.text], ids=[drawer.id], metadatas=[metadata])
            self._semantic_error = None
        except Exception as e:
            self._semantic_error = str(e)

    def _search_semantic(self, query: str, *, limit: int) -> list[SearchHit]:
        col = self._semantic(create=False)
        if col is None:
            return []
        try:
            results = col.query(
                query_texts=[query],
                n_results=limit,
                include=["documents", "metadatas", "distances"],
            )
            ids = (getattr(results, "ids", None) or [[]])[0]
            docs = (getattr(results, "documents", None) or [[]])[0]
            metas = (getattr(results, "metadatas", None) or [[]])[0]
            distances = (getattr(results, "distances", None) or [[]])[0]
        except Exception as e:
            self._semantic_error = str(e)
            return []

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for drawer_id, doc, meta, distance in zip(ids, docs, metas, distances, strict=False):
            if not drawer_id or drawer_id in seen:
                continue
            seen.add(drawer_id)
            drawer = self.get(drawer_id)
            if drawer is None:
                drawer = self._semantic_row_to_drawer(drawer_id, doc or "", meta or {})
            try:
                score = max(0.0, 1.0 - float(distance))
            except (TypeError, ValueError):
                score = 0.0
            hits.append(SearchHit(drawer=drawer, score=score))
        self._semantic_error = None
        return hits

    def _delete_semantic(self, drawer_id: str) -> None:
        col = self._semantic(create=False)
        if col is None:
            return
        try:
            col.delete(ids=[drawer_id])
            self._semantic_error = None
        except Exception as e:
            self._semantic_error = str(e)

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

    @staticmethod
    def _semantic_row_to_drawer(drawer_id: str, text: str, metadata: dict) -> Drawer:
        raw_metadata = metadata.get("metadata_json", "{}")
        try:
            parsed_metadata = json.loads(raw_metadata)
        except (TypeError, json.JSONDecodeError):
            parsed_metadata = {}
        return Drawer(
            id=drawer_id,
            text=text,
            source=metadata.get("source") or metadata.get("source_file") or "semantic",
            wing=metadata.get("wing", "default"),
            room=metadata.get("room", "default"),
            created_at=float(metadata.get("created_at", time.time())),
            metadata=parsed_metadata,
        )

    def close(self) -> None:
        if self._semantic_collection is not None:
            close = getattr(self._semantic_collection, "close", None)
            if callable(close):
                close()
        self._db.close()
