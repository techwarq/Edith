from __future__ import annotations

from typing import Optional

import Quartz


class ScreenCaptureError(Exception):
    pass


def capture_window(frame: tuple[float, float, float, float]) -> "Quartz.CGImageRef":
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


WIDGET_BUNDLE_ID = "com.edith.widget"


def _widget_window_id() -> Optional[int]:
    import AppKit

    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []:
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(w.get("kCGWindowOwnerPID", 0)))
        if app is not None and app.bundleIdentifier() == WIDGET_BUNDLE_ID:
            return int(w.get("kCGWindowNumber"))
    return None


def main_display_bounds() -> tuple[float, float, float, float]:
    b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return (b.origin.x, b.origin.y, b.size.width, b.size.height)


def capture_screen_jpeg(max_pixels: int = 1440, quality: float = 0.7) -> tuple[bytes, tuple[int, int]]:
    x, y, w, h = main_display_bounds()
    rect = Quartz.CGRectMake(x, y, w, h)
    widget_id = _widget_window_id()
    if widget_id is not None:
        image = Quartz.CGWindowListCreateImage(
            rect, Quartz.kCGWindowListOptionOnScreenBelowWindow, widget_id, Quartz.kCGWindowImageDefault
        )
    else:
        image = Quartz.CGWindowListCreateImage(
            rect, Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault
        )
    if image is None:
        raise ScreenCaptureError(
            "screen capture returned nothing — check Screen Recording permission "
            "in System Settings > Privacy & Security > Screen Recording."
        )

    src_w, src_h = image_size(image)
    scale = min(1.0, max_pixels / max(src_w, src_h))
    out_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))

    data = Quartz.CFDataCreateMutable(None, 0)
    dest = Quartz.CGImageDestinationCreateWithData(data, "public.jpeg", 1, None)
    Quartz.CGImageDestinationAddImage(
        dest,
        image,
        {
            Quartz.kCGImageDestinationLossyCompressionQuality: quality,
            Quartz.kCGImageDestinationImageMaxPixelSize: max(out_size),
        },
    )
    if not Quartz.CGImageDestinationFinalize(dest):
        raise ScreenCaptureError("couldn't encode the screenshot as JPEG")
    return bytes(data), out_size
