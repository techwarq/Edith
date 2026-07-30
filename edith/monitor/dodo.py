"""Dodo Payments client for the Situation Monitor's Revenue panel.

Confirmed against docs.dodopayments.com (2026-07-30): base URLs are
https://live.dodopayments.com / https://test.dodopayments.com, auth is a
plain `Authorization: Bearer <key>` header, GET /payments returns
{"items": [...]} with total_amount/currency/status/created_at/refund_status
per payment, and GET /subscriptions returns recurring_pre_tax_amount +
payment_frequency_interval/count per active subscription. Amounts are
integers in minor units (cents), matching the Stripe-shaped convention Dodo's
own docs reference (payment_provider can literally be "stripe").
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.monitor.dodo")

_TIMEOUT_SECONDS = 15
_PAGE_SIZE = 100
_MAX_PAGES = 10  # caps a runaway loop at 1000 payments/subscriptions per call — plenty for a personal dashboard

_MONTHS_PER_CYCLE = {"Day": 1 / 30.44, "Week": 1 / 4.345, "Month": 1.0, "Year": 12.0}


class DodoError(Exception):
    pass


def _get(base_url: str, api_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = requests.get(
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            params={k: v for k, v in params.items() if v not in (None, "")},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        raise DodoError(f"network error calling Dodo Payments: {e}") from e

    if resp.status_code >= 400:
        raise DodoError(f"Dodo Payments API error ({resp.status_code}): {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as e:
        raise DodoError(f"Dodo Payments returned a non-JSON response (status {resp.status_code})") from e


def _paginate(base_url: str, api_key: str, path: str, extra_params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(_MAX_PAGES):
        body = _get(base_url, api_key, path, {**extra_params, "page_size": _PAGE_SIZE, "page_number": page})
        page_items = body.get("items") or []
        items.extend(page_items)
        if len(page_items) < _PAGE_SIZE:
            break
    return items


def _is_refunded(payment: dict[str, Any]) -> bool:
    status = (payment.get("refund_status") or "").lower()
    return status not in ("", "none", "not_refunded", "no_refund")


def _monthly_equivalent(amount: int, interval: Optional[str], count: Optional[int]) -> float:
    months = _MONTHS_PER_CYCLE.get(interval or "Month", 1.0) * max(count or 1, 1)
    return amount / months if months else 0.0


def get_revenue_summary(base_url: str, api_key: str) -> dict[str, Any]:
    """Gross/net revenue (all-time, succeeded payments), MRR (from active
    subscriptions), and the most recent payment. Amounts are returned in
    major currency units (cents / 100), all summed as USD-equivalent numbers
    without FX conversion — fine for a single-currency business; a
    multi-currency one will see amounts blended together as raw numbers."""
    payments = _paginate(base_url, api_key, "/payments", {"status": "succeeded"})
    subscriptions = _paginate(base_url, api_key, "/subscriptions", {"status": "active"})

    gross_cents = sum(p.get("total_amount") or 0 for p in payments)
    refunded_cents = sum(p.get("total_amount") or 0 for p in payments if _is_refunded(p))
    mrr_cents = sum(
        _monthly_equivalent(s.get("recurring_pre_tax_amount") or 0, s.get("payment_frequency_interval"), s.get("payment_frequency_count"))
        for s in subscriptions
    )

    last_payment = None
    if payments:
        latest = max(payments, key=lambda p: p.get("created_at") or "")
        last_payment = {
            "amount_usd": (latest.get("total_amount") or 0) / 100,
            "currency": latest.get("currency"),
            "customer_name": (latest.get("customer") or {}).get("name"),
            "created_at": latest.get("created_at"),
        }

    return {
        "configured": True,
        "gross_revenue_usd": gross_cents / 100,
        "net_revenue_usd": (gross_cents - refunded_cents) / 100,
        "mrr_usd": mrr_cents / 100,
        "active_subscriptions": len(subscriptions),
        "last_payment": last_payment,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
