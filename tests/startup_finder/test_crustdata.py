from edith.memory import db
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import crustdata, finder

CLIPSTER = {
    "crustdata_company_id": 1,
    "basic_info": {"name": "Clipster", "primary_domain": "clipster.ai", "year_founded": 2023,
                   "description": "Clipster turns long videos into short-form clips for creators with AI.",
                   "professional_network_url": "https://www.linkedin.com/company/clipster"},
    "headcount": {"total": 12, "growth_percent": {"yoy": 50.0}},
    "funding": {"total_investment_usd": 3_500_000.0, "last_round_type": "seed", "last_fundraise_date": "2025-03-01",
                "investors": ["Antler", "Seedcamp"]},
    "locations": {"country": "SWE", "headquarters": "Stockholm, Sweden"},
    "hiring": {"openings_count": 3},
    "people": {
        "founders": [{"basic_profile": {"name": "Ana Berg", "current_title": "Co-founder & CEO"},
                      "social_handles": {"professional_network_identifier": {"profile_url": "https://linkedin.com/in/anaberg"}}}],
        "cxos": [{"basic_profile": {"name": "Ana Berg", "current_title": "CEO"}},
                 {"basic_profile": {"name": "Leo Lind", "current_title": "CTO"}}],
    },
}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_enrich_summarizes_and_dedupes_people(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return _Resp(200, [
            {"matched_on": "clipster.ai", "match_type": "domain", "matches": [{"confidence_score": 1.0, "company_data": CLIPSTER}]},
            {"matched_on": "nope.ai", "match_type": "domain", "matches": []},
        ])

    monkeypatch.setattr(crustdata.requests, "post", fake_post)
    out = crustdata.enrich("k", ["Clipster.ai", "nope.ai", "clipster.ai"])

    url, body, headers = calls[0]
    assert url.endswith("/company/enrich")
    assert body["domains"] == ["clipster.ai", "nope.ai"]
    assert headers["authorization"] == "Bearer k" and headers["x-api-version"] == crustdata.API_VERSION
    info = out["clipster.ai"]
    assert "nope.ai" not in out
    assert info["headcount"] == 12 and info["last_round"] == "seed" and info["hq"] == "Stockholm, Sweden"
    assert [f["name"] for f in info["founders"]] == ["Ana Berg", "Leo Lind"]
    assert info["founders"][0]["linkedin"] == "https://linkedin.com/in/anaberg"
    text = crustdata.format_info(info)
    assert "12 people (+50% yoy)" in text and "$3.5M raised, last seed 2025-03" in text


def test_enrich_batches_and_survives_errors(monkeypatch):
    sizes = []

    def fake_post(url, json, headers, timeout):
        sizes.append(len(json["domains"]))
        if len(sizes) == 1:
            return _Resp(403, {"error": {"message": "out of credits"}})
        return _Resp(200, [])

    monkeypatch.setattr(crustdata.requests, "post", fake_post)
    assert crustdata.enrich("k", [f"d{i}.com" for i in range(30)]) == {}
    assert sizes == [25, 5]


def test_find_applies_crustdata_and_persists(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    raw = [{"kind": "founder", "dedup_key": "co:clipster.ai", "company": "Clipster", "domain": "clipster.ai", "fund": "Antler",
            "source": "getro", "region": "europe", "description": "AI video", "active_jobs": 1}]
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([dict(r) for r in raw], {"sources": {}, "errors": {}}))
    seen = []
    monkeypatch.setattr(finder.crustdata, "enrich", lambda key, domains: seen.append(domains) or crustdata_out())
    monkeypatch.setattr(finder, "_hunter_email", lambda key, domain, name: "ana@clipster.ai" if name == "Ana Berg" else None)
    monkeypatch.setattr(finder, "_hunter_founders", lambda key, lead: ([], None))

    out = finder.find(conn, count=1, crustdata_api_key="k", hunter_api_key="h")

    assert seen == [["clipster.ai"]]
    lead = out["leads"][0]
    assert lead["team_size"] == 12 and lead["stage"] == "seed"
    ana = lead["founders"][0]
    assert ana["email"] == "ana@clipster.ai" and ana["linkedin"] == "https://linkedin.com/in/anaberg"
    stored = leads_store.get_lead(conn, lead["id"])
    assert stored["company_info"]["total_funding_usd"] == 3_500_000.0
    assert stored["team_size"] == 12
    assert "founders" not in stored["company_info"]
    assert stored["draft_to"] == "ana@clipster.ai" and stored["draft_body"].startswith("hello ana,")


def test_find_skips_crustdata_without_key(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    raw = [{"kind": "founder", "dedup_key": "co:vox.ai", "company": "Vox", "domain": "vox.ai", "fund": "Index",
            "source": "getro", "region": "europe", "description": "AI audio dubbing", "active_jobs": 1}]
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([dict(r) for r in raw], {"sources": {}, "errors": {}}))
    monkeypatch.setattr(finder.crustdata, "enrich", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    assert finder.find(conn, count=1)["returned"] == 1


def crustdata_out():
    return {"clipster.ai": crustdata._summarize(CLIPSTER)}


def test_us_hq_from_crustdata_is_dropped_and_headcount_overrides(tmp_path, monkeypatch):
    from tests.startup_finder.test_finder import FakeClient, _no_fetch
    conn = db.connect(tmp_path / "t.db")
    raw = [
        {"kind": "founder", "dedup_key": "co:clipster.ai", "company": "Clipster", "domain": "clipster.ai", "fund": "Antler",
         "source": "getro", "region": "europe", "description": "AI video", "active_jobs": 1, "team_size": 30},
        {"kind": "founder", "dedup_key": "co:nyc.ai", "company": "Nyc", "domain": "nyc.ai", "fund": "Techstars",
         "source": "getro", "region": "europe", "description": "AI images", "active_jobs": 1, "team_size": 20},
    ]
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([dict(r) for r in raw], {"sources": {}, "errors": {}}))
    _no_fetch(monkeypatch)
    us = {**CLIPSTER, "basic_info": {"name": "Nyc"}, "locations": {"headquarters": "New York, New York, United States"}}
    monkeypatch.setattr(finder.crustdata, "enrich", lambda key, domains: {
        "clipster.ai": crustdata._summarize(CLIPSTER), "nyc.ai": crustdata._summarize(us)})
    out = finder.find(conn, count=2, genai_client=FakeClient(), model="m", crustdata_api_key="k", min_team=10, max_team=40)
    assert [l["company"] for l in out["leads"]] == ["Clipster"]
    assert out["leads"][0]["team_size"] == 12
    assert leads_store.list_leads(conn, status="skipped")[0]["region"] == "us"


def test_draft_lead_enriches_old_lead_without_touching_delivery(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO startup_leads (dedup_key, kind, company, domain, status, delivered_at) "
                 "VALUES ('co:clipster.ai', 'founder', 'Clipster', 'clipster.ai', 'delivered', '2026-01-01T00:00:00Z')")
    monkeypatch.setattr(finder.crustdata, "enrich", lambda key, domains: crustdata_out())
    monkeypatch.setattr(finder, "_hunter_email", lambda key, domain, name: None)
    monkeypatch.setattr(finder, "_hunter_founders", lambda key, lead: ([], None))
    monkeypatch.setattr(finder, "_hunter_generic", lambda key, domain: "hello@clipster.ai")

    lead = finder.draft_lead(conn, 1, None, "m", hunter_api_key="h", crustdata_api_key="k")

    assert lead["company_info"]["headcount"] == 12
    assert [f["name"] for f in lead["founders"]][:1] == ["Ana Berg"]
    assert lead["draft_to"] == "hello@clipster.ai"
    assert lead["delivered_at"] == "2026-01-01T00:00:00Z" and lead["status"] == "delivered"


def test_location_search_feeds_pool_and_survives_prune(tmp_path, monkeypatch):
    from tests.startup_finder.test_finder import FakeClient, _no_fetch
    conn = db.connect(tmp_path / "t.db")
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([], {"sources": {}, "errors": {}}))
    _no_fetch(monkeypatch)
    rows = [{**CLIPSTER, "basic_info": {**CLIPSTER["basic_info"], "name": "Riff", "primary_domain": "riff.ai",
                                        "description": "Turn operational knowledge into AI agents."},
             "locations": {"headquarters": "Oslo, Norway", "country": "Norway"}}]
    calls = []
    monkeypatch.setattr(finder.crustdata, "_post", lambda key, path, body: calls.append(body) or {"companies": rows, "next_cursor": None})
    monkeypatch.setattr(finder.crustdata, "enrich", lambda key, domains: {})

    out = finder.find(conn, count=1, genai_client=FakeClient(), model="m", crustdata_api_key="k",
                      location="Norway", min_team=10, max_team=40)

    assert [l["company"] for l in out["leads"]] == ["Riff"]
    conds = calls[0]["filters"]["conditions"]
    assert {"field": "headcount.total", "type": "=>", "value": 10} in conds
    assert conds[0]["conditions"][0] == {"field": "locations.country", "type": "in", "value": ["Norway"]}
    assert out["leads"][0]["company_info"]["headcount"] == 12
    finder.refresh(conn)
    assert leads_store.get_lead(conn, out["leads"][0]["id"]) is not None


def test_same_company_under_another_domain_is_not_repeated(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    raw = [{"kind": "founder", "dedup_key": f"co:{d}", "company": n, "domain": d, "fund": "Antler", "source": "getro",
            "region": "europe", "description": "AI video", "active_jobs": 1, "team_size": 20}
           for n, d in (("Vexter AS", "vexter.no"), ("Vexter", "vexter.io"), ("Other", "other.ai"))]
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([dict(r) for r in raw], {"sources": {}, "errors": {}}))
    first = finder.find(conn, count=1)
    second = finder.find(conn, count=5)
    names = [l["company"] for l in first["leads"] + second["leads"]]
    assert sorted(names) == ["Other", "Vexter AS"] or sorted(names) == ["Other", "Vexter"]
