import json

import pytest

from edith.memory import db, store
from edith.startup_finder import finder, sources


class _Client:
    def __init__(self, rows):
        self.calls = 0
        rows_json = json.dumps(rows)
        outer = self

        class Models:
            def generate_content(self, model, contents):
                outer.calls += 1
                return type("R", (), {"text": rows_json})()

        self.models = Models()


ROWS = [
    {"name": "Wexler", "domain": "wexler.ai", "about": "AI agents for litigation document analysis", "country": "United Kingdom"},
    {"name": "Sandstorm", "domain": "sandstorm.ae", "about": "AI video ads", "country": ""},
    {"name": "NoSite", "domain": "", "about": "x", "country": ""},
    {"name": "Lever Hosted", "domain": "jobs.lever.co", "about": "x", "country": ""},
]


@pytest.mark.real_portfolio
def test_portfolio_sources_extracts_and_caches(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "PORTFOLIO_PAGES", {"Shorooq": ("https://example.com", "middle_east")})
    monkeypatch.setattr(sources, "portfolio_page_text", lambda url: "page text")
    client = _Client(ROWS)

    leads, report = finder.portfolio_sources(conn, client, "m")
    assert report["sources"] == {"Shorooq portfolio": 2}
    by_name = {l["company"]: l for l in leads}
    assert by_name["Wexler"]["region"] == "europe"
    assert by_name["Sandstorm"]["region"] == "middle_east"
    assert by_name["Wexler"]["dedup_key"] == "co:wexler.ai"

    finder.portfolio_sources(conn, client, "m")
    assert client.calls == 1
    assert store.get_meta(conn, "startup_finder_portfolio:Shorooq")


@pytest.mark.real_portfolio
def test_portfolio_failure_is_reported_not_raised(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "PORTFOLIO_PAGES", {"Broken": ("https://example.com", None)})

    def boom(url):
        raise RuntimeError("403")

    monkeypatch.setattr(sources, "portfolio_page_text", boom)
    leads, report = finder.portfolio_sources(conn, _Client(ROWS), "m")
    assert leads == [] and "Broken portfolio" in report["errors"]


@pytest.mark.real_portfolio
def test_no_client_and_no_cache_skips(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "portfolio_page_text", lambda url: pytest.fail("should not fetch"))
    leads, report = finder.portfolio_sources(conn, None, "m")
    assert leads == []
