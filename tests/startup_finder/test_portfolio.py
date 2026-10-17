import json

import pytest

from edith.memory.records import system
from edith.memory.storage import sqlite
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


@pytest.fixture(autouse=True)
def no_site_fetches(monkeypatch):
    monkeypatch.setattr(sources, "site_blurb", lambda domain: "")
    monkeypatch.setattr(sources, "portfolio_details", lambda url: [])


@pytest.mark.real_portfolio
def test_portfolio_sources_extracts_and_caches(tmp_path, monkeypatch):
    conn = sqlite.connect(tmp_path / "t.db")
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
    assert system.get_setting(conn, "startup_finder_portfolio:Shorooq")


@pytest.mark.real_portfolio
def test_portfolio_failure_is_reported_not_raised(tmp_path, monkeypatch):
    conn = sqlite.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "PORTFOLIO_PAGES", {"Broken": ("https://example.com", None)})

    def boom(url):
        raise RuntimeError("403")

    monkeypatch.setattr(sources, "portfolio_page_text", boom)
    leads, report = finder.portfolio_sources(conn, _Client(ROWS), "m")
    assert leads == [] and "Broken portfolio" in report["errors"]


@pytest.mark.real_portfolio
def test_no_client_and_no_cache_skips(tmp_path, monkeypatch):
    conn = sqlite.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "portfolio_page_text", lambda url: pytest.fail("should not fetch"))
    leads, report = finder.portfolio_sources(conn, None, "m")
    assert leads == []


@pytest.mark.real_portfolio
def test_name_only_page_falls_back_to_detail_pages_and_blurbs(tmp_path, monkeypatch):
    conn = sqlite.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "PORTFOLIO_PAGES", {"Northzone": ("https://example.com", None)})
    monkeypatch.setattr(sources, "portfolio_page_text", lambda url: "page text")
    monkeypatch.setattr(sources, "portfolio_details", lambda url: [
        {"name": "Cusp", "domain": "cuspai.com", "about": "", "country": ""},
        {"name": "Klarna", "domain": "klarna.com", "about": "", "country": ""},
    ])
    monkeypatch.setattr(sources, "site_blurb", lambda d: "Cusp — generative AI for materials" if d == "cuspai.com" else "")
    rows = [{"name": n, "domain": "", "about": "", "country": ""} for n in ("Cusp", "Klarna", "Other")]
    leads, report = finder.portfolio_sources(conn, _Client(rows), "m")
    assert report["sources"] == {"Northzone portfolio": 2}
    assert {l["domain"]: l["description"] for l in leads} == {"cuspai.com": "Cusp — generative AI for materials", "klarna.com": ""}


@pytest.mark.real_portfolio
def test_old_cache_is_upgraded_without_reextracting(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    conn = sqlite.connect(tmp_path / "t.db")
    monkeypatch.setattr(sources, "PORTFOLIO_PAGES", {"Seedcamp": ("https://example.com", None)})
    monkeypatch.setattr(sources, "site_blurb", lambda d: "AI agents for lawyers")
    system.set_setting(conn, "startup_finder_portfolio:Seedcamp", json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(), "companies": [{"name": "Lexa", "domain": "lexa.io", "about": "", "country": ""}]}))
    client = _Client([])
    leads, _ = finder.portfolio_sources(conn, client, "m")
    assert client.calls == 0 and leads[0]["description"] == "AI agents for lawyers"
    assert json.loads(system.get_setting(conn, "startup_finder_portfolio:Seedcamp"))["v"] == finder.PORTFOLIO_VERSION


def test_detail_links_and_host_pick():
    page = '<a href="/portfolio/cusp-ai">x</a><a href="https://fund.com/portfolio/klarna">k</a><a href="/portfolio?page=2">p</a><a href="/about">a</a>'
    assert sources.portfolio_detail_links("https://fund.com/portfolio", page) == [
        "https://fund.com/portfolio/cusp-ai", "https://fund.com/portfolio/klarna"]
    assert sources.pick_company_host("cuspai", ["agency.com", "cuspai.com"], {"agency.com"}) == "cuspai.com"
    assert sources.pick_company_host("klarna", ["agency.com"], {"agency.com"}) is None
    assert sources.pick_company_host("klarna", ["news.com", "blog.com"], set()) is None
    assert sources.pick_company_host("klarna", ["klarna.se"], set()) == "klarna.se"
