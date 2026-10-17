"""Eddy's brain — long-term memory as a self-organizing network of notes (A-MEM,
arXiv:2502.12110).

remember(): perceive the content (worth keeping? which region? core?), store the
note, index it in Qdrant, then link it to its nearest notes and let those notes
evolve. recall(): Qdrant top-k plus each hit's linked notes. core(): the notes that
are always in Eddy's prompt. Regions are not predefined — they emerge from what
the user talks about, so a fresh install starts with an empty brain.

The rest of Eddy only talks to the Brain class; cortex.py holds the LLM steps and
notes.py the SQLite tables (memory_notes, memory_links, memory_refs).
"""

import logging
import sqlite3
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Iterable, Optional

from edith.config import MEMORY_MODEL
from edith.memory.brain import cortex, notes
from edith.memory.storage import qdrant

logger = logging.getLogger("edith.memory.brain")

NOTE_TYPE = "note"
RECALL_K = 5
EVOLUTION_K = 8
LINKED_PER_HIT = 3

# One worker so notes land in order: evolving note n must see note n-1.
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain")


class Brain:
    def __init__(self, conn: sqlite3.Connection, llm_client: Any = None, model: str = MEMORY_MODEL, qdrant_client: Any = None):
        self.conn = conn
        self.llm_client = llm_client
        self.model = model
        self.qdrant_client = qdrant_client

    @property
    def can_think(self) -> bool:
        return self.llm_client is not None and bool(self.model)

    # -- writing ------------------------------------------------------------

    def remember(
        self,
        content: str,
        source: str = "turn",
        session_id: Optional[str] = None,
        region: Optional[str] = None,
        refs: Iterable[tuple[str, int]] = (),
        at: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Store content as a note if it's worth remembering; returns the note or None.
        `at` backdates it (ISO timestamp) when importing past conversations.
        Raises if the LLM call fails — use remember_later where that must not matter."""
        content = content.strip()
        if not content or not self.can_think:
            return None
        timestamp = at or notes.now(self.conn)
        attrs = cortex.perceive(self.llm_client, self.model, content, timestamp, notes.regions(self.conn), region)
        if attrs is None:
            return None
        note_id = notes.insert(self.conn, content, attrs, source, session_id, timestamp)
        for kind, record_id in refs:
            notes.add_ref(self.conn, note_id, kind, record_id)
        note = notes.get(self.conn, note_id)
        self._index(note)
        try:
            self._evolve(note)
        except Exception:  # noqa: BLE001 — the note is stored; a failed evolution only loses links
            logger.exception("Brain evolution failed for note %s", note_id)
        return notes.get(self.conn, note_id)

    def remember_later(self, content: str, **kwargs: Any) -> Optional[Future]:
        """remember() on the background writer, so it never adds latency to a turn."""
        if not content.strip() or not self.can_think:
            return None
        return self._in_background(lambda brain: brain.remember(content, **kwargs))

    def index_pending(self) -> int:
        """Index notes that have no vector yet (migrated notes, or a past Qdrant outage)."""
        if self.qdrant_client is None:
            return 0
        return sum(self._index(note) for note in notes.unindexed(self.conn))

    def index_pending_later(self) -> Optional[Future]:
        if self.qdrant_client is None or self.llm_client is None:
            return None
        return self._in_background(lambda brain: brain.index_pending())

    def forget(self, note_id: int) -> bool:
        removed = notes.delete(self.conn, note_id)
        if removed:
            qdrant.delete(self.qdrant_client, [note_id])
        return removed

    # -- reading ------------------------------------------------------------

    def core(self) -> list[dict[str, Any]]:
        return notes.core(self.conn)

    def regions(self) -> list[tuple[str, int]]:
        return notes.regions(self.conn)

    def about(self, kind: str, record_id: int) -> list[dict[str, Any]]:
        return notes.for_record(self.conn, kind, record_id)

    def recall(self, query: str, k: int = RECALL_K, include_core: bool = True) -> list[dict[str, Any]]:
        """Top-k notes by meaning (each with "score"), then up to LINKED_PER_HIT linked
        notes per hit (each with "via": (hit id, relation))."""
        if self.llm_client is None:
            return []
        hits = qdrant.search(self.qdrant_client, self.llm_client, query, top_k=k, type_filter=NOTE_TYPE)
        scores = {int(h["id"]): h["score"] for h in hits}
        found = [
            {**n, "score": scores[n["id"]]}
            for n in notes.get_many(self.conn, scores)
            if include_core or not n["core"]
        ]
        seen = {n["id"] for n in found}
        for hit in list(found):
            linked = [l for l in notes.links(self.conn, hit["id"]) if l["id"] not in seen][:LINKED_PER_HIT]
            relation = {l["id"]: l["relation"] for l in linked}
            for n in notes.get_many(self.conn, relation):
                if include_core or not n["core"]:
                    found.append({**n, "via": (hit["id"], relation[n["id"]])})
                    seen.add(n["id"])
        notes.touch(self.conn, seen)
        return found

    # -- internals ----------------------------------------------------------

    def _index(self, note: dict[str, Any]) -> bool:
        ok = qdrant.upsert(
            self.qdrant_client,
            self.llm_client,
            NOTE_TYPE,
            cortex.embedding_text(note),
            point_id=note["id"],
            region=note["region"],
            core=note["core"],
        )
        if ok:
            notes.mark_indexed(self.conn, note["id"])
        return ok

    def _evolve(self, note: dict[str, Any]) -> None:
        hits = qdrant.search(
            self.qdrant_client, self.llm_client, cortex.embedding_text(note), top_k=EVOLUTION_K + 1, type_filter=NOTE_TYPE
        )
        neighbors = notes.get_many(self.conn, [int(h["id"]) for h in hits if int(h["id"]) != note["id"]][:EVOLUTION_K])
        if not neighbors:
            return
        plan = cortex.evolve(self.llm_client, self.model, note, neighbors)

        for other, relation in plan["links"]:
            notes.link(self.conn, note["id"], other, relation)
        if plan["tags"] and plan["tags"] != note["tags"]:
            note["tags"] = plan["tags"]
            notes.update(self.conn, note)
            self._index(note)

        by_id = {n["id"]: n for n in neighbors}
        for update in plan["updates"]:
            neighbor = {**by_id[update["id"]], **update}
            notes.update(self.conn, neighbor, evolved=True)
            self._index(neighbor)

    def _in_background(self, work: Any) -> Future:
        path = _db_path(self.conn)

        def run() -> Any:
            conn = _writer_connection(path) if path else self.conn
            try:
                return work(Brain(conn, self.llm_client, self.model, self.qdrant_client))
            except Exception:  # noqa: BLE001 — background memory work never surfaces into a turn
                logger.exception("Background brain work failed")
                return None
            finally:
                if conn is not self.conn:
                    conn.close()

        return _writer.submit(run)


def _db_path(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2] if row else ""


def _writer_connection(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def format_notes(found: list[dict[str, Any]]) -> str:
    lines = []
    for n in found:
        origin = f"match {n['score']:.2f}" if "score" in n else f"{n['via'][1]} #{n['via'][0]}"
        lines.append(f"#{n['id']} [{n['region']}, {n['created_at'][:10]}, {origin}] {n['context']}")
    return "\n".join(lines)
