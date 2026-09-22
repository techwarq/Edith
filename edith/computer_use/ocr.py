"""OCR via Apple's Vision framework, called directly through PyObjC — no
ocrmac or other wrapper. Runs on an already-captured CGImage (see screen.py);
needs no permission of its own beyond having that image.
"""

from __future__ import annotations

from dataclasses import dataclass

import Foundation
import Vision


class OcrError(Exception):
    pass


@dataclass(frozen=True)
class TextBlock:
    text: str
    confidence: float
    # normalized bounding box, Vision's bottom-left-origin convention: (x, y, w, h) in [0, 1]
    box: tuple[float, float, float, float]


# Fallback threshold (fraction of text height) for a 2-word line, where
# there's only one gap to look at and no baseline to compare it against.
_WORD_GAP_RATIO = 0.5
# A gap this many times wider than the line's own median word-gap is a real
# visual break (icon padding), not ordinary letter-spacing.
_GAP_OUTLIER_RATIO = 2.2
# An all-letters token this short, trailing a longer cluster, is essentially
# never the last word of real prose in this UI (names/labels, not
# sentences) — almost always Vision reading a social/link icon as text
# ("X", "in", "f"). Peeled off unconditionally since gap size alone isn't a
# reliable signal here (see _cluster_words).
_ICON_TOKEN_MAX_LEN = 2


def _split_trailing_icon_tokens(
    clusters: list[list[tuple[str, tuple[float, float, float, float]]]],
) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """Catches the case _cluster_words' gap analysis can't: Vision sometimes
    spaces an icon glyph exactly like another word in the same line (e.g.
    "Kevin Lin X in" with three perfectly uniform gaps, no outlier at all),
    so there's no gap signal left to split on. Runs after gap clustering, so
    it only ever peels tokens off the *end* of an already-gap-formed
    cluster — it does not touch ordinary short words in the middle of a
    real sentence."""
    result = []
    for cluster in clusters:
        popped = []
        while len(cluster) > 1 and len(cluster[-1][0]) <= _ICON_TOKEN_MAX_LEN and cluster[-1][0].isalpha():
            popped.append(cluster.pop())
        result.append(cluster)
        result.extend([token] for token in reversed(popped))
    return result


def _word_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, length, word) for each whitespace-delimited token — the units
    Vision's boundingBoxForRange:error: needs to report a per-word box
    instead of one box for the whole line."""
    spans = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        start = i
        while i < n and not text[i].isspace():
            i += 1
        if i > start:
            spans.append((start, i - start, text[start:i]))
    return spans


def _cluster_words(
    word_boxes: list[tuple[str, tuple[float, float, float, float]]],
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Vision reports one bounding box per *line*, which merges visually
    distinct controls that happen to sit on the same line — a founder's
    name and the icon-link glyphs beside it end up as a single box, so a
    click aimed at the icon actually lands somewhere between name and icon.
    Re-groups per-word boxes into clusters using the gap between
    consecutive words.

    A fixed gap threshold doesn't work: ordinary letter-spacing and the
    padding before a tightly-set icon glyph can be nearly the same absolute
    width (e.g. "Eric Ren X" — the gap before "X" is no wider than the gap
    between "Eric" and "Ren"). What does reliably stand out is a gap that's
    an outlier *relative to the other gaps in that same line* — icon
    padding is consistently a few times wider than the line's own normal
    word-spacing, even when neither is wide in absolute terms. Only a
    2-word line has no such baseline to compare against, so it falls back
    to a fixed fraction of the text height."""
    if len(word_boxes) <= 1:
        return word_boxes

    avg_h = sum(box[3] for _, box in word_boxes) / len(word_boxes)
    gaps = []
    for i in range(1, len(word_boxes)):
        prev_end_x = word_boxes[i - 1][1][0] + word_boxes[i - 1][1][2]
        gaps.append(word_boxes[i][1][0] - prev_end_x)

    if len(gaps) >= 2:
        sorted_gaps = sorted(gaps)
        mid = len(sorted_gaps) // 2
        median_gap = (
            sorted_gaps[mid] if len(sorted_gaps) % 2 else (sorted_gaps[mid - 1] + sorted_gaps[mid]) / 2
        )
        gap_threshold = max(median_gap * _GAP_OUTLIER_RATIO, avg_h * 0.25)
    else:
        gap_threshold = avg_h * _WORD_GAP_RATIO

    clusters: list[list[tuple[str, tuple[float, float, float, float]]]] = [[word_boxes[0]]]
    for i, gap in enumerate(gaps, start=1):
        if gap > gap_threshold:
            clusters.append([])
        clusters[-1].append(word_boxes[i])

    clusters = _split_trailing_icon_tokens(clusters)

    merged = []
    for cluster in clusters:
        words = [w for w, _ in cluster]
        boxes = [b for _, b in cluster]
        min_x = min(b[0] for b in boxes)
        min_y = min(b[1] for b in boxes)
        max_x = max(b[0] + b[2] for b in boxes)
        max_y = max(b[1] + b[3] for b in boxes)
        merged.append((" ".join(words), (min_x, min_y, max_x - min_x, max_y - min_y)))
    return merged


def recognize_text(image: "Vision.CGImageRef", min_confidence: float = 0.3) -> list[TextBlock]:
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise OcrError(f"Vision OCR request failed: {error}")

    blocks: list[TextBlock] = []
    for observation in request.results() or []:
        candidate = observation.topCandidates_(1).firstObject()
        if candidate is None:
            continue
        confidence = float(candidate.confidence())
        if confidence < min_confidence:
            continue

        text = str(candidate.string())
        line_rect = observation.boundingBox()
        line_box = (line_rect.origin.x, line_rect.origin.y, line_rect.size.width, line_rect.size.height)

        words = _word_spans(text)
        if len(words) <= 1:
            blocks.append(TextBlock(text=text, confidence=confidence, box=line_box))
            continue

        word_boxes = []
        for start, length, word in words:
            value, _error = candidate.boundingBoxForRange_error_(Foundation.NSRange(start, length), None)
            if value is None:
                word_boxes = None
                break
            rect = value.boundingBox()
            word_boxes.append((word, (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)))

        if not word_boxes:
            blocks.append(TextBlock(text=text, confidence=confidence, box=line_box))
            continue

        for merged_text, merged_box in _cluster_words(word_boxes):
            blocks.append(TextBlock(text=merged_text, confidence=confidence, box=merged_box))

    return blocks
