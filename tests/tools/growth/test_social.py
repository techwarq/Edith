import pytest

from edith.memory import db
from edith.tools.growth import social
from edith.tools.registry import ToolRegistry


class FakeEmbedding:
    def __init__(self, values):
        self.values = values


class FakeEmbedResponse:
    def __init__(self, values):
        self.embeddings = [FakeEmbedding(values)]


class FakeModels:
    def __init__(self, vector=(0.1, 0.2, 0.3)):
        self.vector = vector

    def embed_content(self, model, contents, config=None):
        return FakeEmbedResponse(self.vector)


class FakeGenaiClient:
    def __init__(self):
        self.models = FakeModels()


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

    def upsert(self, collection_name, points):
        self.upserted.extend(points)

    def query_points(self, collection_name, query, query_filter=None, limit=5):
        return self.query_result


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def registry(conn):
    r = ToolRegistry()
    social.register(r, conn, FakeQdrantClient(), FakeGenaiClient())
    return r


def test_save_and_list_social_skill(registry):
    result = registry.dispatch(
        "save_social_skill", {"title": "X writing voice", "content": "Short, punchy, no hashtags.", "platform": "x"}
    )
    assert "X writing voice" in result

    listed = registry.dispatch("list_social_skills", {})
    assert "X writing voice" in listed
    assert "Short, punchy, no hashtags." in listed


def test_list_social_skills_empty(registry):
    assert registry.dispatch("list_social_skills", {}) == "No social media skill files saved yet."


def test_save_social_skill_embeds_with_own_type(conn):
    qdrant_client = FakeQdrantClient()
    r = ToolRegistry()
    social.register(r, conn, qdrant_client, FakeGenaiClient())
    r.dispatch("save_social_skill", {"title": "Niche", "content": "AI agents for solo builders.", "platform": "x"})

    assert len(qdrant_client.upserted) == 1
    point = qdrant_client.upserted[0]
    assert point.payload["type"] == social.SOCIAL_SKILL_CATEGORY
    assert point.payload["text"] == "Niche: AI agents for solo builders."
    assert point.payload["platform"] == "x"


def test_recall_social_skills_returns_scored_matches(registry):
    qdrant_client = FakeQdrantClient()
    qdrant_client.query_result = FakeQueryResult(
        [FakeScoredPoint(0.9, {"type": social.SOCIAL_SKILL_CATEGORY, "text": "Niche: AI agents for solo builders."})]
    )
    r = ToolRegistry()
    social.register(r, None, qdrant_client, FakeGenaiClient())
    result = r.dispatch("recall_social_skills", {"query": "AI agents"})
    assert "AI agents for solo builders" in result
    assert "score=0.90" in result


def test_recall_social_skills_no_matches(registry):
    assert registry.dispatch("recall_social_skills", {"query": "anything"}) == "No matching social skill content found."


def test_recall_social_skills_qdrant_not_configured(conn):
    r = ToolRegistry()
    social.register(r, conn, None, None)
    assert r.dispatch("recall_social_skills", {"query": "anything"}) == "Semantic memory isn't configured yet."
