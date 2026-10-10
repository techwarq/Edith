from edith.startup_finder import qualify


def test_eligibility_worldwide_and_india():
    assert qualify.eligibility(["REMOTE (Worldwide)"])[0] == "yes"
    assert qualify.eligibility(["REMOTE (US/Canada/UK/India)"])[0] == "yes"
    assert qualify.eligibility(["Remote"], "Overlap with IST hours")[0] == "yes"


def test_eligibility_region_locked():
    assert qualify.eligibility(["REMOTE (US or Canada)"], "global brand, international team")[0] == "no"
    assert qualify.eligibility(["Germany", "Europe", "Remote"])[0] == "no"
    assert qualify.eligibility(["Remote"], "Must be based in the US")[0] == "no"
    assert qualify.eligibility(["Stuttgart & Remote"], "Das Team ist super")[0] == "no"


def test_eligibility_bare_remote_is_likely():
    assert qualify.eligibility(["Remote"]) == ("likely", "remote, no country listed")


def test_role_fit_filters():
    assert qualify.role_fit("AI Engineer")[0] == 25
    assert qualify.role_fit("Founding Engineer")[0] == 25
    assert qualify.role_fit("Member of Technical Staff")[0] > 0
    assert qualify.role_fit("Senior Software Engineer")[0] < qualify.role_fit("Software Engineer")[0]
    for bad in ("Solutions Engineer", "Account Executive", "Staff Engineer", "Forward Deployed Engineer, Spanish/English", "Stack: python, react", "https://x.com/careers/engineer"):
        assert qualify.role_fit(bad)[0] == 0, bad


def test_region_of():
    assert qualify.region_of(["Berlin, Germany"]) == "europe"
    assert qualify.region_of(["Dubai - United Arab Emirates"]) == "middle_east"
    assert qualify.region_of(["Bengaluru"]) == "india"


def test_team_size_buckets():
    assert qualify.team_size(2, bucketed=True) == 30
    assert qualify.team_size(250) == 250
    assert qualify.team_size(None) is None


def test_score_creative_ai_europe_role_beats_generic_us_role():
    creative = qualify.score({
        "kind": "role", "company": "Clipster", "description": "AI video editing for creators",
        "role_title": "AI Engineer", "locations": ["Remote"], "region": "europe", "team_size": 12,
    })
    generic = qualify.score({
        "kind": "role", "company": "Ledgerly", "description": "accounting software",
        "role_title": "Software Engineer", "locations": ["Remote"], "region": "global", "team_size": 900,
    })
    assert creative and generic
    assert creative["score"] > generic["score"]
    assert any("creative AI" in r for r in creative["reasons"])


def test_score_drops_low_salary_and_locked_roles():
    assert qualify.score({"kind": "role", "company": "X", "role_title": "Backend Engineer", "locations": ["Remote"], "salary_raw": {"max": 900, "currency": "USD", "period": "month"}}) is None
    assert qualify.score({"kind": "role", "company": "X", "role_title": "Backend Engineer", "locations": ["Remote", "France"]}) is None


def test_founder_leads_need_ai_and_small_team():
    assert qualify.score({"kind": "founder", "company": "Bakery", "description": "bread delivery", "region": "europe"}) is None
    assert qualify.score({"kind": "founder", "company": "BigAI", "description": "AI agents", "region": "europe", "team_size": 3000}) is None
    lead = qualify.score({"kind": "founder", "company": "Vox", "description": "AI audio dubbing", "region": "europe", "team_size": 5, "active_jobs": 3, "founders": [{"name": "A"}]})
    assert lead and lead["eligibility"] == "founder_dm"


def test_only_europe_and_middle_east():
    base = {"kind": "founder", "company": "Vox", "description": "AI audio dubbing", "team_size": 5}
    assert qualify.score({**base, "region": "us"}) is None
    assert qualify.score({**base, "region": "apac"}) is None
    assert qualify.score({**base, "region": "europe"})
    assert qualify.score({**base, "region": "middle_east"})
    assert qualify.score({**base, "region": "global"})
