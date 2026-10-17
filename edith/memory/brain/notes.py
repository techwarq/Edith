"""SQLite persistence for brain notes, note<->note links, and note<->record refs."""

import json
import sqlite3
from typing import Any, Iterable, Optional

_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "content": row["content"],
        "context": row["context"],
        "keywords": json.loads(row["keywords"]),
        "tags": json.loads(row["tags"]),
        "region": row["region"],
        "core": bool(row["core"]),
        "source": row["source"],
        "created_at": row["created_at"],
    }


def now(conn: sqlite3.Connection) -> str:
    return conn.execute(f"SELECT {_NOW} AS t").fetchone()["t"]


def insert(
    conn: sqlite3.Connection,
    content: str,
    attrs: dict[str, Any],
    source: str,
    session_id: Optional[str],
    created_at: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO memory_notes (content, context, keywords, tags, region, core, source, session_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            content,
            attrs["context"],
            json.dumps(attrs["keywords"]),
            json.dumps(attrs["tags"]),
            attrs["region"],
            int(attrs["core"]),
            source,
            session_id,
            created_at,
        ),
    )
    return cur.lastrowid


def update(conn: sqlite3.Connection, note: dict[str, Any], evolved: bool = False) -> None:
    conn.execute(
        f"UPDATE memory_notes SET context = ?, keywords = ?, tags = ?, core = ?, indexed = 0, "
        f"evolution_count = evolution_count + ?, updated_at = {_NOW} WHERE id = ?",
        (note["context"], json.dumps(note["keywords"]), json.dumps(note["tags"]), int(note["core"]), int(evolved), note["id"]),
    )


def mark_indexed(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute("UPDATE memory_notes SET indexed = 1 WHERE id = ?", (note_id,))


def get(conn: sqlite3.Connection, note_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM memory_notes WHERE id = ?", (note_id,)).fetchone()
    return _row(row) if row else None


def get_many(conn: sqlite3.Connection, ids: Iterable[int]) -> list[dict[str, Any]]:
    ids = list(ids)
    if not ids:
        return []
    rows = conn.execute(f"SELECT * FROM memory_notes WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    by_id = {r["id"]: _row(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete(conn: sqlite3.Connection, note_id: int) -> bool:
    return conn.execute("DELETE FROM memory_notes WHERE id = ?", (note_id,)).rowcount > 0


def core(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM memory_notes WHERE core = 1 ORDER BY region, id").fetchall()
    return [_row(r) for r in rows]


def in_region(conn: sqlite3.Connection, region: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM memory_notes WHERE region = ? ORDER BY id", (region,)).fetchall()
    return [_row(r) for r in rows]


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM memory_notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def unindexed(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM memory_notes WHERE indexed = 0 ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def regions(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT region, COUNT(*) AS n FROM memory_notes GROUP BY region ORDER BY n DESC, region"
    ).fetchall()
    return [(r["region"], r["n"]) for r in rows]


def touch(conn: sqlite3.Connection, ids: Iterable[int]) -> None:
    ids = list(ids)
    if ids:
        conn.execute(
            f"UPDATE memory_notes SET retrieval_count = retrieval_count + 1, last_accessed = {_NOW} "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )


# ---------------------------------------------------------------------------
# links (note <-> note) and refs (note <-> structured record)
# ---------------------------------------------------------------------------

def link(conn: sqlite3.Connection, a: int, b: int, relation: str = "related") -> None:
    if a == b:
        return
    lo, hi = sorted((a, b))
    conn.execute(
        "INSERT INTO memory_links (note_a, note_b, relation) VALUES (?, ?, ?) "
        "ON CONFLICT(note_a, note_b) DO UPDATE SET relation = excluded.relation",
        (lo, hi, relation or "related"),
    )


def links(conn: sqlite3.Connection, note_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT note_b AS id, relation FROM memory_links WHERE note_a = ? "
        "UNION ALL SELECT note_a, relation FROM memory_links WHERE note_b = ? ORDER BY id",
        (note_id, note_id),
    ).fetchall()
    return [dict(r) for r in rows]


def add_ref(conn: sqlite3.Connection, note_id: int, kind: str, record_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO memory_refs (note_id, kind, record_id) VALUES (?, ?, ?)", (note_id, kind, record_id)
    )


def refs(conn: sqlite3.Connection, note_id: int) -> list[tuple[str, int]]:
    rows = conn.execute("SELECT kind, record_id FROM memory_refs WHERE note_id = ? ORDER BY kind, record_id", (note_id,))
    return [(r["kind"], r["record_id"]) for r in rows]


def for_record(conn: sqlite3.Connection, kind: str, record_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT n.* FROM memory_notes n JOIN memory_refs r ON r.note_id = n.id "
        "WHERE r.kind = ? AND r.record_id = ? ORDER BY n.id",
        (kind, record_id),
    ).fetchall()
    return [_row(r) for r in rows]
