from edith.memory import db


def test_connect_creates_schema(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"sessions", "messages", "user_profile", "meta"} <= tables
    conn.close()


def test_connect_idempotent(tmp_path):
    path = tmp_path / "test.db"
    conn1 = db.connect(path)
    conn1.close()
    conn2 = db.connect(path)  # should not raise on existing schema
    conn2.close()
