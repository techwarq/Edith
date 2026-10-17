from edith.memory.storage import sqlite


def test_connect_creates_schema(tmp_path):
    conn = sqlite.connect(tmp_path / "test.db")
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"sessions", "messages", "settings", "memory_notes", "memory_links", "memory_refs"} <= tables
    conn.close()


def test_connect_idempotent(tmp_path):
    path = tmp_path / "test.db"
    conn1 = sqlite.connect(path)
    conn1.close()
    conn2 = sqlite.connect(path)  # should not raise on existing schema
    conn2.close()
