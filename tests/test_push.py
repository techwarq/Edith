"""Tests for edith/push.py. Never touches real Firebase — firebase_admin.messaging.send
and edith.push._get_app are monkeypatched with fakes."""

import pytest

from edith import push
from edith.memory import db, store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


class FakeSettings:
    def __init__(self, firebase_service_account_json=""):
        self.firebase_service_account_json = firebase_service_account_json


@pytest.fixture(autouse=True)
def reset_app_singleton(monkeypatch):
    monkeypatch.setattr(push, "_app", None)


def test_no_op_when_firebase_not_configured(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(push.messaging, "send", lambda *a, **kw: calls.append((a, kw)))
    store.save_device_token(conn, "some-token")

    push.send_push_notification(conn, FakeSettings(""), "Title", "Body")

    assert calls == []


def test_no_op_when_no_devices_registered(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(push.messaging, "send", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(push, "_get_app", lambda settings: object())

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body")

    assert calls == []


def test_sends_to_every_registered_token(conn, monkeypatch):
    sent_tokens = []

    def fake_send(message, app=None):
        sent_tokens.append(message.token)

    monkeypatch.setattr(push.messaging, "send", fake_send)
    monkeypatch.setattr(push, "_get_app", lambda settings: object())
    store.save_device_token(conn, "token-a")
    store.save_device_token(conn, "token-b")

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body")

    assert sorted(sent_tokens) == ["token-a", "token-b"]


def test_prunes_stale_token_on_unregistered_error(conn, monkeypatch):
    def fake_send(message, app=None):
        raise push.messaging.UnregisteredError("gone")

    monkeypatch.setattr(push.messaging, "send", fake_send)
    monkeypatch.setattr(push, "_get_app", lambda settings: object())
    store.save_device_token(conn, "stale-token")

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body")

    assert store.list_device_tokens(conn) == []


def test_data_payload_passed_through_when_provided(conn, monkeypatch):
    sent_data = []

    def fake_send(message, app=None):
        sent_data.append(message.data)

    monkeypatch.setattr(push.messaging, "send", fake_send)
    monkeypatch.setattr(push, "_get_app", lambda settings: object())
    store.save_device_token(conn, "token-a")

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body", data={"type": "job_completion"})

    assert sent_data == [{"type": "job_completion"}]


def test_data_payload_defaults_to_none(conn, monkeypatch):
    sent_data = []

    def fake_send(message, app=None):
        sent_data.append(message.data)

    monkeypatch.setattr(push.messaging, "send", fake_send)
    monkeypatch.setattr(push, "_get_app", lambda settings: object())
    store.save_device_token(conn, "token-a")

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body")

    assert sent_data == [None]


def test_other_tokens_still_sent_after_one_fails(conn, monkeypatch):
    sent_tokens = []

    def fake_send(message, app=None):
        if message.token == "bad-token":
            raise push.messaging.UnregisteredError("gone")
        sent_tokens.append(message.token)

    monkeypatch.setattr(push.messaging, "send", fake_send)
    monkeypatch.setattr(push, "_get_app", lambda settings: object())
    store.save_device_token(conn, "bad-token")
    store.save_device_token(conn, "good-token")

    push.send_push_notification(conn, FakeSettings("{}"), "Title", "Body")

    assert sent_tokens == ["good-token"]
    assert store.list_device_tokens(conn) == ["good-token"]
