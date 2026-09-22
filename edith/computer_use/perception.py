"""Merges accessibility elements with OCR text into one numbered item table —
the same text-table shape either way, so Jev reasons over rows, never a
screenshot. This is what lets a control the accessibility tree never exposes
(a web app's custom video-player buttons, canvas-rendered UI) still show up
as something clickable. Perception only builds the table; decide.py is still
the only place that chooses what to do with a row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from edith.computer_use import accessibility, ocr, screen

MAX_ITEMS = 120
# Single letters/stray punctuation OCR occasionally reports aren't worth
# offering as a click target.
MIN_OCR_TEXT_LENGTH = 2


@dataclass(frozen=True)
class Item:
    index: int
    role: str
    label: str
    frame: Optional[tuple[float, float, float, float]]
    editable: bool
    enabled: bool
    ax_element: Optional[Any]  # None for OCR-only items — see accessibility.click_at/type_at


def _ocr_frame_to_screen(
    box: tuple[float, float, float, float],
    window_frame: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Vision's boundingBox is normalized [0, 1] within the captured image,
    origin bottom-left. AX frames (and accessibility.click_at) use absolute
    screen points, origin top-left."""
    box_x, box_y, box_w, box_h = box
    win_x, win_y, win_w, win_h = window_frame
    img_w, img_h = image_size
    scale_x = win_w / img_w if img_w else 1.0
    scale_y = win_h / img_h if img_h else 1.0

    pixel_x = box_x * img_w
    pixel_y_from_top = (1 - box_y - box_h) * img_h

    return (
        win_x + pixel_x * scale_x,
        win_y + pixel_y_from_top * scale_y,
        box_w * img_w * scale_x,
        box_h * img_h * scale_y,
    )


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)


def build_items(
    elements: list[accessibility.ElementInfo],
    window_frame: Optional[tuple[float, float, float, float]],
    max_items: int = MAX_ITEMS,
) -> list[Item]:
    """AX elements first — they carry real semantics (role, editability,
    enabled state) — then OCR text for anything not already covered by an AX
    element's frame. Most native/well-behaved UI needs no OCR at all; it
    only fills the gaps a custom web player leaves."""
    items: list[Item] = []
    for e in elements:
        if len(items) >= max_items:
            return items
        items.append(
            Item(
                index=len(items),
                role=e.role,
                label=e.label,
                frame=e.frame,
                editable=e.editable,
                enabled=e.enabled,
                ax_element=e.element,
            )
        )

    if window_frame is None:
        return items

    try:
        image = screen.capture_window(window_frame)
        blocks = ocr.recognize_text(image)
    except (screen.ScreenCaptureError, ocr.OcrError):
        return items  # OCR is a bonus signal — its absence shouldn't fail the whole perceive step

    image_size = screen.image_size(image)
    ax_frames = [e.frame for e in elements if e.frame]
    ocr_start = len(items)
    for block in blocks:
        if len(items) >= max_items:
            break
        text = block.text.strip()
        if len(text) < MIN_OCR_TEXT_LENGTH:
            continue
        screen_frame = _ocr_frame_to_screen(block.box, window_frame, image_size)
        if any(_overlaps(screen_frame, f) for f in ax_frames):
            continue  # already represented by a real accessibility element
        items.append(
            Item(index=len(items), role="text", label=text, frame=screen_frame, editable=False, enabled=True, ax_element=None)
        )

    return _disambiguate_duplicate_labels(items, ocr_start)


def _disambiguate_duplicate_labels(items: list[Item], ocr_start: int) -> list[Item]:
    """OCR reuses the same plain string for visually distinct controls that
    happen to say the same thing — e.g. a "See all options" expander under
    the Batch filter and another, unrelated one under the Industry filter.
    Identical text is genuinely indistinguishable to the decision model, so
    for any label that repeats, tag each occurrence with the nearest label
    above it (its filter section's own heading, in practice) instead of
    leaving Jev to guess between them."""
    counts: dict[str, int] = {}
    for item in items[ocr_start:]:
        counts[item.label] = counts.get(item.label, 0) + 1
    if not any(c > 1 for c in counts.values()):
        return items

    result = list(items)
    for i in range(ocr_start, len(items)):
        item = items[i]
        if counts[item.label] <= 1 or item.frame is None:
            continue
        nearest_label = None
        nearest_dist = None
        for other in items:
            if other is item or other.frame is None or other.label == item.label:
                continue
            if other.frame[1] >= item.frame[1]:  # only look above (smaller y = higher on screen)
                continue
            dist = abs(other.frame[0] - item.frame[0]) + (item.frame[1] - other.frame[1])
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist, nearest_label = dist, other.label
        if nearest_label:
            result[i] = replace(item, label=f"{item.label} (near {nearest_label!r})")
    return result
