import pytest

from edith.startup_finder import finder


@pytest.fixture(autouse=True)
def no_portfolio_network(request, monkeypatch):
    if "real_portfolio" in request.keywords:
        return
    monkeypatch.setattr(finder, "portfolio_sources", lambda conn, genai_client, model: ([], {"sources": {}, "errors": {}}))


@pytest.fixture(autouse=True)
def no_site_scrape(request, monkeypatch):
    from edith.startup_finder import site_emails
    if "real_site_emails" in request.keywords:
        return
    monkeypatch.setattr(site_emails, "find", lambda domain, max_pages=0: [])
