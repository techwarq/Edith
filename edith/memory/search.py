"""FTS5 query helpers for the search_history tool and the /history REPL command."""

import sqlite3


def _fts_escape(query: str) -> str:
    """Wrap free-text input in quotes per-token so FTS5 special characters
    (AND, OR, NOT, *, -, ") in user input don't break the query syntax."""
    tokens = query.split()
    escaped = ['"{}"'.format(t.replace('"', '""')) for t in tokens]
    return " ".join(escaped) if escaped else '""'


def search_history(
    conn: sqlite3.Connection, query: str, limit: int = 10
) -> list[dict[str, str]]:
    fts_query = _fts_escape(query)
    rows = conn.execute(
        """
        SELECT m.id, m.session_id, m.role, m.content, m.created_at
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [dict(r) for r in rows]
