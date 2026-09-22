"""Maps a Decision onto a real accessibility.py call. Text and key values
come from the goal (via writer.py) — never from Jev itself: the classifier
picks a job, never the literal content, same separation of concerns as
computer-use-jev's own design.
"""

from __future__ import annotations

from typing import Optional

import openai

from edith.computer_use import accessibility, writer
from edith.computer_use.decide import Decision, PerceivedState


class ActionError(Exception):
    pass


def perform(
    decision: Decision,
    state: PerceivedState,
    writer_client: Optional[openai.OpenAI],
    writer_model: str,
) -> str:
    kind = decision.kind.choice

    if kind in ("click", "fill"):
        if decision.item is None:
            raise ActionError(f"{kind} needs an item choice")
        try:
            idx = int(decision.item.choice)
        except ValueError as e:
            raise ActionError(f"Jev returned a non-numeric item choice: {decision.item.choice!r}") from e
        item = next((i for i in state.items if i.index == idx), None)
        if item is None:
            raise ActionError(f"Jev chose an item not in the current list: {decision.item.choice!r}")

        if kind == "click":
            return accessibility.click(item.ax_element, item.frame)

        text = writer.quoted_segment(state.goal)
        if text is None:
            if writer_client is None:
                raise ActionError("goal names no literal text and no writer is configured to compose it")
            text = writer.compose_fill_text(writer_client, writer_model, state.goal, item.label, state.history)
        if not text:
            raise ActionError("writer declined to compose text for this field")
        return accessibility.set_text(item.ax_element, item.frame, text)

    if kind == "press":
        combo = writer.key_combo(state.goal)
        if combo is None:
            raise ActionError("goal names no keyboard shortcut for 'press' (e.g. cmd+s)")
        accessibility.press_key(combo)
        return f"pressed {combo}"

    if kind == "scroll_down":
        if state.window_frame is None:
            raise ActionError("no window frame to scroll")
        x, y, w, h = state.window_frame
        accessibility.scroll((x + w / 2, y + h / 2), lines=-10)
        return "scrolled down"

    raise ActionError(f"unknown action kind {kind!r}")
