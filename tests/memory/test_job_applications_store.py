import pytest

from edith.memory import db, job_applications_store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_create_and_get(conn):
    app_id = job_applications_store.create_lead(
        conn, "Acme Inc", company_domain="acme.com", role_title="Full Stack Engineer",
        source="a16z", source_url="https://a16z.com/portfolio/", job_posting_url="https://acme.com/jobs/1",
    )
    app = job_applications_store.get_application(conn, app_id)
    assert app["company"] == "Acme Inc"
    assert app["company_domain"] == "acme.com"
    assert app["status"] == "discovered"
    assert app["channel"] == "undetermined"


def test_find_existing_application_only_matches_in_flight_statuses(conn):
    app_id = job_applications_store.create_lead(conn, "Acme Inc", company_domain="acme.com")
    # a freshly discovered lead already counts as "in flight" — prevents immediately
    # re-recording the same company as a second lead
    found = job_applications_store.find_existing_application(conn, "acme.com")
    assert found is not None and found["id"] == app_id

    job_applications_store.update_application(conn, app_id, status="drafted")
    found = job_applications_store.find_existing_application(conn, "acme.com")
    assert found is not None and found["id"] == app_id

    job_applications_store.update_application(conn, app_id, status="failed")
    assert job_applications_store.find_existing_application(conn, "acme.com") is None


def test_update_application_rejects_unknown_field(conn):
    app_id = job_applications_store.create_lead(conn, "Acme Inc")
    with pytest.raises(ValueError):
        job_applications_store.update_application(conn, app_id, company="Different Co")


def test_list_applications_filters_by_status(conn):
    a = job_applications_store.create_lead(conn, "Acme Inc")
    b = job_applications_store.create_lead(conn, "Beta Inc")
    job_applications_store.update_application(conn, b, status="sent")

    assert len(job_applications_store.list_applications(conn)) == 2
    assert len(job_applications_store.list_applications(conn, status="sent")) == 1
    assert job_applications_store.list_applications(conn, status="discovered")[0]["id"] == a


def test_count_sent_today(conn):
    a = job_applications_store.create_lead(conn, "Acme Inc")
    assert job_applications_store.count_sent_today(conn) == 0
    job_applications_store.update_application(
        conn, a, status="sent", sent_at="2020-01-01T09:00:00.000Z"
    )
    assert job_applications_store.count_sent_today(conn) == 0  # a stale date shouldn't count as "today"
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    job_applications_store.update_application(conn, a, sent_at=today)
    assert job_applications_store.count_sent_today(conn) == 1


def test_resume_text_roundtrip(conn):
    assert job_applications_store.get_resume_text(conn) is None
    job_applications_store.save_resume_text(conn, "Sonali Nayak, Full Stack Engineer...", "resume.pdf")
    assert job_applications_store.get_resume_text(conn) == "Sonali Nayak, Full Stack Engineer..."
    job_applications_store.save_resume_text(conn, "updated text", "resume.pdf")
    assert job_applications_store.get_resume_text(conn) == "updated text"


def test_style_sample_roundtrip_independent_of_resume(conn):
    job_applications_store.save_resume_text(conn, "resume text", "resume.pdf")
    assert job_applications_store.get_style_sample(conn) is None
    job_applications_store.save_style_sample(conn, "Hi, excited to apply...", "email.txt")
    assert job_applications_store.get_style_sample(conn) == "Hi, excited to apply..."
    # saving the style sample must not clobber the previously saved resume text
    assert job_applications_store.get_resume_text(conn) == "resume text"


def test_style_sample_before_resume(conn):
    job_applications_store.save_style_sample(conn, "sample", "email.txt")
    assert job_applications_store.get_style_sample(conn) == "sample"
    job_applications_store.save_resume_text(conn, "resume text", "resume.pdf")
    assert job_applications_store.get_resume_text(conn) == "resume text"
    assert job_applications_store.get_style_sample(conn) == "sample"
