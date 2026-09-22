"""Screen capture via Quartz's window-server APIs — no third-party library.
Needs macOS Screen Recording permission (System Settings > Privacy &
Security > Screen Recording) granted to whatever process runs this; without
it, CGWindowListCreateImage returns a black/empty image rather than raising,
so callers should treat an all-black capture as a permission problem.
"""

from __future__ import annotations

from typing import Optional

import Quartz


class ScreenCaptureError(Exception):
    pass


def capture_window(frame: tuple[float, float, float, float]) -> "Quartz.CGImageRef":
    """Captures the screen region `frame` (x, y, w, h) in the global
    (top-left-origin) coordinate space AXUIElement frames already use."""
    x, y, w, h = frame
    rect = Quartz.CGRectMake(x, y, w, h)
    image = Quartz.CGWindowListCreateImage(
        rect,
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
        Quartz.kCGWindowImageDefault,
    )
    if image is None:
        raise ScreenCaptureError(
            "screen capture returned nothing — check Screen Recording permission "
            "in System Settings > Privacy & Security > Screen Recording."
        )
    return image


def image_size(image: "Quartz.CGImageRef") -> tuple[int, int]:
    return int(Quartz.CGImageGetWidth(image)), int(Quartz.CGImageGetHeight(image))
