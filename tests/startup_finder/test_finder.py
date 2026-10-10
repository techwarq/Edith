from datetime import datetime, timezone

from edith.memory import db, store
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import finder


def _raw():
    return [
        {"kind": "role", "dedup_key": "getro:1", "company": "Clipster", "domain": "clipster.ai", "fund": "Antler", "source": "getro",
         "role_title": "AI Engineer", "locations": ["Remote"], "region": "europe", "description": "AI video for creators", "team_size": 10},
        {"kind": "role", "dedup_key": "getro:2", "company": "Clipster", "domain": "clipster.ai", "fund": "Antler", "source": "getro",
         "role_title": "Backend Engineer", "locations": ["Remote"], "region": "europe", "description": "AI video for creators", "team_size": 10},
        {"kind": "founder", "dedup_key": "co:vox.ai", "company": "Vox", "domain": "vox.ai", "fund": "Index", "source": "getro",
         "region": "europe", "description": "AI audio dubbing", "team_size": 5, "active_jobs": 2},
        {"kind": "role", "dedup_key": "getro:3", "company": "Ledger", "domain": "ledger.com", "fund": "GV", "source": "consider",
         "role_title": "Account Executive", "locations": ["Remote"], "region": "us", "description": "fintech"},
        {"kind": "role", "dedup_key": "hn:9", "company": "Tiny", "fund": "HN", "source": "hn", "_parts": ["Tiny", "Founding Engineer", "REMOTE (Worldwide)"],
         "locations": ["REMOTE (Worldwide)"], "region": "global", "description": "AI agents", "job_text": "Tiny | Founding Engineer | REMOTE (Worldwide)"},
    ]


def _patch_crawl(monkeypatch, rows):
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([dict(r) for r in rows], {"sources": {}, "errors": {}}))


def test_find_returns_requested_count_one_per_company_and_never_repeats(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())

    first = finder.find(conn, count=2)
    assert first["returned"] == 2
    companies = [l["company"] for l in first["leads"]]
    assert len(set(companies)) == 2

    second = finder.find(conn, count=5)
    assert not {l["id"] for l in first["leads"]} & {l["id"] for l in second["leads"]}
    assert all(l["company"] != "Ledger" for l in first["leads"] + second["leads"])


def test_hn_title_extracted(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    out = finder.find(conn, count=10)
    hn = [l for l in out["leads"] if l["source"] == "hn"]
    assert hn and hn[0]["role_title"] == "Founding Engineer"


def test_kind_filter(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    out = finder.find(conn, count=10, kind="founder")
    assert [l["company"] for l in out["leads"]] == ["Vox"]


def test_skips_domains_already_applied(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO job_applications (company, company_domain) VALUES ('Clipster', 'clipster.ai')")
    _patch_crawl(monkeypatch, _raw())
    out = finder.find(conn, count=10)
    assert "Clipster" not in [l["company"] for l in out["leads"]]


def test_uses_cached_crawl_when_fresh(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    calls = []
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: calls.append(1) or ([dict(r) for r in _raw()], {"sources": {}, "errors": {}}))
    finder.find(conn, count=1)
    store.set_meta(conn, finder.LAST_CRAWL_KEY, datetime.now(timezone.utc).isoformat())
    leads_store.upsert_leads(conn, [{"dedup_key": f"x:{i}", "kind": "founder", "company": f"C{i}", "score": 1} for i in range(10)])
    finder.find(conn, count=1)
    assert len(calls) == 1


def test_refresh_prunes_leads_that_no_longer_qualify(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    finder.refresh(conn)
    before = leads_store.count_new(conn)
    _patch_crawl(monkeypatch, [r for r in _raw() if r["dedup_key"] != "co:vox.ai"])
    report = finder.refresh(conn)
    assert report["pruned"] == 1
    assert leads_store.count_new(conn) == before - 1


class FakeModels:
    def __init__(self, bad_companies=(), us_companies=(), non_ai=()):
        self.bad = set(bad_companies)
        self.us = set(us_companies)
        self.non_ai = set(non_ai)

    def generate_content(self, model, contents):
        import json, re
        if "You screen job leads" in contents:
            items = json.loads(contents[contents.rindex("\n\n") + 2:])
            out = {str(i["id"]): {"fit": 2 if i["company"] in self.bad else 8, "hq": "us" if i["company"] in self.us else "europe", "funded": "yes",
                                   "ai": "no" if i["company"] in self.non_ai else "yes", "why": "test"} for i in items}
            return type("R", (), {"text": json.dumps(out)})()
        ids = re.findall(r'"id": (\d+)', contents)
        return type("R", (), {"text": json.dumps({i: {"like": f"building thing {i}", "projects": "edith,ailens", "focus": "ai agents"} for i in ids})})()


class FakeClient:
    def __init__(self, bad_companies=(), us_companies=(), non_ai=()):
        self.models = FakeModels(bad_companies, us_companies, non_ai)


def _no_fetch(monkeypatch):
    from edith.startup_finder import sources
    monkeypatch.setattr(sources, "fetch_job_text", lambda url: "")


def test_pitches_attached(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    _no_fetch(monkeypatch)
    out = finder.find(conn, count=2, genai_client=FakeClient(), model="m")
    assert out["returned"] == 2
    assert all(l["pitch"].startswith("i like that you're building thing") for l in out["leads"])
    stored = leads_store.get_lead(conn, out["leads"][0]["id"])
    assert stored["status"] == "delivered" and stored["pitch"]
    assert stored["reasons"][0].startswith("fit 8/10")
    assert stored["draft_subject"] == "engineer who builds ai agents - sonali nayak"
    assert f"like that you're building thing {stored['id']}." in stored["draft_body"]
    assert stored["draft_body"].endswith("best,\nsonali nayak")


def test_non_ai_companies_are_skipped(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    _no_fetch(monkeypatch)
    out = finder.find(conn, count=3, genai_client=FakeClient(non_ai={"Vox"}), model="m")
    assert "Vox" not in [l["company"] for l in out["leads"]]


def test_team_size_window(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    _no_fetch(monkeypatch)
    out = finder.find(conn, count=5, genai_client=FakeClient(), model="m", min_team=8, max_team=40)
    assert [l["company"] for l in out["leads"]] == ["Clipster"]


def test_poor_fit_roles_are_skipped_and_replaced(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    _no_fetch(monkeypatch)
    out = finder.find(conn, count=3, genai_client=FakeClient(bad_companies={"Clipster"}), model="m")
    companies = [l["company"] for l in out["leads"]]
    assert "Clipster" not in companies
    assert len(companies) == 2
    skipped = leads_store.list_leads(conn, status="skipped")
    assert {l["company"] for l in skipped} == {"Clipster"}


def test_unresolved_region_resolved_by_judge(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, _raw())
    _no_fetch(monkeypatch)
    out = finder.find(conn, count=5, genai_client=FakeClient(us_companies={"Tiny"}), model="m")
    assert "Tiny" not in [l["company"] for l in out["leads"]]
    assert all(l["region"] in ("europe", "middle_east") for l in out["leads"])


def test_us_leads_never_stored(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    rows = _raw() + [{"kind": "founder", "dedup_key": "co:us.ai", "company": "USCo", "domain": "us.ai", "region": "us",
                      "description": "AI video", "team_size": 5}]
    _patch_crawl(monkeypatch, rows)
    finder.refresh(conn)
    assert "USCo" not in [l["company"] for l in leads_store.list_leads(conn, limit=100)]


def test_location_and_team_filters(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    rows = _raw() + [
        {"kind": "founder", "dedup_key": "co:fjord.no", "company": "Fjord AI", "domain": "fjord.no", "region": "europe",
         "locations": [], "description": "AI video for creators", "team_size": 5, "founded": 2025},
        {"kind": "founder", "dedup_key": "co:oslo.ai", "company": "Oslo Agents", "domain": "oslo.ai", "region": "europe",
         "locations": ["Oslo, Norway"], "description": "AI agents", "team_size": 120},
    ]
    _patch_crawl(monkeypatch, rows)
    out = finder.find(conn, count=10, location="Norway")
    assert {l["company"] for l in out["leads"]} == {"Fjord AI", "Oslo Agents"}
    assert any("founded 2025" in r for r in out["leads"][0]["reasons"] + out["leads"][-1]["reasons"])


def test_max_team_filter(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    rows = [
        {"kind": "founder", "dedup_key": "co:a.no", "company": "Tiny", "domain": "a.no", "region": "europe", "locations": ["Norway"], "description": "AI video", "team_size": 5},
        {"kind": "founder", "dedup_key": "co:b.no", "company": "Mid", "domain": "b.no", "region": "europe", "locations": ["Norway"], "description": "AI video", "team_size": 120},
    ]
    _patch_crawl(monkeypatch, rows)
    out = finder.find(conn, count=10, location="norway", max_team=50)
    assert [l["company"] for l in out["leads"]] == ["Tiny"]


def test_unfunded_hub_companies_dropped(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    rows = [
        {"kind": "founder", "dedup_key": "co:boot.no", "company": "Boot", "domain": "boot.no", "source": "thehub", "region": "europe",
         "locations": ["Norway"], "description": "AI video", "team_size": 5, "funded": False, "funding": "bootstrapping"},
        {"kind": "founder", "dedup_key": "co:seed.no", "company": "Seeded", "domain": "seed.no", "source": "thehub", "region": "europe",
         "locations": ["Norway"], "description": "AI video", "team_size": 5, "funded": True, "funding": "seed"},
        {"kind": "founder", "dedup_key": "co:vc.no", "company": "Backed", "domain": "vc.no", "source": "getro", "fund": "Antler",
         "region": "europe", "locations": ["Norway"], "description": "AI video", "team_size": 5},
    ]
    _patch_crawl(monkeypatch, rows)
    out = finder.find(conn, count=10, location="norway")
    by = {l["company"]: l for l in out["leads"]}
    assert set(by) == {"Seeded", "Backed"}
    assert "seed-funded" in by["Seeded"]["reasons"]
    assert "Antler-backed" in by["Backed"]["reasons"]


def test_hn_lead_needs_judge_funding_confirmation(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    _patch_crawl(monkeypatch, [r for r in _raw() if r["source"] == "hn"])
    _no_fetch(monkeypatch)

    class NotFunded(FakeModels):
        def generate_content(self, model, contents):
            import json
            if "You screen job leads" in contents:
                items = json.loads(contents[contents.rindex("\n\n") + 2:])
                return type("R", (), {"text": json.dumps({str(i["id"]): {"fit": 9, "hq": "europe", "funded": "unknown", "why": "x"} for i in items})})()
            return super().generate_content(model, contents)

    client = FakeClient()
    client.models = NotFunded()
    out = finder.find(conn, count=5, genai_client=client, model="m")
    assert out["returned"] == 0


def test_multi_country_location_filter(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    rows = [{"kind": "founder", "dedup_key": f"co:{d}", "company": d, "domain": d, "locations": loc, "region": "europe", "score": 10}
            for d, loc in (("a.no", ["Oslo, Norway"]), ("b.se", ["Stockholm, Sweden"]), ("c.de", ["Berlin, Germany"]), ("d.uk", ["London"]))]
    leads_store.upsert_leads(conn, rows)
    got = lambda loc: sorted(l["domain"] for l in leads_store.pick_new(conn, limit=10, location=loc))
    assert got("Norway, Sweden") == ["a.no", "b.se"]
    assert got("United Kingdom") == ["d.uk"]
    assert got("Germany") == ["c.de"]
