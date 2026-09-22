"""The bounded perceive-decide-act loop for one goal.

Step 0 locks onto a single window (by app identity, not "whichever window
happens to be frontmost") and every later step re-verifies and acts on that
exact window — see accessibility.PinnedWindow / refresh_pinned /
raise_pinned. There is no re-query of "what's frontmost" anywhere after
that: if the pinned window disappears, the loop stops and says so rather
than adopting a new frontmost window to act on instead.

A confidence gate stops and reports rather than acting on a low-confidence
guess — mirrors computer-use-jev's own DESIGN.md, with our own decision step
(decide.py, calling Jev via OpenRouter) in place of theirs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import openai

from edith.computer_use import accessibility, perception, writer
from edith.computer_use.actions import ActionError, perform
from edith.computer_use.decide import Decision, PerceivedState, choose_target_app, choose_window_index, decide
from edith.computer_use.typesafe_client import TypeSafeClient, TypeSafeError


@dataclass
class StepRecord:
    number: int
    kind: str
    confidence: float
    result: str


@dataclass
class RunResult:
    done: bool
    steps: list[StepRecord] = field(default_factory=list)
    message: str = ""


def _snapshot(pinned: accessibility.PinnedWindow, goal: str, history: list[str]) -> Optional[PerceivedState]:
    """Re-verifies the pinned window by AX identity and builds this step's
    state from *only* that window's own element tree. Returns None once the
    window is confirmed gone — never falls back to scanning for a new
    frontmost window."""
    window_info = accessibility.refresh_pinned(pinned)
    if window_info is None:
        return None
    accessibility.raise_pinned(pinned)
    elements = accessibility.walk_elements(pinned.element)
    items = perception.build_items(elements, window_info.frame)
    return PerceivedState(goal, pinned, window_info.title, window_info.frame, items, history)


def run(
    client: TypeSafeClient,
    goal: str,
    max_steps: int,
    confidence_threshold: float,
    writer_client: Optional[openai.OpenAI] = None,
    writer_model: str = "",
    on_progress: Optional[Callable[[str], None]] = None,
) -> RunResult:
    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    if not accessibility.is_trusted():
        return RunResult(
            False,
            [],
            "Accessibility permission hasn't been granted yet — grant it in System Settings > "
            "Privacy & Security > Accessibility, then try again.",
        )

    apps = accessibility.running_apps()
    if not apps:
        return RunResult(False, [], "No running applications found to act on.")

    if writer_client is not None:
        try:
            launch_name = writer.app_to_launch(writer_client, writer_model, goal, [a.name for a in apps])
        except Exception:  # noqa: BLE001 — this is a nice-to-have; a writer hiccup shouldn't sink the run
            launch_name = None
        if launch_name:
            progress(f"Opening {launch_name}...")
            if accessibility.launch_app(launch_name):
                apps = accessibility.running_apps()
            else:
                progress(f"Couldn't open {launch_name} — continuing with what's already running.")

    try:
        target_app = choose_target_app(client, goal, apps)
    except TypeSafeError as e:
        return RunResult(False, [], f"Couldn't determine which application this goal targets — {e}")

    progress(f"Switching to {target_app.name}...")
    accessibility.activate_app(target_app.pid)

    # Some apps (browsers, Finder, Mail...) group several logical windows
    # under one native macOS window-tab titlebar — the Accessibility API
    # only ever exposes the *selected* tab as a full window, everything else
    # as a blank sliver, so disambiguating by AX title alone can't find a
    # background one. Their own scripting bridge sees the true titles and
    # can select among them; select first, then let AX see the real window.
    scriptable_titles = accessibility.scriptable_window_titles(target_app.name)
    if scriptable_titles and len(scriptable_titles) > 1:
        progress(f"Choosing which {target_app.name} window to use...")
        try:
            idx = choose_window_index(client, goal, scriptable_titles)
        except TypeSafeError as e:
            return RunResult(False, [], f"Couldn't determine which {target_app.name} window this goal targets — {e}")
        accessibility.select_scriptable_window(target_app.name, scriptable_titles[idx])
        time.sleep(0.3)

    candidates = [w for w in accessibility.windows(target_app.pid) if not w.minimized]
    if not candidates:
        return RunResult(False, [], f"{target_app.name} has no open window to act on.")
    if len(candidates) == 1:
        window = candidates[0]
    else:
        titles = [accessibility.window_title(w) for w in candidates]
        try:
            idx = choose_window_index(client, goal, titles)
        except TypeSafeError as e:
            return RunResult(False, [], f"Couldn't determine which {target_app.name} window this goal targets — {e}")
        window = candidates[idx]

    pinned = accessibility.pin_window(target_app, window)
    progress(f"Working in {pinned.app_name} — {pinned.title_at_pin}")

    history: list[str] = []
    steps: list[StepRecord] = []

    for step_number in range(1, max_steps + 1):
        state = _snapshot(pinned, goal, history)
        if state is None:
            return RunResult(
                False,
                steps,
                f"Lost the {pinned.app_name} window ({pinned.title_at_pin!r}) — stopping rather than "
                "hunting for a new frontmost window to act on instead.",
            )

        try:
            decision = decide(client, state)
        except TypeSafeError as e:
            return RunResult(False, steps, f"Stopped after {step_number - 1} step(s) — {e}")

        if decision.kind.choice == "done":
            steps.append(StepRecord(step_number, "done", decision.confidence, "(goal judged satisfied)"))
            if not decision.satisfied:
                return RunResult(
                    False, steps, "Jev chose 'done' but did not confirm the goal satisfied — stopping rather than guessing."
                )
            return RunResult(True, steps, "goal achieved")

        if decision.satisfied:
            steps.append(
                StepRecord(step_number, decision.kind.choice, decision.confidence, "(goal already satisfied; no action taken)")
            )
            return RunResult(True, steps, "goal achieved")

        if decision.confidence < confidence_threshold:
            return RunResult(
                False,
                steps,
                f"Stopped after {step_number - 1} step(s) — low confidence ({decision.confidence:.2f}) "
                f"on next action {decision.kind.choice!r}.",
            )

        if decision.kind.choice == "blocked":
            steps.append(StepRecord(step_number, "blocked", decision.confidence, "(Jev judged this unreachable)"))
            return RunResult(False, steps, "Stopped — the goal can't be made progress on from this window.")

        if decision.kind.choice == "wait":
            progress("Waiting for the window to settle...")
            time.sleep(1.0)
            steps.append(StepRecord(step_number, "wait", decision.confidence, "(waited for the window to settle)"))
            history.append("waited")
            continue

        progress(f"{decision.kind.choice.capitalize()}{_target_description(decision, state)}...")

        title_before = state.window_title
        try:
            result = perform(decision, state, writer_client, writer_model)
        except (ActionError, accessibility.AccessibilityError) as e:
            result = f"error: {e}"
        else:
            # click/fill/press/scroll all take a moment to actually land — without
            # this, the next snapshot can still see the pre-action state, which is
            # what made the loop re-issue the same action repeatedly.
            time.sleep(0.6)

        # Verify in code, not by asking again: did the window we just acted on
        # actually change? Surfaced in history so the *next* decide() call can
        # tell a no-op click apart from one that landed, instead of guessing.
        after = accessibility.refresh_pinned(pinned)
        if after is None:
            steps.append(StepRecord(step_number, decision.kind.choice, decision.confidence, result))
            return RunResult(
                False,
                steps,
                f"Lost the {pinned.app_name} window ({pinned.title_at_pin!r}) right after a {decision.kind.choice} — "
                "stopping rather than hunting for a new frontmost window to act on instead.",
            )
        if after.title != title_before:
            result += f" (title changed to {after.title!r})"
            progress(f"Now on: {after.title}")

        steps.append(StepRecord(step_number, decision.kind.choice, decision.confidence, result))
        history.append(f"{decision.kind.choice}{_target_description(decision, state)} -> {result}")

    return RunResult(False, steps, f"Stopped after {max_steps} steps without reaching the goal.")


def _target_description(decision: Decision, state: PerceivedState) -> str:
    """Element indices are renumbered fresh every snapshot, so a history
    entry that only says "click -> clicked" can't tell step 5's click apart
    from step 1's — the model has no way to notice it already did this.
    Recording the actual role/label (stable across steps, unlike the index)
    is what lets 'do not repeat an action already taken' and goal_satisfied
    actually work."""
    if decision.item is not None:
        try:
            idx = int(decision.item.choice)
        except ValueError:
            return ""
        item = next((i for i in state.items if i.index == idx), None)
        if item:
            return f" {item.role} {item.label!r}"
    return ""
