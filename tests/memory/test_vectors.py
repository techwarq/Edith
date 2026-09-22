"""Tests for edith/memory/vectors.py — the Qdrant-backed semantic memory layer.

Fakes a QdrantClient and a genai.Client rather than hitting real services,
mirroring tests/integrations/test_voice.py's fake-client pattern. The "client is None ->
no-op / empty result" behavior is the main thing worth locking down: it's
what lets every call site (save_fact, agent message persistence, web_search)
stay unconditional even when Qdrant isn't configured.
"""

from edith.memory import vectors


class FakeEmbedding:
    def __init__(self, values):
        self.values = values


class FakeEmbedResponse:
    def __init__(self, values):
        self.embeddings = [FakeEmbedding(values)]


class FakeModels:
    def __init__(self, vector):
        self.vector = vector
        self.calls = []

    def embed_content(self, model, contents, config=None):
        self.calls.append(contents)
        return FakeEmbedResponse(self.vector)


class FakeGenaiClient:
    def __init__(self, vector=(0.1, 0.2, 0.3)):
        self.models = FakeModels(vector)


class FakeScoredPoint:
    def __init__(self, score, payload):
        self.score = score
        self.payload = payload


class FakeQueryResult:
    def __init__(self, points):
        self.points = points


class FakeQdrantClient:
    def __init__(self):
        self.upserted = []
        self.query_result = FakeQueryResult([])
        self.existing_collections = set()

    def collection_exists(self, name):
        return name in self.existing_collections

    def create_collection(self, collection_name, vectors_config):
        self.existing_collections.add(collection_name)

    def upsert(self, collection_name, points):
        self.upserted.extend(points)

    def query_points(self, collection_name, query, query_filter=None, limit=5):
        return self.query_result


# ---------------------------------------------------------------------------
# None-client no-ops
# ---------------------------------------------------------------------------

def test_ensure_collection_noop_when_client_none():
    vectors.ensure_collection(None)  # must not raise


def test_upsert_noop_when_client_none():
    vectors.upsert(None, FakeGenaiClient(), "fact", "some text")  # must not raise


def test_semantic_search_returns_empty_when_client_none():
    assert vectors.semantic_search(None, FakeGenaiClient(), "query") == []


def test_upsert_noop_for_blank_text():
    client = FakeQdrantClient()
    genai_client = FakeGenaiClient()
    vectors.upsert(client, genai_client, "fact", "   ")
    assert client.upserted == []
    assert genai_client.models.calls == []  # never even embedded


# ---------------------------------------------------------------------------
# ensure_collection
# ---------------------------------------------------------------------------

def test_ensure_collection_creates_when_missing():
    client = FakeQdrantClient()
    vectors.ensure_collection(client)
    assert vectors.QDRANT_COLLECTION in client.existing_collections


def test_ensure_collection_idempotent_when_exists():
    client = FakeQdrantClient()
    client.existing_collections.add(vectors.QDRANT_COLLECTION)
    vectors.ensure_collection(client)  # must not raise / recreate
    assert vectors.QDRANT_COLLECTION in client.existing_collections


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------

def test_upsert_embeds_and_stores_point_with_payload():
    client = FakeQdrantClient()
    genai_client = FakeGenaiClient(vector=(1.0, 2.0, 3.0))
    vectors.upsert(client, genai_client, "fact", "likes: coffee", category="preference")

    assert len(client.upserted) == 1
    point = client.upserted[0]
    assert list(point.vector) == [1.0, 2.0, 3.0]
    assert point.payload == {"type": "fact", "text": "likes: coffee", "category": "preference"}
    assert genai_client.models.calls == ["likes: coffee"]


def test_upsert_swallows_qdrant_errors():
    class BrokenClient(FakeQdrantClient):
        def upsert(self, collection_name, points):
            raise RuntimeError("qdrant is down")

    vectors.upsert(BrokenClient(), FakeGenaiClient(), "fact", "some text")  # must not raise


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------

def test_semantic_search_returns_scored_payloads():
    client = FakeQdrantClient()
    client.query_result = FakeQueryResult(
        [FakeScoredPoint(0.87, {"type": "fact", "text": "likes coffee"})]
    )
    results = vectors.semantic_search(client, FakeGenaiClient(), "beverages")
    assert results == [{"score": 0.87, "type": "fact", "text": "likes coffee"}]


def test_semantic_search_swallows_qdrant_errors():
    class BrokenClient(FakeQdrantClient):
        def query_points(self, **kwargs):
            raise RuntimeError("qdrant is down")

    assert vectors.semantic_search(BrokenClient(), FakeGenaiClient(), "query") == []
