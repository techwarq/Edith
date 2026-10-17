import hashlib
import json

import numpy as np
import pytest

from edith.memory.brain import Brain, format_notes, notes
from edith.memory.storage import sqlite


def _bag_of_words(text, dim):
    v = np.zeros(dim)
    for word in text.lower().split():
        word = word.strip(".,:;!?—-()[]'\"")
        if word:
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    return v


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeChat:
    def __init__(self, llm):
        self.completions = self
        self.llm = llm

    def create(self, model, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.llm.prompts.append(prompt)
        handler = self.llm.evolve if "maintain the memory network" in prompt else self.llm.perceive
        result = handler(prompt)
        if isinstance(result, Exception):
            raise result
        return _Obj(choices=[_Obj(message=_Obj(content=json.dumps(result)))])


class FakeEmbeddings:
    def create(self, model, input):
        return _Obj(data=[_Obj(embedding=list(_bag_of_words(input, 64)))])


class FakeLLM:
    """OpenAI-compatible fake: chat.completions for the cortex, embeddings for Qdrant."""

    def __init__(self):
        self.perceive = lambda prompt: {
            "worth_remembering": True, "region": "general", "core": False,
            "context": "ctx", "keywords": ["k1", "k2", "k3"], "tags": ["t1"],
        }
        self.evolve = lambda prompt: {"links": [], "tags": [], "neighbor_updates": []}
        self.prompts = []
        self.chat = FakeChat(self)
        self.embeddings = FakeEmbeddings()


class FakeQdrant:
    def __init__(self):
        self.points = {}

    def upsert(self, collection_name, points):
        for p in points:
            self.points[p.id] = (np.asarray(p.vector), p.payload)

    def query_points(self, collection_name, query, query_filter=None, limit=5):
        wanted = query_filter.must[0].match.value if query_filter else None
        q = np.asarray(query)
        scored = []
        for pid, (vec, payload) in self.points.items():
            if wanted and payload.get("type") != wanted:
                continue
            denom = (np.linalg.norm(q) * np.linalg.norm(vec)) or 1.0
            scored.append(type("P", (), {"id": pid, "score": float(q @ vec / denom), "payload": payload})())
        scored.sort(key=lambda p: -p.score)
        return type("R", (), {"points": scored[:limit]})()

    def delete(self, collection_name, points_selector):
        for pid in points_selector.points:
            self.points.pop(pid, None)


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def vectors():
    return FakeQdrant()


@pytest.fixture
def brain(conn, llm, vectors):
    return Brain(conn, llm, "m", vectors)


def test_remember_files_note_into_region_and_indexes_it(brain, llm, vectors):
    llm.perceive = lambda p: {
        "worth_remembering": True, "region": "preferences", "core": True,
        "context": "Prefers short, direct answers.", "keywords": ["answers", "short"], "tags": ["communication"],
    }

    note = brain.remember("User: keep answers short please", session_id="s1")

    assert note["region"] == "preferences"
    assert note["core"] is True
    assert note["context"] == "Prefers short, direct answers."
    assert vectors.points[note["id"]][1]["type"] == "note"
    assert brain.core() == [note]


def test_small_talk_is_not_stored(brain, llm, conn):
    llm.perceive = lambda p: {"worth_remembering": False}

    assert brain.remember("User: thanks!\nEddy: anytime") is None
    assert notes.recent(conn) == []


def test_perceive_sees_existing_regions_so_it_can_reuse_them(brain, llm):
    llm.perceive = lambda p: {"worth_remembering": True, "region": "business", "context": "c", "keywords": [], "tags": []}
    brain.remember("Launching the paid tier next month")

    brain.remember("Revenue hit 2k MRR")

    perceive_prompts = [p for p in llm.prompts if "maintain the memory network" not in p]
    assert "- business: 1" in perceive_prompts[-1]


def test_fresh_brain_says_it_has_no_regions(brain, llm):
    brain.remember("first memory ever")
    assert "(none yet" in llm.prompts[0]


def test_remember_can_backdate_imported_history(brain, llm):
    note = brain.remember("Went to the LGBTQ support group", at="2023-05-07T13:56:00Z")
    assert note["created_at"] == "2023-05-07T13:56:00Z"
    assert "(2023-05-07T13:56:00Z)" in llm.prompts[0]


def test_explicit_region_overrides_the_brain(brain):
    note = brain.remember("Posts 3x a week on X", region="Content Strategy")
    assert note["region"] == "content strategy"


def test_evolution_links_with_relation_and_retires_superseded_core(brain, llm):
    llm.perceive = lambda p: {"worth_remembering": True, "region": "career", "core": True, "context": "Works at Acme as a PM.", "keywords": [], "tags": []}
    old = brain.remember("I work at Acme as a PM")
    llm.perceive = lambda p: {"worth_remembering": True, "region": "career", "core": True, "context": "Left Acme; now job hunting.", "keywords": [], "tags": []}
    llm.evolve = lambda p: {
        "links": [{"id": old["id"], "relation": "updates"}, {"id": 9999, "relation": "made up"}],
        "tags": ["career", "job-change"],
        "neighbor_updates": [{"id": old["id"], "context": "Used to work at Acme as a PM.", "superseded": True}],
    }

    new = brain.remember("I left Acme, job hunting now")

    assert notes.links(brain.conn, new["id"]) == [{"id": old["id"], "relation": "updates"}]
    assert new["tags"] == ["career", "job-change"]
    evolved = notes.get(brain.conn, old["id"])
    assert evolved["context"] == "Used to work at Acme as a PM."
    assert evolved["core"] is False
    assert [n["id"] for n in brain.core()] == [new["id"]]


def test_malformed_json_is_retried_once(brain, llm):
    calls = {"n": 0}
    real_create = llm.chat.create

    def flaky(model, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Obj(choices=[_Obj(message=_Obj(content='{"region": "health", "core":'))])
        return real_create(model, messages, **kwargs)

    llm.chat.create = flaky
    assert brain.remember("I run 5k three times a week") is not None
    assert calls["n"] == 2


def test_evolution_failure_keeps_the_note(brain, llm):
    brain.remember("one")
    llm.evolve = lambda p: RuntimeError("model down")

    note = brain.remember("two")

    assert note["content"] == "two"


def test_recall_returns_hits_then_linked_notes_with_relation(brain, llm, conn):
    a = brain.remember("kubernetes cluster migration for the startup")
    b = brain.remember("grandmother birthday dinner on sunday")
    notes.link(conn, a["id"], b["id"], "same week")

    found = brain.recall("kubernetes cluster migration", k=1)

    assert [n["id"] for n in found] == [a["id"], b["id"]]
    assert "score" in found[0]
    assert found[1]["via"] == (a["id"], "same week")
    text = format_notes(found)
    assert f"same week #{a['id']}" in text
    retrieved = dict(conn.execute("SELECT id, retrieval_count FROM memory_notes").fetchall())
    assert retrieved == {a["id"]: 1, b["id"]: 1}


def test_recall_can_exclude_core(brain, llm):
    llm.perceive = lambda p: {"worth_remembering": True, "region": "me", "core": True, "context": "c", "keywords": [], "tags": []}
    brain.remember("kubernetes expert")
    assert brain.recall("kubernetes", include_core=False) == []


def test_refs_link_notes_to_records(brain):
    note = brain.remember("finished the first marathon milestone", refs=[("goal", 3), ("milestone", 7)])

    assert notes.refs(brain.conn, note["id"]) == [("goal", 3), ("milestone", 7)]
    assert [n["id"] for n in brain.about("goal", 3)] == [note["id"]]


def test_forget_removes_note_links_refs_and_vector(brain, vectors, conn):
    a = brain.remember("alpha", refs=[("todo", 1)])
    b = brain.remember("beta")
    notes.link(conn, a["id"], b["id"])

    assert brain.forget(a["id"]) is True
    assert notes.links(conn, b["id"]) == []
    assert brain.about("todo", 1) == []
    assert a["id"] not in vectors.points
    assert brain.forget(a["id"]) is False


def test_without_qdrant_notes_still_save_and_index_later(conn, llm, vectors):
    offline = Brain(conn, llm, "m", None)
    note = offline.remember("remember me")
    assert note is not None
    assert offline.recall("remember me") == []

    online = Brain(conn, llm, "m", vectors)
    assert online.index_pending() == 1
    assert note["id"] in vectors.points
    assert online.index_pending() == 0


def test_brain_without_llm_is_inert(conn):
    brain = Brain(conn)
    assert brain.remember("anything") is None
    assert brain.remember_later("anything") is None
    assert brain.recall("anything") == []


def test_remember_later_writes_through_its_own_connection(brain, conn):
    note = brain.remember_later("background memory", source="explicit").result(timeout=5)

    assert notes.get(conn, note["id"])["source"] == "explicit"


def test_remember_later_swallows_failures(brain, llm):
    llm.perceive = lambda p: RuntimeError("boom")
    assert brain.remember_later("x").result(timeout=5) is None


def test_legacy_profile_migrates_into_settings_and_core_notes(tmp_path):
    import sqlite3 as std_sqlite

    path = tmp_path / "old.db"
    old = std_sqlite.connect(path)
    old.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES ('last_session_id', 'abc');"
        "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT, category TEXT, "
        "source_message_id INTEGER, created_at TEXT DEFAULT 'x', updated_at TEXT DEFAULT 'x');"
        "INSERT INTO user_profile (key, value, category) VALUES ('current_role', 'PM', 'identity'), "
        "('https://a.com', 'news', 'tracked_url'), ('niche', 'AI agents', 'content_strategy'), ('pet', 'cat', NULL);"
    )
    old.commit()
    old.close()

    conn = sqlite.connect(path)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "user_profile" not in tables and "meta" not in tables
    assert conn.execute("SELECT value FROM settings WHERE key='last_session_id'").fetchone()[0] == "abc"
    assert conn.execute("SELECT category FROM settings WHERE key='https://a.com'").fetchone()[0] == "tracked_url"
    migrated = {(n["region"], n["context"]) for n in notes.core(conn)}
    assert migrated == {("identity", "current_role: PM"), ("content strategy", "niche: AI agents"), ("about me", "pet: cat")}
    assert (tmp_path / "old.pre-brain.db").exists()
    conn.close()
