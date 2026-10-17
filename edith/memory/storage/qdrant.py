"""Vector index: embed text through OpenRouter, store/query in Qdrant.

One collection holds every vector, told apart by payload `type` ("note" for brain
notes keyed by note id, "social_skill", "search_query", ...). Every function takes
a nullable QdrantClient and degrades (False / [] / no-op) when it's None or Qdrant
errors, so callers never branch on whether vectors are configured.
"""

import logging
import uuid
from typing import Any, Optional, Union

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from edith.config import MEMORY_EMBEDDING_DIM, MEMORY_EMBEDDING_MODEL, QDRANT_COLLECTION

logger = logging.getLogger("edith.memory.qdrant")

PointId = Union[int, str]


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
            vectors_config=qmodels.VectorParams(size=MEMORY_EMBEDDING_DIM, distance=qmodels.Distance.COSINE),
        )
    client.create_payload_index(
        collection_name=QDRANT_COLLECTION, field_name="type", field_schema=qmodels.PayloadSchemaType.KEYWORD
    )


def embed(llm_client: OpenAI, text: str) -> list[float]:
    resp = llm_client.embeddings.create(model=MEMORY_EMBEDDING_MODEL, input=text)
    return list(resp.data[0].embedding)


def upsert(
    client: Optional[QdrantClient],
    llm_client: OpenAI,
    type_: str,
    text: str,
    point_id: Optional[PointId] = None,
    **payload: Any,
) -> bool:
    """Embeds text and writes it under point_id (a fresh uuid if omitted — upserting
    the same id again replaces the vector). Returns whether the write landed."""
    if client is None or not text.strip():
        return False
    try:
        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=point_id if point_id is not None else str(uuid.uuid4()),
                    vector=embed(llm_client, text),
                    payload={"type": type_, "text": text, **payload},
                )
            ],
        )
        return True
    except Exception:  # noqa: BLE001 — vectors are best-effort, never break a write path over them
        logger.exception("Qdrant upsert failed for type=%r", type_)
        return False


def search(
    client: Optional[QdrantClient],
    llm_client: OpenAI,
    query: str,
    top_k: int = 5,
    type_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """[{"id", "score", **payload}] best first."""
    if client is None or not query.strip():
        return []
    try:
        query_filter = None
        if type_filter:
            query_filter = qmodels.Filter(
                must=[qmodels.FieldCondition(key="type", match=qmodels.MatchValue(value=type_filter))]
            )
        result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=embed(llm_client, query),
            query_filter=query_filter,
            limit=top_k,
        )
        return [{"id": p.id, "score": p.score, **p.payload} for p in result.points]
    except Exception:  # noqa: BLE001 — degrade to no results rather than crash the tool loop
        logger.exception("Qdrant search failed for query=%r", query)
        return []


def delete(client: Optional[QdrantClient], point_ids: list[PointId]) -> None:
    if client is None or not point_ids:
        return
    try:
        client.delete(collection_name=QDRANT_COLLECTION, points_selector=qmodels.PointIdsList(points=point_ids))
    except Exception:  # noqa: BLE001
        logger.exception("Qdrant delete failed for %r", point_ids)
