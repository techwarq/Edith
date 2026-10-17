"""Tests for edith/memory/storage/qdrant.py — the Qdrant vector index.

Fakes a QdrantClient and an OpenAI-compatible client rather than hitting real services,
mirroring tests/integrations/test_voice.py's fake-client pattern. The "client is None ->
no-op / empty result" behavior is the main thing worth locking down: it's
what lets every call site (the brain, social skills, web_search)
stay unconditional even when Qdrant isn't configured.
"""

from edith.memory.storage import qdrant


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeEmbeddings:
    def __init__(self, vector):
        self.vector = vector
        self.calls = []

    def create(self, model, input):
        self.calls.append(input)
        return _Obj(data=[_Obj(embedding=list(self.vector))])


class FakeLLMClient:
    def __init__(self, vector=(0.1, 0.2, 0.3)):
        self.embeddings = FakeEmbeddings(vector)


class FakeScoredPoint:
    def __init__(self, score, payload, id=1):
        self.id = id
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
        self.payload_indexes = set()

    def collection_exists(self, name):
        return name in self.existing_collections

    def create_collection(self, collection_name, vectors_config):
        self.existing_collections.add(collection_name)

    def create_payload_index(self, collection_name, field_name, field_schema):
        self.payload_indexes.add(field_name)

    def upsert(self, collection_name, points):
        self.upserted.extend(points)

    def query_points(self, collection_name, query, query_filter=None, limit=5):
        return self.query_result


# ---------------------------------------------------------------------------
# None-client no-ops
# ---------------------------------------------------------------------------

def test_ensure_collection_noop_when_client_none():
    qdrant.ensure_collection(None)  # must not raise


def test_upsert_noop_when_client_none():
    qdrant.upsert(None, FakeLLMClient(), "fact", "some text")  # must not raise


def test_semantic_search_returns_empty_when_client_none():
    assert qdrant.search(None, FakeLLMClient(), "query") == []


def test_upsert_noop_for_blank_text():
    client = FakeQdrantClient()
    llm_client = FakeLLMClient()
    qdrant.upsert(client, llm_client, "fact", "   ")
    assert client.upserted == []
    assert llm_client.embeddings.calls == []  # never even embedded


# ---------------------------------------------------------------------------
# ensure_collection
# ---------------------------------------------------------------------------

def test_ensure_collection_creates_when_missing():
    client = FakeQdrantClient()
    qdrant.ensure_collection(client)
    assert qdrant.QDRANT_COLLECTION in client.existing_collections


def test_ensure_collection_idempotent_when_exists():
    client = FakeQdrantClient()
    client.existing_collections.add(qdrant.QDRANT_COLLECTION)
    qdrant.ensure_collection(client)  # must not raise / recreate
    assert qdrant.QDRANT_COLLECTION in client.existing_collections
    assert client.payload_indexes == {"type"}


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------

def test_upsert_embeds_and_stores_point_with_payload():
    client = FakeQdrantClient()
    llm_client = FakeLLMClient(vector=(1.0, 2.0, 3.0))
    qdrant.upsert(client, llm_client, "fact", "likes: coffee", category="preference")

    assert len(client.upserted) == 1
    point = client.upserted[0]
    assert list(point.vector) == [1.0, 2.0, 3.0]
    assert point.payload == {"type": "fact", "text": "likes: coffee", "category": "preference"}
    assert llm_client.embeddings.calls == ["likes: coffee"]


def test_upsert_swallows_qdrant_errors():
    class BrokenClient(FakeQdrantClient):
        def upsert(self, collection_name, points):
            raise RuntimeError("qdrant is down")

    qdrant.upsert(BrokenClient(), FakeLLMClient(), "fact", "some text")  # must not raise


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------

def test_search_returns_scored_payloads():
    client = FakeQdrantClient()
    client.query_result = FakeQueryResult(
        [FakeScoredPoint(0.87, {"type": "fact", "text": "likes coffee"})]
    )
    results = qdrant.search(client, FakeLLMClient(), "beverages")
    assert results == [{"id": 1, "score": 0.87, "type": "fact", "text": "likes coffee"}]


def test_search_swallows_qdrant_errors():
    class BrokenClient(FakeQdrantClient):
        def query_points(self, **kwargs):
            raise RuntimeError("qdrant is down")

    assert qdrant.search(BrokenClient(), FakeLLMClient(), "query") == []
