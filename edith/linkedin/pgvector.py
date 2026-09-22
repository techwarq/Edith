"""pgvector memory for LinkedIn Growth Engine.

Mirrors edith/memory/vectors.py but for LinkedIn persona-scoped memory.
Uses Postgres + pgvector if DATABASE_URL is set, else no-ops (same philosophy as vectors.py).

Embedding still via Gemini (gemini-embedding-001, 3072 dim) so we can swap without re-embedding.
"""
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger("edith.linkedin.pgvector")

PGVECTOR_DIM = 3072
PGVECTOR_TABLE = "linkedin_memory"

def _get_db_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip() or os.environ.get("LINKEDIN_DATABASE_URL", "").strip()

def is_enabled() -> bool:
    url = _get_db_url()
    return bool(url) and os.environ.get("PGVECTOR_ENABLED", "true").lower() not in ("0","false","no")

def _connect():
    url = _get_db_url()
    if not url:
        return None
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.warning("pgvector connect failed: %s", e)
        return None

def ensure_pgvector_schema() -> None:
    """Create extension + table if DATABASE_URL present. No-op otherwise."""
    url = _get_db_url()
    if not url:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {PGVECTOR_TABLE} (
                id UUID PRIMARY KEY,
                author_urn TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding vector({PGVECTOR_DIM}),
                pillar TEXT,
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_linkedin_memory_author ON {PGVECTOR_TABLE}(author_urn);")
        # ivfflat index needs some rows first; create lazily
        try:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_linkedin_memory_embedding ON {PGVECTOR_TABLE} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);")
        except Exception as e:
            # ivfflat fails if table empty, ignore
            logger.debug("ivfflat index create deferred: %s", e)
        cur.close()
        conn.close()
        logger.info("pgvector schema ensured")
    except Exception:
        logger.exception("ensure_pgvector_schema failed")

def _embed_gemini(genai_client, text: str) -> Optional[list[float]]:
    try:
        from edith.config import EMBEDDING_MODEL, EMBEDDING_DIM
        resp = genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config={"output_dimensionality": EMBEDDING_DIM},
        )
        return list(resp.embeddings[0].values)
    except Exception:
        logger.exception("gemini embed failed")
        return None

def pg_upsert(genai_client, author_urn: str, kind: str, text: str, pillar: str = "", metadata: dict | None = None) -> bool:
    """Store one memory vector. Returns True if stored."""
    if not is_enabled() or not text.strip():
        return False
    if genai_client is None:
        logger.warning("pg_upsert no genai_client")
        return False
    vec = _embed_gemini(genai_client, text)
    if vec is None:
        return False
    conn = _connect()
    if not conn:
        return False
    try:
        import psycopg2.extras
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {PGVECTOR_TABLE} (id, author_urn, kind, text, embedding, pillar, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), author_urn, kind, text, vec, pillar or None, psycopg2.extras.Json(metadata or {})),
        )
        cur.close()
        conn.close()
        return True
    except Exception:
        logger.exception("pg_upsert failed")
        try:
            conn.close()
        except: pass
        return False

def pg_search(genai_client, author_urn: str, query: str, top_k: int = 5, kind: str | None = None) -> list[dict]:
    """Cosine similarity search filtered by author_urn (+ optional kind)."""
    if not is_enabled() or not query.strip():
        return []
    if genai_client is None:
        return []
    vec = _embed_gemini(genai_client, query)
    if vec is None:
        return []
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=getattr(__import__("psycopg2.extras", fromlist=["RealDictCursor"]), "RealDictCursor"))
        # Use cosine distance: 1 - cosine similarity, so order by distance ASC
        if kind:
            cur.execute(
                f"SELECT id, author_urn, kind, text, pillar, metadata, 1 - (embedding <=> %s::vector) as score FROM {PGVECTOR_TABLE} WHERE author_urn=%s AND kind=%s ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, author_urn, kind, vec, top_k),
            )
        else:
            cur.execute(
                f"SELECT id, author_urn, kind, text, pillar, metadata, 1 - (embedding <=> %s::vector) as score FROM {PGVECTOR_TABLE} WHERE author_urn=%s ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, author_urn, vec, top_k),
            )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            # score is similarity 0-1
            out.append(d)
        return out
    except Exception:
        logger.exception("pg_search failed")
        try:
            conn.close()
        except: pass
        return []

def pg_list_recent(author_urn: str, limit: int = 20) -> list[dict]:
    if not is_enabled():
        return []
    conn = _connect()
    if not conn:
        return []
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"SELECT id, author_urn, kind, text, pillar, created_at FROM {PGVECTOR_TABLE} WHERE author_urn=%s ORDER BY created_at DESC LIMIT %s", (author_urn, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("pg_list_recent failed")
        try: conn.close()
        except: pass
        return []
