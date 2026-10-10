from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.memory import db
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import api, email_draft

LEAD = {
    "id": 1, "kind": "founder", "company": "Visoid", "domain": "visoid.com",
    "founders": [
        {"name": "Kari Holm", "title": "Head of Sales", "email": "kari@visoid.com"},
        {"name": "Dennis Berg", "title": "Co-founder & CTO", "email": "dennis@visoid.com", "linkedin": "https://linkedin.com/in/dennis"},
    ],
}


def test_compose_matches_template_and_picks_founder():
    d = email_draft.compose(LEAD, "Solving one hard problem for architects.", "nagent, ailens, bogus")
    assert d["to"] == "dennis@visoid.com" and d["subject"] == "engineer who builds creative ai - sonali nayak"
    assert d["body"] == (
        "hello dennis,\n\n" + email_draft.INTRO + "\n\n"
        "i came across visoid and like that you're solving one hard problem for architects.\n\n"
        "- " + email_draft.PROJECTS["nagent"] + "\n- " + email_draft.PROJECTS["ailens"] + "\n- portfolio: techwarq.space\n\n"
        "open to relocating if you can sponsor a visa. would love to work with you, how can we do it?\n\n"
        "best,\nsonali nayak"
    )


def test_compose_defaults_projects_when_none_picked():
    body = email_draft.compose(LEAD, "x", "")["body"]
    assert "- " + email_draft.PROJECTS["edith"] + "\n- " + email_draft.PROJECTS["ailens"] in body
    assert email_draft.project_keys("edith, ai-lens, nagent, edith") == ["edith", "ailens", "nagent"]


def test_compose_role_intro_and_no_like():
    d = email_draft.compose({**LEAD, "kind": "role", "role_title": "AI Engineer", "founders": []}, "")
    assert "i just applied for the ai engineer role at visoid." in d["body"]
    assert "like that" not in d["body"] and d["to"] is None and d["body"].startswith("hello,")
    with_like = email_draft.compose({**LEAD, "kind": "role", "role_title": "AI Engineer"}, "shipping agents")["body"]
    assert "i just applied for the ai engineer role at visoid and like that you're shipping agents." in with_like


def test_to_html_links_known_urls_only():
    out = email_draft.to_html("- live on nagent.ai: script in\n- evals (github.com/techwarq/ai-lens)\n- lip-sync & <b>")
    assert '<a href="https://nagent.ai">nagent.ai</a>:' in out
    assert '<a href="https://github.com/techwarq/ai-lens">github.com/techwarq/ai-lens</a>)' in out
    assert "&lt;b&gt;" in out and "lip-sync" in out


def _client(tmp_path, monkeypatch, resume):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO startup_leads (dedup_key, kind, company, domain) VALUES ('co:visoid.com', 'founder', 'Visoid', 'visoid.com')")
    leads_store.save_draft(conn, 1, "dennis@visoid.com", "subj", "hello dennis,\n\nportfolio: techwarq.space")
    sent = []
    monkeypatch.setattr(api.google_auth, "get_credentials", lambda: object())
    monkeypatch.setattr(api.gmail, "send_rich_email", lambda creds, to, subject, text, html, att, name: sent.append((to, subject, text, html, att, name)) or f"Email sent to {to}.")
    settings = SimpleNamespace(hunter_api_key="", crustdata_api_key="", gemini_grounding_model="m", resume_pdf=str(resume))
    app = FastAPI()
    app.include_router(api.build_router(conn, settings, None, "t"))
    return TestClient(app), conn, sent


def test_send_uses_edits_attaches_resume_and_blocks_resend(tmp_path, monkeypatch):
    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4")
    client, conn, sent = _client(tmp_path, monkeypatch, resume)

    r = client.post("/api/startup-finder/leads/1/send", json={"token": "t", "body": "hello dennis, edited"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "contacted" and r.json()["sent_at"]
    to, subject, text, html, att, name = sent[0]
    assert (to, subject, text) == ("dennis@visoid.com", "subj", "hello dennis, edited")
    assert att == resume and name == email_draft.ATTACHMENT_NAME

    again = client.post("/api/startup-finder/leads/1/send", json={"token": "t"})
    assert again.status_code == 409 and len(sent) == 1


def test_send_rejects_bad_recipient_and_missing_resume(tmp_path, monkeypatch):
    client, conn, sent = _client(tmp_path, monkeypatch, tmp_path / "missing.pdf")
    assert client.post("/api/startup-finder/leads/1/send", json={"token": "t", "to": "nope"}).status_code == 400
    r = client.post("/api/startup-finder/leads/1/send", json={"token": "t"})
    assert r.status_code == 400 and "resume not found" in r.json()["error"]
    assert not sent


def test_short_name_and_bullet_voice():
    assert email_draft.short_name("Simplifai AS") == "Simplifai"
    assert email_draft.short_name("Acme, Inc.") == "Acme"
    assert email_draft.short_name("Aster") == "Aster"
    d = email_draft.compose({"kind": "founder", "company": "Simplifai AS", "founders": []}, "")
    assert "i came across simplifai and wanted to reach out directly." in d["body"]


def test_subject_focus_per_company():
    assert email_draft.compose(LEAD, "x", focus="AI agents")["subject"] == "engineer who builds ai agents - sonali nayak"
    assert email_draft.subject_for("engineer who builds llm apps.") == "engineer who builds llm apps - sonali nayak"
    assert email_draft.subject_for("a really long rambling focus that goes on and on") == "engineer who builds creative ai - sonali nayak"


def test_send_to_several_people_personalizes_each_and_skips_already_sent(tmp_path, monkeypatch):
    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4")
    client, conn, sent = _client(tmp_path, monkeypatch, resume)
    leads_store.mark_delivered(conn, 1, founders=[
        {"name": "Dennis Berg", "email": "dennis@visoid.com"}, {"name": "Kari Holm", "email": "kari@visoid.com"},
        {"name": "Ola Nord", "email": "ola@visoid.com"},
    ])

    r = client.post("/api/startup-finder/leads/1/send", json={"token": "t", "to": ["dennis@visoid.com", "kari@visoid.com"]})
    assert r.status_code == 200, r.text
    assert [(s[0], s[2].split("\n")[0]) for s in sent] == [("dennis@visoid.com", "hello dennis,"), ("kari@visoid.com", "hello kari,")]
    assert r.json()["sent_to"] == ["dennis@visoid.com", "kari@visoid.com"]

    r = client.post("/api/startup-finder/leads/1/send", json={"token": "t", "to": ["kari@visoid.com", "ola@visoid.com"]})
    assert r.status_code == 200
    assert [s[0] for s in sent[2:]] == ["ola@visoid.com"] and sent[2][2].startswith("hello ola,")
    assert r.json()["sent_to"] == ["dennis@visoid.com", "kari@visoid.com", "ola@visoid.com"]


def test_for_recipient_swaps_greeting_only():
    assert email_draft.for_recipient("hello dennis,\n\nhello there", "Kari Holm") == "hello kari,\n\nhello there"
    assert email_draft.for_recipient("hello,\n\nx", "Ola Nord") == "hello ola,\n\nx"
    assert email_draft.for_recipient("hello dennis,\n\nx", None) == "hello dennis,\n\nx"


def test_portfolio_link_gets_utm_tags_only_on_own_site():
    out = email_draft.to_html("- live on nagent.ai\n- portfolio: techwarq.space", campaign="factiverse", content="vinay")
    assert ('href="https://techwarq.space/?utm_source=email&amp;utm_medium=cold_email&amp;utm_campaign=factiverse'
            '&amp;utm_content=vinay">techwarq.space</a>') in out
    assert 'href="https://nagent.ai">nagent.ai</a>' in out
    assert 'href="https://techwarq.space">' in email_draft.to_html("portfolio: techwarq.space")
    assert email_draft.utm_slug("Simplifai AS") == "simplifai" and email_draft.utm_slug("Let's Enhance") == "let-s-enhance"


def test_send_tags_each_recipient(tmp_path, monkeypatch):
    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4")
    client, conn, sent = _client(tmp_path, monkeypatch, resume)
    leads_store.mark_delivered(conn, 1, founders=[{"name": "Dennis Berg", "email": "dennis@visoid.com"}])
    assert client.post("/api/startup-finder/leads/1/send", json={"token": "t"}).status_code == 200
    html = sent[0][3]
    assert "utm_campaign=visoid&amp;utm_content=dennis" in html
