"""Semantic memory: embed text with Gemini, store/query in Qdrant.

Optional layer, not required for Edith to run — every function here takes a
nullable QdrantClient and no-ops (upsert) or returns [] (search) when it's
None, so the rest of the codebase never needs to branch on "is Qdrant
configured" itself. Complements, not replaces, the SQLite FTS5 keyword
search in edith/memory/search.py: FTS is exact-match recall ("find the
message where I said X"), this is meaning-based recall ("what have I said
that's *related* to X, even in different words").
"""

import logging
import uuid
from typing import Optional

from google import genai
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from edith.config import EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_COLLECTION

logger = logging.getLogger("edith.memory.vectors")

MemoryType = str  # "fact" | "message" | "search_query" | "document" | "reflection"


def make_qdrant_client(url: str, api_key: str) -> Optional[QdrantClient]:
    if not url or not api_key:
        return None
    return QdrantClient(url=url, api_key=api_key)


def ensure_collection(client: Optional[QdrantClient]) -> None:
    if client is None:
        return
    if not client.collection_exists(QDRANT_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=qmodels.VectorParams(size=EMBEDDING_DIM, distance=qmodels.Distance.COSINE),
        )


def embed(genai_client: genai.Client, text: str) -> list[float]:
    resp = genai_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config={"output_dimensionality": EMBEDDING_DIM},
    )
    return list(resp.embeddings[0].values)


def upsert(
    client: Optional[QdrantClient],
    genai_client: genai.Client,
    type_: MemoryType,
    text: str,
    **metadata: str,
) -> None:
    """metadata is arbitrary payload (source, session_id, etc.) — stored
    alongside type_/text/created_at so semantic_search results carry context."""
    if client is None or not text.strip():
        return
    try:
        vector = embed(genai_client, text)
        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"type": type_, "text": text, **metadata},
                )
            ],
        )
    except Exception:  # noqa: BLE001 — vector memory is best-effort, never break a write path over it
        logger.exception("Qdrant upsert failed for type=%r", type_)


def semantic_search(
    client: Optional[QdrantClient],
    genai_client: genai.Client,
    query: str,
    top_k: int = 5,
    type_filter: Optional[MemoryType] = None,
) -> list[dict]:
    if client is None:
        return []
    try:
        vector = embed(genai_client, query)
        query_filter = None
        if type_filter:
            query_filter = qmodels.Filter(must=[qmodels.FieldCondition(key="type", match=qmodels.MatchValue(value=type_filter))])
        result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=top_k,
        )
        return [{"score": p.score, **p.payload} for p in result.points]
    except Exception:  # noqa: BLE001 — degrade to no results rather than crash the tool loop
        logger.exception("Qdrant semantic_search failed for query=%r", query)
        return []
