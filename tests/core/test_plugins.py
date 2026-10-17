import asyncio
from types import SimpleNamespace

import pytest

from edith import plugins
from edith.memory.storage import sqlite
from edith.temporal import client as temporal_client


def test_no_plugins_by_default(monkeypatch):
    monkeypatch.delenv("EDITH_PLUGINS", raising=False)
    assert plugins.enabled_names() == []
    assert plugins.enabled() == []


def test_only_installed_plugins_are_enabled(monkeypatch):
    monkeypatch.setenv("EDITH_PLUGINS", " career , nope ")
    assert plugins.enabled_names() == ["career"]


def test_plugin_tables_exist_even_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("EDITH_PLUGINS", raising=False)
    conn = sqlite.connect(tmp_path / "t.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"job_applications", "startup_leads", "outreach_prospects"} <= tables


def test_temporal_needs_only_an_address(monkeypatch):
    seen = {}

    async def fake_connect(address, namespace, api_key):
        seen.update(address=address, namespace=namespace, api_key=api_key)

    monkeypatch.setattr(temporal_client.Client, "connect", fake_connect)
    settings = SimpleNamespace(temporal_address="temporal:7233", temporal_namespace="", temporal_api_key="")
    asyncio.run(temporal_client.get_client(settings))
    assert seen == {"address": "temporal:7233", "namespace": "default", "api_key": None}

    with pytest.raises(temporal_client.TemporalNotConfigured):
        asyncio.run(temporal_client.get_client(SimpleNamespace(temporal_address="")))
