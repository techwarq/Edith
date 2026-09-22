import json
from types import SimpleNamespace

import pytest

from edith import browse
from edith.google import gmail as google_gmail
from edith.memory import db, job_applications_store as jobs_store, store
from edith.tools import job_applications as job_applications_tool
from edith.tools.registry import ToolRegistry


class FakeModels:
    def __init__(self, text: str):
        self._text = text

    def generate_content(self, model, contents):
        return SimpleNamespace(text=self._text)


class FakeGenaiClient:
    def __init__(self, text: str = ""):
        self.models = FakeModels(text)


def _registry(tmp_path, draft_text: str = ""):
    conn = db.connect(tmp_path / "test.db")
    r = ToolRegistry()
    job_applications_tool.register(r, conn, FakeGenaiClient(draft_text), "fake-model")
    return r, conn


def test_register_seeds_default_job_sources(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("list_job_sources", {})

    assert "jobs.a16z.com" in result
    assert "ycombinator.com/jobs" in result
    assert "sequoiacap.com" in result
    assert "workatastartup" in result


def test_record_job_lead_and_dedup(tmp_path):
    r, conn = _registry(tmp_path)

    first = r.dispatch(
        "record_job_lead",
        {"company": "Acme Inc", "role_title": "Full Stack Engineer", "source": "a16z",
         "source_url": "https://jobs.a16z.com/jobs", "job_posting_url": "https://acme.com/careers/1",
         "company_domain": ""},
    )
    assert "Recorded lead #1" in first

    dup = r.dispatch(
        "record_job_lead",
        {"company": "Acme Inc", "role_title": "", "source": "", "source_url": "",
         "job_posting_url": "https://acme.com/careers/2", "company_domain": ""},
    )
    assert "Already tracked as #1" in dup


def test_check_company_applied(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    result = r.dispatch("check_company_applied", {"company": "Acme Inc", "company_domain": "acme.com"})
    assert "Already in flight: #1" in result

    result2 = r.dispatch("check_company_applied", {"company": "Beta Inc", "company_domain": "beta.com"})
    assert "No existing in-flight application" in result2


def test_draft_job_application_requires_resume(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    result = r.dispatch("draft_job_application", {"application_id": 1, "job_posting_text": "We're hiring"})
    assert result.startswith("ERROR")
    assert "no resume ingested" in result


def test_draft_job_application_success_grounded_and_persists(tmp_path):
    draft = json.dumps({
        "resume_summary": "Full stack engineer with AI platform experience.",
        "subject": "Application: Full Stack Engineer",
        "body": "Hi team, I'd love to join Acme...",
    })
    r, conn = _registry(tmp_path, draft_text=draft)
    jobs_store.save_resume_text(conn, "Sonali Nayak, Full Stack Engineer at Nagent AI...", "resume.pdf")
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "Full Stack Engineer", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    result = r.dispatch("draft_job_application", {"application_id": 1, "job_posting_text": "We're hiring a full stack engineer"})

    assert "Drafted application #1" in result
    assert "fallback tone" in result  # no style sample ingested in this test
    app = jobs_store.get_application(conn, 1)
    assert app["status"] == "drafted"
    assert app["draft_body"] == "Hi team, I'd love to join Acme..."
    assert app["resume_summary"] == "Full stack engineer with AI platform experience."


def test_set_application_channel_validates(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    bad = r.dispatch("set_application_channel", {"application_id": 1, "channel": "carrier_pigeon"})
    assert bad.startswith("ERROR")

    good = r.dispatch("set_application_channel", {"application_id": 1, "channel": "email"})
    assert "channel to email" in good
    assert jobs_store.get_application(conn, 1)["channel"] == "email"


def test_send_job_application_email_queues_when_not_autonomous(tmp_path, monkeypatch):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    def fail_if_called(*a, **k):
        raise AssertionError("must not call the real Gmail executor when autonomous mode is off")
    monkeypatch.setattr(google_gmail, "execute_send_email", fail_if_called)

    result = r.dispatch("send_job_application_email", {
        "application_id": 1, "to": "founder@acme.com", "subject": "Hi", "body": "Hello",
    })

    assert "Queued as action #" in result
    app = jobs_store.get_application(conn, 1)
    assert app["status"] == "queued_for_approval"
    assert app["pending_action_id"] is not None
    pending = store.get_pending_actions(conn)
    assert len(pending) == 1 and pending[0]["tool_name"] == "send_email"


def test_send_job_application_email_sends_directly_when_autonomous(tmp_path, monkeypatch):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})
    r.dispatch("enable_jobs_autonomous_mode", {})

    monkeypatch.setattr(google_gmail, "execute_send_email", lambda creds, args: f"Email sent to {args['to']}.")
    monkeypatch.setattr("edith.google.auth.get_credentials", lambda: object())

    result = r.dispatch("send_job_application_email", {
        "application_id": 1, "to": "founder@acme.com", "subject": "Hi", "body": "Hello",
    })

    assert result == "Email sent to founder@acme.com."
    app = jobs_store.get_application(conn, 1)
    assert app["status"] == "sent"
    assert app["sent_at"] is not None
    assert store.get_pending_actions(conn) == []


def test_send_job_application_email_marks_failed_on_executor_error(tmp_path, monkeypatch):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})
    r.dispatch("enable_jobs_autonomous_mode", {})

    monkeypatch.setattr(google_gmail, "execute_send_email", lambda creds, args: "ERROR: sending email failed: boom")
    monkeypatch.setattr("edith.google.auth.get_credentials", lambda: object())

    r.dispatch("send_job_application_email", {"application_id": 1, "to": "x@acme.com", "subject": "Hi", "body": "Hello"})

    app = jobs_store.get_application(conn, 1)
    assert app["status"] == "failed"
    assert "boom" in app["error"]


def test_submit_job_application_form_queues_when_not_autonomous(tmp_path, monkeypatch):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})

    def fail_if_called(*a, **k):
        raise AssertionError("must not call the real form executor when autonomous mode is off")
    monkeypatch.setattr(browse, "execute_submit_form", fail_if_called)

    result = r.dispatch("submit_job_application_form", {
        "application_id": 1, "url": "https://acme.com/apply", "field_values": {"name": "Sonali"},
    })

    assert "Queued as action #" in result
    assert jobs_store.get_application(conn, 1)["status"] == "queued_for_approval"


def test_submit_job_application_form_submits_directly_when_autonomous(tmp_path, monkeypatch):
    r, conn = _registry(tmp_path)
    r.dispatch("record_job_lead", {"company": "Acme Inc", "role_title": "", "source": "",
                                    "source_url": "", "job_posting_url": "", "company_domain": "acme.com"})
    r.dispatch("enable_jobs_autonomous_mode", {})
    monkeypatch.setattr(browse, "execute_submit_form", lambda auth, args: f"Form submitted at {args['url']}.")

    result = r.dispatch("submit_job_application_form", {
        "application_id": 1, "url": "https://acme.com/apply", "field_values": {"name": "Sonali"},
    })

    assert result == "Form submitted at https://acme.com/apply."
    assert jobs_store.get_application(conn, 1)["status"] == "applied"


def test_enable_disable_autonomous_mode_roundtrip(tmp_path):
    r, conn = _registry(tmp_path)

    assert store.get_fact(conn, job_applications_tool.AUTONOMOUS_KEY) is None
    r.dispatch("enable_jobs_autonomous_mode", {})
    assert store.get_fact(conn, job_applications_tool.AUTONOMOUS_KEY) == "true"
    r.dispatch("disable_jobs_autonomous_mode", {})
    assert store.get_fact(conn, job_applications_tool.AUTONOMOUS_KEY) == "false"


def test_track_untrack_job_source(tmp_path):
    r, conn = _registry(tmp_path)

    r.dispatch("track_job_source", {"url": "https://jobs.testvc-example.com", "note": "TestVC portfolio jobs"})
    listed = r.dispatch("list_job_sources", {})
    assert "jobs.testvc-example.com" in listed

    r.dispatch("untrack_job_source", {"url": "https://jobs.testvc-example.com"})
    listed_after = r.dispatch("list_job_sources", {})
    assert "jobs.testvc-example.com" not in listed_after
