"""macOS Accessibility (AXUIElement) access, written directly against the
PyObjC bindings for Apple's own ApplicationServices/Cocoa/Quartz frameworks —
no third-party computer-use library. Everything the perceive/decide/act loop
needs to read the screen and act on it lives here: running apps and windows,
a bounded walk of one window's element tree, and click/type/press/activate.

Unlike a subprocess-based tool, elements stay as live AXUIElementRef objects
in memory for the lifetime of one loop run — there is no token-serialization
problem to solve, since nothing crosses a process boundary.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import AppKit
import ApplicationServices as AX
import Quartz

# Roles worth surfacing to the decision model — containers (groups, scroll
# areas, splitters, ...) are walked through but never offered as targets.
ACTIONABLE_ROLES = frozenset(
    {
        "AXButton",
        "AXLink",
        "AXCheckBox",
        "AXRadioButton",
        "AXMenuItem",
        "AXMenuButton",
        "AXPopUpButton",
        "AXTextField",
        "AXTextArea",
        "AXComboBox",
        "AXTab",
        "AXSlider",
        "AXSwitch",
        "AXDisclosureTriangle",
        "AXCell",
    }
)
EDITABLE_ROLES = frozenset({"AXTextField", "AXTextArea", "AXComboBox"})
# Window-chrome buttons (traffic lights) — never a legitimate click target for
# a goal, and a synthetic click landing on one is how a whole window
# disappears out from under the loop.
WINDOW_CHROME_SUBROLES = frozenset({"AXCloseButton", "AXMinimizeButton", "AXZoomButton", "AXFullScreenButton"})
# Defense in depth for the same failure mode where the control isn't a real
# traffic-light button but a web/tab-strip "Close" that reports no subrole —
# exact-match only, so this can't accidentally hide unrelated content that
# merely contains the word (e.g. a "Close friends" list item).
BLOCKED_LABELS = frozenset({"close", "close tab", "close window", "minimize", "minimize window"})

MAX_ELEMENTS = 80
MAX_DEPTH = 12
MAX_CHILDREN_PER_NODE = 60
MAX_NODES_VISITED = 3000  # a big Chromium/Electron tree can have tens of thousands of nodes
WALK_TIME_BUDGET_SECONDS = 1.5
# Roles whose own label should be inherited by an unlabeled child one level down — a bare
# decorative AXImage inside an AXButton, not a separate control in its own right.
LABEL_PARENT_ROLES = frozenset({"AXButton", "AXCell", "AXCheckBox", "AXLink", "AXMenuButton", "AXPopUpButton", "AXRadioButton", "AXRow", "AXTab"})
# List/table rows keep their label in a shallow AXStaticText child rather than on themselves.
LABEL_DESCENDANT_ROLES = frozenset({"AXCell", "AXRow"})
MIN_CLICKABLE_SIDE = 4.0
# A real content window is never this thin — anything shorter/narrower is a
# toolbar/findbar/notification-bar sliver, not something a goal ever targets.
MIN_WINDOW_SIDE = 100.0


class AccessibilityError(Exception):
    pass


def is_trusted() -> bool:
    return bool(AX.AXIsProcessTrusted())


def request_trust() -> bool:
    """Triggers the system Accessibility permission dialog if not already
    granted. Returns the current (pre-grant) trust state — macOS never grants
    synchronously, the user has to click through System Settings."""
    return bool(AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True}))


def _require_trust() -> None:
    if not is_trusted():
        raise AccessibilityError(
            "Accessibility permission hasn't been granted to this process. "
            "Grant it in System Settings > Privacy & Security > Accessibility."
        )


def _attr(element: Any, name: str) -> Any:
    err, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None


def _set_attr(element: Any, name: str, value: Any) -> bool:
    return AX.AXUIElementSetAttributeValue(element, name, value) == 0


def _perform(element: Any, action: str) -> bool:
    return AX.AXUIElementPerformAction(element, action) == 0


def _point(value: Any) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    ok, pt = AX.AXValueGetValue(value, AX.kAXValueCGPointType, None)
    return (pt.x, pt.y) if ok else None


def _size(value: Any) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    ok, sz = AX.AXValueGetValue(value, AX.kAXValueCGSizeType, None)
    return (sz.width, sz.height) if ok else None


@dataclass(frozen=True)
class AppInfo:
    pid: int
    name: str
    bundle_id: str
    active: bool


def running_apps() -> list[AppInfo]:
    """NSWorkspace-level — no Accessibility permission required."""
    apps = []
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.activationPolicy() != AppKit.NSApplicationActivationPolicyRegular:
            continue  # skip background/UI-less processes — not something a goal would ever target
        apps.append(
            AppInfo(
                pid=app.processIdentifier(),
                name=app.localizedName() or "",
                bundle_id=app.bundleIdentifier() or "",
                active=bool(app.isActive()),
            )
        )
    return apps


def launch_app(name: str, timeout: float = 15.0) -> bool:
    """Launches an app that isn't running yet, via macOS's own `open -a` —
    the same mechanism Finder/Spotlight use to open an app by name, so no
    knowledge of its bundle path is needed. `open` returns as soon as the
    launch request is *accepted*, well before the app has actually started
    and drawn a window, so this polls running_apps()/_has_onscreen_windows
    until it's really up rather than trusting the command's return alone.
    Generous default timeout — a cold Electron-app start (Slack, Spotify)
    restoring its last session can genuinely take 10+ seconds.

    Confirmed live: an app that restores its window on a different Space
    (or otherwise starts non-frontmost) can fail to show up under
    kCGWindowListOptionOnScreenOnly even once its window is real and fully
    drawn. activate_app is what surfaces it — but a single early call (the
    moment the process first appears, before it's created any window at
    all) doesn't reliably stick once the window shows up moments later;
    only a fresh activate_app call issued *after* the window exists
    reliably brings it onscreen. So this nudges periodically while
    waiting, not just once."""
    try:
        subprocess.run(["open", "-a", name], check=True, capture_output=True, timeout=5)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False

    deadline = time.monotonic() + timeout
    next_activate = 0.0
    activate_interval = 1.5
    while time.monotonic() < deadline:
        app = next((a for a in running_apps() if a.name.lower() == name.lower()), None)
        if app is not None:
            if _has_onscreen_windows(app.pid):
                return True
            now = time.monotonic()
            if now >= next_activate:
                activate_app(app.pid)
                next_activate = now + activate_interval
        time.sleep(0.2)
    return False


def activate_app(pid: int, timeout: float = 2.0) -> bool:
    """AppleScript's `activate` command, not NSRunningApplication directly —
    activateWithOptions_ proved unreliable when called from a bare Python
    subprocess (no real window/focus of its own to hand off from), the same
    reason a real automation tool goes through the scripting bridge instead.
    Polls NSWorkspace's frontmostApplication for confirmation afterward,
    since activation is asynchronous either way."""
    running = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if running is None:
        return False
    name = (running.localizedName() or "").replace('"', '\\"')
    if name:
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{name}" to activate'],
                check=True,
                capture_output=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    else:
        running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None and front.processIdentifier() == pid:
            return True
        time.sleep(0.05)
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return front is not None and front.processIdentifier() == pid


@dataclass(frozen=True)
class WindowInfo:
    element: Any
    title: str
    main: bool
    minimized: bool
    frame: Optional[tuple[float, float, float, float]]  # x, y, w, h


def _has_onscreen_windows(pid: int) -> bool:
    """Ground truth from the window server, not the AX bridge — used only to
    decide whether kAXWindowsAttribute coming back empty is worth retrying
    (real flakiness) or correct (the app genuinely has no windows)."""
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for w in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
            return True
    return False


def windows(pid: int, retries: int = 3, retry_delay: float = 0.15) -> list[WindowInfo]:
    """kAXWindowsAttribute has observed transient flakiness — reporting zero
    windows for an app that (per the window server, checked independently)
    genuinely has some on screen — so an empty first read is retried a few
    times before being trusted, rather than treated as ground truth."""
    _require_trust()
    app_element = AX.AXUIElementCreateApplication(pid)
    AX.AXUIElementSetMessagingTimeout(app_element, 0.3)  # bound one slow/hung call instead of stalling the loop

    raw_windows = _attr(app_element, AX.kAXWindowsAttribute) or []
    attempt = 0
    while not raw_windows and attempt < retries and _has_onscreen_windows(pid):
        time.sleep(retry_delay)
        raw_windows = _attr(app_element, AX.kAXWindowsAttribute) or []
        attempt += 1

    result = []
    for w in raw_windows:
        # kAXWindowsAttribute has been observed (Brave/Chromium) to include
        # elements that aren't real windows at all — a toolbar/findbar
        # sliver a few dozen points tall, even a stray AXHelpTag tooltip —
        # which would otherwise get offered as a pin/disambiguation target
        # indistinguishable from the actual browser window.
        if _attr(w, AX.kAXRoleAttribute) != AX.kAXWindowRole:
            continue
        pos = _point(_attr(w, AX.kAXPositionAttribute))
        size = _size(_attr(w, AX.kAXSizeAttribute))
        frame = (pos[0], pos[1], size[0], size[1]) if pos and size else None
        if frame is not None and min(frame[2], frame[3]) < MIN_WINDOW_SIDE:
            continue
        result.append(
            WindowInfo(
                element=w,
                title=_attr(w, AX.kAXTitleAttribute) or "",
                main=bool(_attr(w, AX.kAXMainAttribute)),
                minimized=bool(_attr(w, AX.kAXMinimizedAttribute)),
                frame=frame,
            )
        )
    return result


@dataclass(frozen=True)
class PinnedWindow:
    """A single window locked in once at the start of a run. Every later
    step re-verifies against this exact AXUIElement (see refresh_pinned) —
    never against "whichever window happens to be frontmost right now",
    which is what let the loop drift onto the wrong window whenever the
    user's own activity, or the loop's own actions, changed what was
    frontmost mid-task."""

    id: str
    pid: int
    app_name: str
    bundle_id: str
    element: Any
    title_at_pin: str


def scriptable_window_titles(app_name: str) -> Optional[list[str]]:
    """Best-effort: apps with a real AppleScript window dictionary (browsers,
    Finder, Mail, ...) report every window's true title through their own
    scripting bridge, even for a background member of a native macOS
    window-tab group that the Accessibility API reports as a blank sliver
    until it's actually selected (see window_title). Returns None when the
    app doesn't support this — callers fall back to raw AX enumeration."""
    name = app_name.replace('"', '\\"')
    script = (
        f'tell application "{name}"\n'
        'set out to ""\n'
        "repeat with w in windows\n"
        "set out to out & (title of w) & linefeed\n"
        "end repeat\n"
        "return out\n"
        "end tell"
    )
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.split("\n") if line]


def select_scriptable_window(app_name: str, title: str) -> bool:
    """Selects a window by exact title, through the app's own scripting
    bridge — the general equivalent of clicking its native window-tab,
    which is what actually materializes it as a full AXWindow. AXRaise
    alone does not select a background member of a native macOS window-tab
    group; only the app itself (or a real click on the tab) does.

    Selects by title, not by the position returned from
    scriptable_window_titles — window z-order is live state that can shift
    between that read and this call (the user's own activity, another
    window losing focus), so a positional index resolved a moment ago can
    already point at a different window by the time this runs."""
    name = app_name.replace('"', '\\"')
    title_escaped = title.replace('"', '\\"')
    script = f'tell application "{name}" to set index of (first window whose title is "{title_escaped}") to 1'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return proc.returncode == 0


def window_title(window: WindowInfo, settle_seconds: float = 0.15) -> str:
    """Chromium/Electron apps only populate a background window's AX title
    (and other attributes) once it's raised — kAXTitleAttribute reads back
    empty for every window but the currently-focused one. Disambiguating
    windows by title therefore needs a brief raise-and-read rather than a
    cheap attribute read, or every background window looks identically
    blank."""
    if window.title:
        return window.title
    _perform(window.element, AX.kAXRaiseAction)
    time.sleep(settle_seconds)
    return _attr(window.element, AX.kAXTitleAttribute) or ""


def pin_window(app: AppInfo, window: WindowInfo) -> PinnedWindow:
    """Locks onto one already-chosen window, once. Nothing after this
    re-queries "what's frontmost" — later steps call
    refresh_pinned/raise_pinned against the returned element."""
    _perform(window.element, AX.kAXRaiseAction)
    return PinnedWindow(
        id=f"{app.bundle_id or app.name}:{app.pid}",
        pid=app.pid,
        app_name=app.name,
        bundle_id=app.bundle_id,
        element=window.element,
        title_at_pin=window_title(window),
    )


def refresh_pinned(pinned: PinnedWindow) -> Optional[WindowInfo]:
    """Ground truth for "is the window I locked onto still open" — matched
    by AX identity (CFEqual on the AXUIElementRef), not by title (which
    changes the moment the page navigates) and not by re-scanning for
    whatever's frontmost now. Returns None once the window is truly gone;
    callers must stop rather than hunt for a replacement."""
    for w in windows(pinned.pid):
        if AX.CFEqual(w.element, pinned.element):
            return w
    return None


def raise_pinned(pinned: PinnedWindow) -> None:
    """Brings the pinned window forward before each snapshot/action. This is
    an assertion ("THIS window is what I'm about to look at and act on"),
    not a "what's frontmost" read — both the OCR screenshot and synthetic
    clicks operate on absolute screen coordinates, which land on the wrong
    app if another window is on top."""
    activate_app(pinned.pid)
    _perform(pinned.element, AX.kAXRaiseAction)


def scroll(point: tuple[float, float], lines: int) -> None:
    """Synthetic scroll-wheel event at `point` (typically the pinned
    window's center) — positive `lines` scrolls up, negative scrolls down."""
    event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines)
    Quartz.CGEventSetLocation(event, point)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


@dataclass(frozen=True)
class ElementInfo:
    index: int
    element: Any
    role: str
    label: str
    frame: Optional[tuple[float, float, float, float]]
    editable: bool
    enabled: bool


def _own_label(element: Any) -> str:
    for attr in (AX.kAXTitleAttribute, AX.kAXDescriptionAttribute):
        value = _attr(element, attr)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
    value = _attr(element, AX.kAXValueAttribute)
    if isinstance(value, str) and 0 < len(value.strip()) <= 120:
        return " ".join(value.split())
    return ""


def _frame_of(node: Any) -> Optional[tuple[float, float, float, float]]:
    pos = _point(_attr(node, AX.kAXPositionAttribute))
    size = _size(_attr(node, AX.kAXSizeAttribute))
    return (pos[0], pos[1], size[0], size[1]) if pos and size else None


def _off_display(frame: Optional[tuple[float, float, float, float]], display_w: float, display_h: float) -> bool:
    """A real frame lying wholly outside the display is a background tab's
    stale layout or a node parked off-canvas — not something to offer as a
    click target. A frameless/zero-size node (a container) is never
    considered off-display; it still needs its subtree walked."""
    if frame is None:
        return False
    x, y, w, h = frame
    if w <= 0 or h <= 0:
        return False
    return x >= display_w or y >= display_h or x + w <= 0 or y + h <= 0


def _descendant_label(children: list, fanout: int = 8) -> str:
    """The first static text within two levels — where list rows/table cells
    usually hide their label instead of carrying it themselves."""
    for kid in children[:fanout]:
        if _attr(kid, AX.kAXRoleAttribute) == "AXStaticText":
            text = _own_label(kid)
            if text:
                return text
    for kid in children[:fanout]:
        grandkids = (_attr(kid, AX.kAXChildrenAttribute) or [])[:fanout]
        for grandkid in grandkids:
            if _attr(grandkid, AX.kAXRoleAttribute) == "AXStaticText":
                text = _own_label(grandkid)
                if text:
                    return text
    return ""


def walk_elements(window_element: Any, max_elements: int = MAX_ELEMENTS) -> list[ElementInfo]:
    """Breadth-first walk of one window's accessibility tree, bounded by node
    count and wall-clock time so a deeply nested app (a browser with dozens
    of tabs, an Electron app) can't stall the loop or flood the result with
    duplicates. Returns only actionable, on-screen elements — everything
    else is just structure.

    Two things a naive walk gets wrong on real apps, both fixed here:
    - The same control often appears more than once in the tree (a button
      wrapping an image that reports the same role/label/frame) — deduped by
      (role, label, rounded frame).
    - Many controls (icon buttons, list rows) report no label of their own —
      recovered from a labeled parent or a descendant AXStaticText, instead
      of showing up as a useless blank entry.
    """
    _require_trust()
    display_bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    display_w, display_h = display_bounds.size.width, display_bounds.size.height

    found: list[ElementInfo] = []
    seen_keys: set[tuple] = set()
    frontier: list[tuple[Any, str]] = [(window_element, "")]  # (node, inherited label)
    depth = 0
    visited = 0
    deadline = time.monotonic() + WALK_TIME_BUDGET_SECONDS

    while frontier and depth < MAX_DEPTH and len(found) < max_elements:
        if time.monotonic() >= deadline:
            break
        next_frontier: list[tuple[Any, str]] = []
        for node, parent_label in frontier:
            if visited >= MAX_NODES_VISITED or time.monotonic() >= deadline:
                break
            visited += 1

            role = _attr(node, AX.kAXRoleAttribute) or ""
            subrole = _attr(node, AX.kAXSubroleAttribute) or ""
            children = _attr(node, AX.kAXChildrenAttribute) or []
            own_label = _own_label(node)
            label = own_label
            if not label and role in LABEL_DESCENDANT_ROLES:
                label = _descendant_label(list(children))
            if not label and parent_label:
                label = parent_label

            frame = _frame_of(node)
            if (
                role in ACTIONABLE_ROLES
                and subrole not in WINDOW_CHROME_SUBROLES
                and label
                and label.strip().lower() not in BLOCKED_LABELS
                and not _off_display(frame, display_w, display_h)
                and (frame is None or min(frame[2], frame[3]) >= MIN_CLICKABLE_SIDE)
            ):
                key = (role, label, round(frame[0]) if frame else None, round(frame[1]) if frame else None)
                if key not in seen_keys:
                    seen_keys.add(key)
                    enabled = _attr(node, AX.kAXEnabledAttribute)
                    found.append(
                        ElementInfo(
                            index=len(found),
                            element=node,
                            role=role,
                            label=label,
                            frame=frame,
                            editable=role in EDITABLE_ROLES,
                            enabled=enabled is None or bool(enabled),
                        )
                    )
                    if len(found) >= max_elements:
                        break

            child_label = own_label if role in LABEL_PARENT_ROLES else ""
            next_frontier.extend((kid, child_label) for kid in list(children)[:MAX_CHILDREN_PER_NODE])
        frontier = next_frontier
        depth += 1
    return found


# --- actions -----------------------------------------------------------

def click(ax_element: Optional[Any], frame: Optional[tuple[float, float, float, float]]) -> str:
    """AXPress first (works for native buttons/links/menu items) when there's
    a real element to press; a synthetic mouse click at the frame's center
    otherwise — the only option for OCR-only items (perception.py), and a
    fallback for elements that don't implement AXPress (common in web
    content)."""
    if ax_element is not None and _perform(ax_element, AX.kAXPressAction):
        return "clicked"
    if not frame:
        raise AccessibilityError("item has no frame to click and doesn't support AXPress")
    x, y, w, h = frame
    _synthetic_click((x + w / 2, y + h / 2))
    return "clicked (synthetic)"


def _synthetic_click(point: tuple[float, float]) -> None:
    down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, point, Quartz.kCGMouseButtonLeft)
    up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, point, Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.03)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def set_text(ax_element: Optional[Any], frame: Optional[tuple[float, float, float, float]], text: str) -> str:
    """AXUIElementSetAttributeValue first (works for native text fields) when
    there's a real element; click-to-focus + synthetic keystrokes otherwise —
    the only option for OCR-only items, and a fallback for elements (mostly
    web content) that reject a direct value set."""
    if ax_element is not None and _set_attr(ax_element, AX.kAXValueAttribute, text):
        return "set value"
    click(ax_element, frame)
    time.sleep(0.1)
    type_text(text)
    return "typed (synthetic)"


def type_text(text: str) -> None:
    """Synthesizes keystrokes for arbitrary Unicode text via a single
    keyboard event pair — no per-character keycode mapping needed."""
    down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    Quartz.CGEventKeyboardSetUnicodeString(down, len(text), text)
    up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    Quartz.CGEventKeyboardSetUnicodeString(up, len(text), text)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31,
    "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "return": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
_MODIFIERS = {
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "command": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "opt": Quartz.kCGEventFlagMaskAlternate,
    "option": Quartz.kCGEventFlagMaskAlternate,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "ctrl": Quartz.kCGEventFlagMaskControl,
    "control": Quartz.kCGEventFlagMaskControl,
}


def press_key(combo: str) -> None:
    """Synthesizes a keyboard shortcut like 'cmd+l' or 'return' to whatever
    application is currently frontmost — matching how a real keypress works."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise AccessibilityError(f"empty key combination: {combo!r}")
    *mods, key = parts
    keycode = _KEYCODES.get(key)
    if keycode is None:
        raise AccessibilityError(f"unsupported key {key!r} in combo {combo!r}")
    flags = 0
    for mod in mods:
        flag = _MODIFIERS.get(mod)
        if flag is None:
            raise AccessibilityError(f"unsupported modifier {mod!r} in combo {combo!r}")
        flags |= flag

    down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        Quartz.CGEventSetFlags(down, flags)
        Quartz.CGEventSetFlags(up, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.02)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
