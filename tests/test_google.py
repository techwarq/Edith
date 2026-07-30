"""Representative tests for the Google tool modules: one direct-tool test
and one propose/executor test per service, using fake API service objects
(same pattern as test_llm_client.py's FakeClient) — no real network calls.
"""

import pytest

from edith.google import calendar as gcalendar
from edith.google import drive as gdrive
from edith.google import gmail as ggmail
from edith.memory import db, store
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


class FakeExecute:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


# ---------------------------------------------------------------------------
# gmail
# ---------------------------------------------------------------------------

class FakeGmailMessages:
    def __init__(self, list_result=None, get_result=None, send_result=None):
        self.list_result = list_result
        self.get_result = get_result
        self.send_result = send_result
        self.send_calls = []

    def list(self, **kwargs):
        self.list_calls_query = kwargs.get("q")
        return FakeExecute(self.list_result)

    def get(self, **kwargs):
        return FakeExecute(self.get_result)

    def send(self, **kwargs):
        self.send_calls.append(kwargs)
        return FakeExecute(self.send_result)


class FakeGmailService:
    def __init__(self, messages):
        self._messages = messages

    def users(self):
        return self

    def messages(self):
        return self._messages


def test_gmail_search_not_connected(monkeypatch):
    monkeypatch.setattr(ggmail, "get_credentials", lambda: None)
    assert ggmail.gmail_search("test") == ggmail.NOT_CONNECTED


def test_gmail_search_formats_results(monkeypatch):
    messages = FakeGmailMessages(
        list_result={"messages": [{"id": "m1"}]},
        get_result={
            "snippet": "hello world",
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "Subject", "value": "Hi"},
                    {"name": "Date", "value": "today"},
                ]
            },
        },
    )
    monkeypatch.setattr(ggmail, "get_credentials", lambda: object())
    monkeypatch.setattr(ggmail, "_service", lambda creds: FakeGmailService(messages))

    result = ggmail.gmail_search("from:a@b.com")
    assert "m1" in result
    assert "a@b.com" in result
    assert "hello world" in result
    assert messages.list_calls_query == "from:a@b.com"


def test_send_email_propose_queues_pending_action(conn):
    registry = ToolRegistry()
    ggmail.register(registry, conn)
    result = registry.dispatch("send_email", {"to": "x@y.com", "subject": "hi", "body": "hello"})
    assert "Queued as action #" in result
    pending = store.get_pending_actions(conn)
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "send_email"
    assert pending[0]["args"] == {"to": "x@y.com", "subject": "hi", "body": "hello"}


def test_execute_send_email_calls_gmail_send(monkeypatch):
    messages = FakeGmailMessages(send_result={"id": "sent1"})
    monkeypatch.setattr(ggmail, "_service", lambda creds: FakeGmailService(messages))

    result = ggmail.execute_send_email(object(), {"to": "x@y.com", "subject": "hi", "body": "hello"})
    assert "sent" in result.lower()
    assert len(messages.send_calls) == 1
    assert messages.send_calls[0]["userId"] == "me"
    assert "raw" in messages.send_calls[0]["body"]


# ---------------------------------------------------------------------------
# drive
# ---------------------------------------------------------------------------

class FakeDriveFiles:
    def __init__(self, list_result=None, create_result=None):
        self.list_result = list_result
        self.create_result = create_result
        self.create_calls = []

    def list(self, **kwargs):
        self.list_query = kwargs.get("q")
        return FakeExecute(self.list_result)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return FakeExecute(self.create_result)


class FakeDriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def test_drive_search_not_connected(monkeypatch):
    monkeypatch.setattr(gdrive, "get_credentials", lambda: None)
    assert gdrive.drive_search("test") == gdrive.NOT_CONNECTED


def test_drive_search_formats_results(monkeypatch):
    files = FakeDriveFiles(
        list_result={
            "files": [{"id": "f1", "name": "notes.txt", "mimeType": "text/plain", "modifiedTime": "2026-01-01"}]
        }
    )
    monkeypatch.setattr(gdrive, "get_credentials", lambda: object())
    monkeypatch.setattr(gdrive, "_service", lambda creds: FakeDriveService(files))

    result = gdrive.drive_search("notes")
    assert "f1" in result
    assert "notes.txt" in result


def test_create_drive_file_propose_queues_pending_action(conn):
    registry = ToolRegistry()
    gdrive.register(registry, conn)
    result = registry.dispatch("create_drive_file", {"name": "test.txt", "content": "hello"})
    assert "Queued as action #" in result
    pending = store.get_pending_actions(conn)
    assert pending[0]["tool_name"] == "create_drive_file"
    assert pending[0]["args"]["name"] == "test.txt"


def test_execute_create_drive_file_calls_api(monkeypatch):
    files = FakeDriveFiles(create_result={"id": "new1", "name": "test.txt"})
    monkeypatch.setattr(gdrive, "_service", lambda creds: FakeDriveService(files))

    result = gdrive.execute_create_drive_file(object(), {"name": "test.txt", "content": "hello", "mime_type": "text/plain"})
    assert "Created" in result
    assert len(files.create_calls) == 1
    assert files.create_calls[0]["body"]["name"] == "test.txt"


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------

class FakeCalendarEvents:
    def __init__(self, list_result=None, insert_result=None):
        self.list_result = list_result
        self.insert_result = insert_result
        self.insert_calls = []

    def list(self, **kwargs):
        return FakeExecute(self.list_result)

    def insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        return FakeExecute(self.insert_result)


class FakeCalendarService:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


def test_calendar_list_events_not_connected(monkeypatch):
    monkeypatch.setattr(gcalendar, "get_credentials", lambda: None)
    assert gcalendar.calendar_list_events("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z") == gcalendar.NOT_CONNECTED


def test_calendar_list_events_formats_results(monkeypatch):
    events = FakeCalendarEvents(
        list_result={"items": [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-01-01T10:00:00Z"}, "end": {"dateTime": "2026-01-01T10:30:00Z"}}]}
    )
    monkeypatch.setattr(gcalendar, "get_credentials", lambda: object())
    monkeypatch.setattr(gcalendar, "_service", lambda creds: FakeCalendarService(events))

    result = gcalendar.calendar_list_events("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    assert "e1" in result
    assert "Standup" in result


def test_create_calendar_event_propose_queues_pending_action(conn):
    registry = ToolRegistry()
    gcalendar.register(registry, conn)
    result = registry.dispatch(
        "create_calendar_event",
        {"summary": "Meeting", "start_iso": "2026-01-01T10:00:00Z", "end_iso": "2026-01-01T11:00:00Z"},
    )
    assert "Queued as action #" in result
    pending = store.get_pending_actions(conn)
    assert pending[0]["tool_name"] == "create_calendar_event"
    assert pending[0]["args"]["summary"] == "Meeting"


def test_execute_create_calendar_event_calls_api(monkeypatch):
    events = FakeCalendarEvents(insert_result={"id": "new1", "summary": "Meeting"})
    monkeypatch.setattr(gcalendar, "_service", lambda creds: FakeCalendarService(events))

    result = gcalendar.execute_create_calendar_event(
        object(), {"summary": "Meeting", "start_iso": "2026-01-01T10:00:00Z", "end_iso": "2026-01-01T11:00:00Z"}
    )
    assert "Created" in result
    assert len(events.insert_calls) == 1
