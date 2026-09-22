from types import SimpleNamespace

from edith.tools.growth import hunter
from edith.tools.registry import ToolRegistry


class _FakeSettings:
    def __init__(self, key="test-hunter-key"):
        self.hunter_api_key = key


def _fake_response(json_data, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: json_data, text=str(json_data))


def _registry(monkeypatch, response, settings=None):
    monkeypatch.setattr(hunter.requests, "get", lambda *a, **k: response)
    r = ToolRegistry()
    hunter.register(r, settings or _FakeSettings())
    return r


def test_missing_api_key_returns_error():
    r = ToolRegistry()
    hunter.register(r, _FakeSettings(key=""))

    result = r.dispatch("hunter_domain_search", {"domain": "stripe.com", "limit": 10})

    assert result == "ERROR: Hunter.io isn't configured — HUNTER_API_KEY isn't set."


def test_domain_search_formats_results(monkeypatch):
    response = _fake_response(
        {
            "data": {
                "organization": "Stripe",
                "pattern": "{first}@{domain}",
                "emails": [
                    {"value": "patrick@stripe.com", "first_name": "Patrick", "last_name": "Collison", "position": "CEO", "confidence": 97}
                ],
            }
        }
    )
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_domain_search", {"domain": "stripe.com", "limit": 10})

    assert "Stripe" in result
    assert "patrick@stripe.com" in result
    assert "Patrick Collison" in result
    assert "CEO" in result


def test_domain_search_no_emails(monkeypatch):
    response = _fake_response({"data": {"organization": "Acme", "emails": []}})
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_domain_search", {"domain": "acme.com", "limit": 10})

    assert result == "No emails found for Acme."


def test_email_finder_success(monkeypatch):
    response = _fake_response({"data": {"email": "alexis@reddit.com", "score": 90, "sources": [{}, {}]}})
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_email_finder", {"domain": "reddit.com", "first_name": "Alexis", "last_name": "Ohanian"})

    assert "alexis@reddit.com" in result
    assert "confidence 90" in result


def test_email_finder_not_found(monkeypatch):
    response = _fake_response({"data": {}})
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_email_finder", {"domain": "acme.com", "first_name": "Jane", "last_name": "Doe"})

    assert "No email found" in result


def test_email_verifier(monkeypatch):
    response = _fake_response({"data": {"status": "valid", "score": 95, "result": "deliverable"}})
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_email_verifier", {"email": "patrick@stripe.com"})

    assert "valid" in result
    assert "deliverable" in result


def test_company_enrichment(monkeypatch):
    response = _fake_response(
        {"data": {"name": "Stripe", "category": {"industry": "Fintech"}, "metrics": {"employees": 8000}, "description": "Payments infra."}}
    )
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_company_enrichment", {"domain": "stripe.com"})

    assert "Stripe" in result
    assert "Fintech" in result
    assert "8000 employees" in result
    assert "Payments infra." in result


def test_person_enrichment(monkeypatch):
    response = _fake_response(
        {"data": {"person": {"name": {"fullName": "Patrick Collison"}, "employment": {"title": "CEO", "name": "Stripe"}}}}
    )
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_person_enrichment", {"email": "patrick@stripe.com"})

    assert result == "Patrick Collison — CEO at Stripe"


def test_combined_enrichment(monkeypatch):
    response = _fake_response(
        {
            "data": {
                "person": {"name": {"fullName": "Patrick Collison"}, "employment": {"title": "CEO"}},
                "company": {"name": "Stripe"},
            }
        }
    )
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_combined_enrichment", {"email": "patrick@stripe.com"})

    assert result == "Patrick Collison — CEO at Stripe"


def test_api_error_response_returns_error_string(monkeypatch):
    response = _fake_response({"errors": [{"id": "invalid_domain", "details": "The domain is invalid"}]}, status_code=400)
    r = _registry(monkeypatch, response)

    result = r.dispatch("hunter_domain_search", {"domain": "not-a-domain", "limit": 10})

    assert result.startswith("ERROR:")
    assert "invalid_domain" in result or "The domain is invalid" in result


def test_network_error_returns_error_string(monkeypatch):
    import requests as real_requests

    def _raise(*args, **kwargs):
        raise real_requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(hunter.requests, "get", _raise)
    r = ToolRegistry()
    hunter.register(r, _FakeSettings())

    result = r.dispatch("hunter_email_verifier", {"email": "x@y.com"})

    assert result.startswith("ERROR:")
    assert "network error" in result
