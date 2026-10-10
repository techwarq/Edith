from edith.startup_finder import apollo, finder


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_match_keeps_only_verified_emails(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        status = "verified" if json.get("first_name") == "Ana" else "unavailable"
        return _Resp(200, {"person": {"name": f"{json.get('first_name')} X", "email": "a@x.ai", "email_status": status,
                                      "linkedin_url": "http://linkedin.com/in/a"}})

    monkeypatch.setattr(apollo.requests, "post", fake_post)
    good = apollo.match("k", "x.ai", name="Ana Berg")
    bad = apollo.match("k", "x.ai", name="Leo Lind")
    assert good["email"] == "a@x.ai" and bad["email"] is None
    url, body, headers = calls[0]
    assert url.endswith("/people/match") and headers["x-api-key"] == "k"
    assert body == {"domain": "x.ai", "first_name": "Ana", "last_name": "Berg"}


def test_find_contacts_prefers_apollo_and_skips_hunter(monkeypatch):
    monkeypatch.setattr(finder.apollo, "match", lambda key, domain, name=None, linkedin=None, apollo_id=None: {
        "name": name, "email": "ana@x.ai", "email_status": "verified", "linkedin": None})
    monkeypatch.setattr(finder, "_hunter_email", lambda *a: (_ for _ in ()).throw(AssertionError("hunter called")))
    monkeypatch.setattr(finder, "_hunter_founders", lambda *a: (_ for _ in ()).throw(AssertionError("hunter called")))
    lead = {"company": "X", "domain": "x.ai", "founders": [{"name": "Ana Berg", "title": "Co-founder & CTO", "linkedin": "l"}]}
    finder._find_contacts(lead, hunter_api_key="h", apollo_api_key="k")
    assert lead["founders"][0]["email"] == "ana@x.ai" and lead["contact_email"] == "ana@x.ai"


def test_find_contacts_uses_free_search_when_no_names(monkeypatch):
    matched = []
    monkeypatch.setattr(finder.apollo, "search_leaders", lambda key, domain: [
        {"id": "s1", "first_name": "Sam", "title": "Head of Sales", "has_email": True},
        {"id": "c1", "first_name": "Cleo", "title": "CTO", "has_email": True},
        {"id": "f1", "first_name": "Finn", "title": "Founder", "has_email": False},
    ])

    def fake_match(key, domain, name=None, linkedin=None, apollo_id=None):
        matched.append(apollo_id)
        return {"name": "Cleo Ray", "title": "CTO", "email": "cleo@x.ai", "email_status": "verified", "linkedin": "li"}

    monkeypatch.setattr(finder.apollo, "match", fake_match)
    lead = {"company": "X", "domain": "x.ai", "founders": []}
    finder._find_contacts(lead, apollo_api_key="k")
    assert matched == ["c1"]
    assert lead["contact_email"] == "cleo@x.ai" and lead["founders"][0]["name"] == "Cleo Ray"


def test_email_must_belong_to_the_company():
    ok = [("stian@vexter.io", "Vexter AS", "vexter.no"), ("paolo@tether.to", "Tether", "careers.tether.io"),
          ("joseph@wolve.no", "Wolve Loyalty Platform", "wolve.ai"), ("hasib@flinncomply.com", "Flinn", "flinn.ai"),
          ("amanmender@trycorafoneai.com", "Corafone", "corafone.com"), ("a@x.ai", "Zed", "x.ai")]
    bad = [("fdaza@factorial.com.co", "Hurree", "gibcap.factorial.com"), ("bob@gmail.com", "Vexter AS", "vexter.no")]
    for email, company, domain in ok:
        assert finder._email_belongs(email, {"company": company, "domain": domain}), email
    for email, company, domain in bad:
        assert not finder._email_belongs(email, {"company": company, "domain": domain}), email


def test_merge_people_dedupes_apollo_and_crustdata_variants():
    crust = [{"name": "Lars Vågnes", "title": "Co-Founder & CEO", "linkedin": "https://www.linkedin.com/in/lars-vagnes", "email": None},
             {"name": "Antony  E. Kiroles", "title": "Co-Founder & CTO", "linkedin": "https://www.linkedin.com/in/antonykiroles", "email": None}]
    apol = [{"name": "Lars V", "title": "Co-Founder & CEO", "email": "lars@simli.com", "linkedin": None},
            {"name": "Antony Kiroles", "title": "Co-Founder & CTO", "email": "antony@simli.com", "linkedin": "http://linkedin.com/in/antonykiroles"},
            {"name": "Lars Berg", "title": "Engineer", "email": "lb@simli.com"}]
    out = finder._merge_people(crust, apol)
    assert [(p["name"], p["email"]) for p in out] == [
        ("Lars Vågnes", "lars@simli.com"), ("Antony  E. Kiroles", "antony@simli.com"), ("Lars Berg", "lb@simli.com")]


def test_site_email_parsing_and_ranking():
    from edith.startup_finder import site_emails
    cf = "54" + "".join(f"{ord(c) ^ 0x54:02x}" for c in "team@acme.ai")
    page = ('<a href="mailto:hello@acme.ai">x</a> jobs@acme.ai noreply@acme.ai logo@2x.png bob@gmail.com '
            f'<span data-cfemail="{cf}"></span> <span data-cfemail="5401"></span> ola.nord@acme.ai')
    found = site_emails.emails_on_page(page, "acme.ai")
    assert "noreply@acme.ai" not in found and "bob@gmail.com" not in found
    assert set(found) >= {"hello@acme.ai", "jobs@acme.ai", "ola.nord@acme.ai", "team@acme.ai"}
    assert site_emails.best(found, ["Ola"]) == ("ola.nord@acme.ai", "ola")
    assert site_emails.best(["jobs@acme.ai", "hello@acme.ai"], []) == ("hello@acme.ai", None)


def test_apollo_quota_stops_lookups_and_warns(monkeypatch):
    calls = []

    def out_of_credits(*a, **k):
        calls.append(1)
        raise finder.apollo.ApolloQuotaError("Apollo is out of credits")

    monkeypatch.setattr(finder.apollo, "match", out_of_credits)
    finder.QUOTA_HIT.clear()
    for d in ("a.ai", "b.ai"):
        finder._find_contacts({"company": d, "domain": d, "founders": [{"name": "Ana Berg", "title": "CEO"}]}, apollo_api_key="k")
    assert len(calls) == 1 and finder.quota_warnings() == ["Apollo is out of credits"]


def test_prospeo_fills_email_when_apollo_is_out(monkeypatch):
    monkeypatch.setattr(finder.apollo, "match", lambda *a, **k: (_ for _ in ()).throw(finder.apollo.ApolloQuotaError("x")))
    asked = []

    def fake_enrich(key, domain, name=None, linkedin=None):
        asked.append(name)
        return {"name": name, "email": "mike@kosli.com" if name == "Mike Long" else None, "email_status": "verified", "linkedin": "li"}

    monkeypatch.setattr(finder.prospeo, "enrich", fake_enrich)
    finder.QUOTA_HIT.clear()
    lead = {"company": "Kosli", "domain": "kosli.com", "founders": [
        {"name": "Mike Long", "title": "Chief Executive Officer"}, {"name": "Sam Ops", "title": "Head of Sales"}]}
    finder._find_contacts(lead, apollo_api_key="a", prospeo_api_key="p")
    assert asked == ["Mike Long"] and lead["contact_email"] == "mike@kosli.com"
    assert finder.quota_warnings() == ["Apollo is out of credits"]


def test_prospeo_parses_response_and_quota(monkeypatch):
    from edith.startup_finder import prospeo
    monkeypatch.setattr(prospeo, "MIN_INTERVAL", 0)
    monkeypatch.setattr(prospeo.time, "sleep", lambda s: None)

    class R:
        def __init__(self, status, body):
            self.status_code, self._b, self.text = status, body, str(body)

        def json(self):
            return self._b

    monkeypatch.setattr(prospeo.requests, "post", lambda url, json, timeout, headers: R(200, {"error": False, "person": {
        "full_name": "Mike Long", "current_job_title": "CEO", "linkedin_url": "li",
        "email": {"status": "VERIFIED", "email": "mike@kosli.com"}}}))
    assert prospeo.enrich("k", "kosli.com", name="Mike Long")["email"] == "mike@kosli.com"
    monkeypatch.setattr(prospeo.requests, "post", lambda url, json, timeout, headers: R(400, {"error": True, "error_code": "INSUFFICIENT_CREDITS"}))
    try:
        prospeo.enrich("k", "kosli.com", name="Mike Long")
        assert False
    except prospeo.ProspeoQuotaError:
        pass
    monkeypatch.setattr(prospeo.requests, "post", lambda url, json, timeout, headers: R(400, {"error": True, "error_code": "NO_MATCH"}))
    assert prospeo.enrich("k", "kosli.com", name="Nobody") is None



def test_prospeo_rate_limit_retries_instead_of_quota(monkeypatch):
    from edith.startup_finder import prospeo
    monkeypatch.setattr(prospeo, "MIN_INTERVAL", 0)
    monkeypatch.setattr(prospeo.time, "sleep", lambda s: None)
    replies = [(429, {"error": True}), (200, {"error": False, "person": {"full_name": "A B", "email": {"status": "VERIFIED", "email": "a@x.ai"}}})]

    class R:
        def __init__(self, status, body):
            self.status_code, self._b, self.text = status, body, str(body)

        def json(self):
            return self._b

    monkeypatch.setattr(prospeo.requests, "post", lambda url, json, timeout, headers: R(*replies.pop(0)))
    assert prospeo.enrich("k", "x.ai", name="A B")["email"] == "a@x.ai"
