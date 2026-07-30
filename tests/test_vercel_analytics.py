import pytest

from edith.monitor import vercel_analytics


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_extract_count_from_scalar():
    assert vercel_analytics._extract_count(42) == 42


def test_extract_count_from_known_field():
    assert vercel_analytics._extract_count({"count": 123, "other": "x"}) == 123


def test_extract_count_from_single_numeric_leaf():
    assert vercel_analytics._extract_count({"weird_field_name": 77}) == 77


def test_extract_count_returns_none_when_ambiguous():
    assert vercel_analytics._extract_count({"a": 1, "b": 2}) is None


def test_extract_count_from_list_of_rows():
    assert vercel_analytics._extract_count([{"count": 10}, {"count": 5}]) == 15


def test_get_pageview_summary_success(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert "projectId" in params
        return _FakeResponse(200, {"data": {"count": 555}})

    monkeypatch.setattr(vercel_analytics.requests, "get", fake_get)
    result = vercel_analytics.get_pageview_summary("token", "proj-123", days=7)
    assert result == {
        "configured": True,
        "pageviews": 555,
        "days": 7,
        "fetched_at": result["fetched_at"],
    }


def test_get_pageview_summary_raises_on_http_error(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(403, "forbidden")

    monkeypatch.setattr(vercel_analytics.requests, "get", fake_get)
    with pytest.raises(vercel_analytics.VercelAnalyticsError):
        vercel_analytics.get_pageview_summary("token", "proj-123")


def test_get_pageview_summary_raises_when_count_unparseable(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(200, {"data": {"a": 1, "b": 2}})

    monkeypatch.setattr(vercel_analytics.requests, "get", fake_get)
    with pytest.raises(vercel_analytics.VercelAnalyticsError):
        vercel_analytics.get_pageview_summary("token", "proj-123")
