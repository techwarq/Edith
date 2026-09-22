import pytest

from edith.monitor import dodo


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_get_revenue_summary_computes_gross_net_mrr(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        if url.endswith("/payments"):
            if params["page_number"] == 0:
                return _FakeResponse(
                    200,
                    {
                        "items": [
                            {"total_amount": 10000, "currency": "USD", "created_at": "2026-07-01T00:00:00Z", "refund_status": None, "customer": {"name": "Alice"}},
                            {"total_amount": 5000, "currency": "USD", "created_at": "2026-07-15T00:00:00Z", "refund_status": "succeeded", "customer": {"name": "Bob"}},
                        ]
                    },
                )
            return _FakeResponse(200, {"items": []})
        if url.endswith("/subscriptions"):
            if params["page_number"] == 0:
                return _FakeResponse(
                    200,
                    {"items": [{"recurring_pre_tax_amount": 2000, "payment_frequency_interval": "Month", "payment_frequency_count": 1}]},
                )
            return _FakeResponse(200, {"items": []})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(dodo.requests, "get", fake_get)

    result = dodo.get_revenue_summary("https://live.dodopayments.com", "test-key")

    assert result["configured"] is True
    assert result["gross_revenue_usd"] == 150.0
    assert result["net_revenue_usd"] == 100.0  # 150 gross - 50 refunded
    assert result["mrr_usd"] == 20.0
    assert result["active_subscriptions"] == 1
    assert result["last_payment"]["customer_name"] == "Bob"
    assert result["last_payment"]["amount_usd"] == 50.0


def test_paginate_stops_on_short_page(monkeypatch):
    pages = [{"items": [{"total_amount": 100}] * 100}, {"items": [{"total_amount": 50}]}]
    call_count = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        page = pages[call_count["n"]]
        call_count["n"] += 1
        return _FakeResponse(200, page)

    monkeypatch.setattr(dodo.requests, "get", fake_get)
    items = dodo._paginate("https://live.dodopayments.com", "key", "/payments", {"status": "succeeded"})
    assert len(items) == 101
    assert call_count["n"] == 2


def test_get_raises_dodo_error_on_http_error(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(401, "unauthorized")

    monkeypatch.setattr(dodo.requests, "get", fake_get)
    with pytest.raises(dodo.DodoError):
        dodo._get("https://live.dodopayments.com", "bad-key", "/payments", {})


def test_monthly_equivalent_yearly():
    assert dodo._monthly_equivalent(1200, "Year", 1) == 100.0


def test_is_refunded():
    assert dodo._is_refunded({"refund_status": "succeeded"}) is True
    assert dodo._is_refunded({"refund_status": None}) is False
    assert dodo._is_refunded({"refund_status": "not_refunded"}) is False
