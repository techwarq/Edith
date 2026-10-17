from edith.plugins.career import store as career
from edith.memory.storage import sqlite
from edith.plugins.career.startup_finder import visa


def _lead(**kw):
    return {"id": 1, "kind": "founder", "company": "Acme", "domain": "acme.ai", **kw}


def test_name_key_strips_legal_suffixes():
    assert visa.name_key("PORTERS LIMITED") == visa.name_key("Porters") == "porters"
    assert visa.name_key("Polar Analytics B.V.") == "polaranalytics"


def test_country_from_iso_hq_tld_and_locations():
    assert visa.country_of(_lead(company_info={"country": "GBR"})) == "united kingdom"
    assert visa.country_of(_lead(company_info={"hq": "Oslo, Oslo, Norway"})) == "norway"
    assert visa.country_of(_lead(domain="paldo.no")) == "norway"
    assert visa.country_of(_lead(locations=["Amsterdam", "Remote"])) == "netherlands"
    assert visa.country_of(_lead(locations=["London, UK", "Berlin, Germany"])) is None


def test_register_hit_means_sponsor(monkeypatch):
    monkeypatch.setattr(visa, "_registers", {"uk": {"porters": "PORTERS LIMITED"}, "nl": {"polaranalytics": "Polar Analytics B.V."}})
    assert visa.classify(_lead(company="Porters", company_info={"country": "GBR"})) == ("sponsor", "on UK sponsor register as PORTERS LIMITED")
    assert visa.classify(_lead(company="Polar", domain="polaranalytics.co", company_info={"hq": "Amsterdam, Netherlands"}))[0] == "sponsor"
    assert visa.classify(_lead(company="Other", company_info={"country": "GBR"})) == ("unlikely", "United Kingdom, not on the sponsor register")


def test_missing_register_is_unknown_not_unlikely(monkeypatch):
    monkeypatch.setattr(visa, "_registers", {"uk": None, "nl": None})
    assert visa.classify(_lead(company_info={"country": "GBR"}))[0] == "unknown"


def test_germany_text_and_remote_signals():
    assert visa.classify(_lead(company_info={"country": "DEU"}))[0] == "sponsor"
    assert visa.classify(_lead(description="We offer visa sponsorship and relocation support"))[0] == "sponsor"
    assert visa.classify(_lead(description="no visa sponsorship. remote-first team", domain="acme.no"))[0] == "remote"
    assert visa.classify(_lead(kind="role", eligibility="yes", domain="acme.pl"))[0] == "remote"
    assert visa.classify(_lead(domain="acme.no")) == ("unlikely", "Norway, no sponsorship or remote signal")
    assert visa.classify(_lead()) == ("unknown", "country unknown")


def test_backfill_and_pick_new_filter(tmp_path):
    conn = sqlite.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO startup_leads (dedup_key, kind, company, domain, score) VALUES ('a', 'founder', 'A', 'a.de', 5)")
    conn.execute("INSERT INTO startup_leads (dedup_key, kind, company, domain, score) VALUES ('b', 'founder', 'B', 'b.no', 5)")
    conn.execute("INSERT INTO startup_leads (dedup_key, kind, company, domain, score) VALUES ('c', 'founder', 'C', 'c.ai', 5)")
    assert visa.backfill(conn) == 3 and visa.backfill(conn) == 0
    assert [l["company"] for l in career.pick_new_leads(conn, 10, visa=["sponsor", "remote"])] == ["A"]
    assert [l["company"] for l in career.list_leads(conn, visa="unlikely")] == ["B"]
