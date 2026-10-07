import pytest

from edith.computer_use import browser_page, jev_step
from edith.computer_use.typesafe_client import Answer


class FakeJev:
    def __init__(self, answers, source="jev"):
        self.answers = answers
        self.last_source = source
        self.seen_state = None
        self.seen_questions = None

    def ask(self, state, questions):
        self.seen_state, self.seen_questions = state, questions
        out = {}
        for qid, q in questions.items():
            if qid in self.answers:
                out[qid] = self.answers[qid]
            elif q.type == "noul":
                out[qid] = Answer(type="noul", noul=0.0)
            else:
                out[qid] = Answer(type="choice", choice="none", probabilities={"none": 1.0}, confidence=1.0)
        return out


def pick(c, p=0.99, conf=0.95):
    return Answer(type="choice", choice=c, probabilities={c: p}, confidence=conf)


def yes(v):
    return Answer(type="noul", noul=v)


@pytest.fixture(autouse=True)
def no_real_apps(monkeypatch):
    monkeypatch.setattr(jev_step, "candidate_apps", lambda goal: ["Notes", "Calculator"])


def page(*elements):
    return browser_page.PageSnapshot(url="https://apply.example.com", title="Apply", elements=list(elements), text=[])


def el(id, label, role="button", editable=False, secure=False, value=""):
    return browser_page.PageElement(id=id, tag="input" if editable else "button", role=role, label=label, value=value,
                                    placeholder="", editable=editable, enabled=True, checked=None, focused=False,
                                    secure=secure, position="middle center", in_view=True)


def run(fake, snap, goal="do it", texts=(), allow_risky=False):
    return jev_step.decide(fake, goal, [], "Brave Browser", "Apply", jev_step.page_table(snap), True, snap,
                           list(texts), [], allow_risky)


def test_ordinary_click_clears_gate_and_maps_to_page_click():
    snap = page(el("p0", "Next"))
    out = run(FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0")}), snap)
    assert out.choice.decision["action"] == "page_click" and out.choice.decision["id"] == "p0"
    assert not out.choice.consequential


def test_low_confidence_falls_back_instead_of_guessing():
    snap = page(el("p0", "Next"))
    out = run(FakeJev({"nextOperation": pick("click", p=0.5, conf=0.3), "clickTarget": pick("p0")}), snap)
    assert out.choice is None and "low confidence" in out.note


def test_consequential_without_authorization_needs_confirmation():
    snap = page(el("p0", "Submit"))
    out = run(FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0"),
                       "consequential": yes(0.95), "explicitAuthorization": yes(0.3)}), snap)
    assert out.choice is not None and out.choice.reason


def test_consequential_authorized_by_goal_runs():
    snap = page(el("p0", "Submit"))
    out = run(FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0"),
                       "consequential": yes(0.95), "explicitAuthorization": yes(0.95)}), snap)
    assert out.choice is not None and not out.choice.reason and out.choice.consequential


def test_fallback_model_can_never_authorize_a_consequential_step():
    snap = page(el("p0", "Submit"))
    fake = FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0"),
                    "consequential": yes(0.95), "explicitAuthorization": yes(0.99)}, source="fallback")
    assert run(fake, snap).choice.reason


def test_consequential_needs_stricter_confidence_even_when_allowed():
    snap = page(el("p0", "Submit"))
    out = run(FakeJev({"nextOperation": pick("click", p=0.7, conf=0.6), "clickTarget": pick("p0"),
                       "consequential": yes(0.95)}), snap, allow_risky=True)
    assert out.choice is None


def test_fill_only_uses_provided_text_and_editable_fields():
    snap = page(el("p0", "Company name", role="text field", editable=True), el("p1", "Submit"))
    fake = FakeJev({"nextOperation": pick("fill"), "fillTarget": pick("p0"), "fillText": pick("t0")})
    out = run(fake, snap, texts=["Eddy Labs"])
    assert out.choice.decision == {"action": "page_fill", "id": "p0", "text": "Eddy Labs",
                                   "describe": "Filling “Company name”"}
    assert set(fake.seen_questions["fillTarget"].criteria) == {"p0", "none"}


def test_no_fill_operation_without_text_to_fill():
    snap = page(el("p0", "Company name", role="text field", editable=True))
    fake = FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0")})
    run(fake, snap)
    assert "fill" not in fake.seen_questions["nextOperation"].criteria


def test_password_fields_are_never_fill_targets():
    snap = page(el("p0", "Password", role="password field", editable=True, secure=True))
    fake = FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0")})
    run(fake, snap, texts=["hunter2"])
    assert "fill" not in fake.seen_questions["nextOperation"].criteria


def test_quoted_text_in_goal_becomes_a_typable_value():
    assert jev_step.candidate_texts('type "hello from Eddy" please', []) == ["hello from Eddy"]


def test_done_requires_verified_completion():
    snap = page(el("p0", "Next"))
    unverified = run(FakeJev({"nextOperation": pick("DONE", p=0.97), "completionVerified": yes(0.5)}), snap)
    verified = run(FakeJev({"nextOperation": pick("DONE", p=0.97), "completionVerified": yes(0.95)}), snap)
    assert not unverified.done and unverified.choice is None
    assert verified.done


def test_state_sent_to_jev_has_no_coordinates_or_pixels():
    snap = page(el("p0", "Next"))
    fake = FakeJev({"nextOperation": pick("click"), "clickTarget": pick("p0")})
    run(fake, snap)
    blob = repr(fake.seen_state)
    assert "jpeg" not in blob and "frame" not in blob and "middle center" in blob


def test_destructive_shortcuts_are_not_on_jevs_menu():
    for combo in ("cmd+q", "cmd+delete", "cmd+return", "cmd+enter"):
        assert combo not in jev_step.SAFE_KEYS


def test_dropdowns_are_fillable_by_option_text():
    snap = page(el("p0", "Batch", role="dropdown"))
    fake = FakeJev({"nextOperation": pick("fill"), "fillTarget": pick("p0"), "fillText": pick("t0")})
    out = run(fake, snap, texts=["Spring 2027"])
    assert out.choice.decision["action"] == "page_fill" and out.choice.decision["text"] == "Spring 2027"
