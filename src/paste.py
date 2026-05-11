"""Paste a string into the focused text field via clipboard + osascript Cmd+V.

osascript runs in its own subprocess so any failure (e.g. missing Automation
permission for 'System Events') stays contained — unlike pynput's CGEventPost
path, which can SIGTRAP this process on recent macOS releases when posting
fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

from AppKit import (
    NSApplicationActivateIgnoringOtherApps,
    NSRunningApplication,
    NSWorkspace,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

from .config import PASTE_RESTORE_DELAY_SEC
from .system import check_accessibility_trust


_OSASCRIPT_PASTE = (
    'tell application "System Events" to keystroke "v" using {command down}'
)
_OSASCRIPT_TARGETED_PASTE = """
on run argv
    set targetPid to (item 1 of argv) as integer
    set targetBundle to item 2 of argv
    if targetBundle is not "" then
        try
            tell application id targetBundle to activate
        end try
    end if
    delay 0.12
    tell application "System Events"
        set targetProc to first application process whose unix id is targetPid
        set frontmost of targetProc to true
        delay 0.12
        key code 9 using {command down}
    end tell
end run
"""
_OSASCRIPT_FRONTMOST_APP = (
    'tell application "System Events" to unix id of first application process whose frontmost is true'
)

KEY_CODE_V = 9


@dataclass(frozen=True)
class PasteTarget:
    pid: int
    bundle_id: Optional[str]
    name: Optional[str]


def capture_paste_target() -> Optional[PasteTarget]:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        if pid == os.getpid():
            return None
        bundle_id = app.bundleIdentifier()
        name = app.localizedName()
        target = PasteTarget(
            pid=pid,
            bundle_id=str(bundle_id) if bundle_id else None,
            name=str(name) if name else None,
        )
        print(f"[paste] captured target: {target}", file=sys.stderr)
        return target
    except Exception as exc:
        print(f"[paste] could not capture frontmost app: {exc}", file=sys.stderr)
        return None


def _activate_target(target: Optional[PasteTarget]) -> bool:
    if target is None:
        return False
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(target.pid)
        if app is None:
            print(
                f"[paste] target app is no longer running: {target}",
                file=sys.stderr,
            )
            return False
        ok = bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
        # Give macOS a breath to make the target app key before System Events
        # sends Cmd+V. Without this, the keystroke can land in PersoWhisper.
        time.sleep(0.30)
        frontmost = _frontmost_pid()
        print(
            f"[paste] activated target={target.pid} ok={ok} frontmost={frontmost}",
            file=sys.stderr,
        )
        return ok
    except Exception as exc:
        print(f"[paste] could not activate target app {target}: {exc}", file=sys.stderr)
        return False


def _frontmost_pid() -> Optional[int]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", _OSASCRIPT_FRONTMOST_APP],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode != 0:
            return None
        return int((proc.stdout or "").strip())
    except Exception:
        return None


def _post_cmd_v_quartz() -> bool:
    try:
        down = CGEventCreateKeyboardEvent(None, KEY_CODE_V, True)
        up = CGEventCreateKeyboardEvent(None, KEY_CODE_V, False)
        if down is None or up is None:
            return False
        CGEventSetFlags(down, kCGEventFlagMaskCommand)
        CGEventSetFlags(up, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, down)
        time.sleep(0.02)
        CGEventPost(kCGHIDEventTap, up)
        return True
    except Exception as exc:
        print(f"[paste] Quartz Cmd+V failed: {exc}", file=sys.stderr)
        return False


def _quartz_paste_allowed(*, log_unavailable: bool = True) -> bool:
    trusted = check_accessibility_trust(prompt=False)
    if trusted is False:
        if log_unavailable:
            print(
                "[paste] Quartz Cmd+V unavailable: enable Accessibility "
                "for PersoWhisper, then fully quit and relaunch it.",
                file=sys.stderr,
            )
        return False
    return True


def _run_paste_script(target: Optional[PasteTarget]) -> subprocess.CompletedProcess:
    if target is None:
        return subprocess.run(
            ["osascript", "-e", _OSASCRIPT_PASTE],
            capture_output=True,
            text=True,
            timeout=5,
        )
    return subprocess.run(
        [
            "osascript",
            "-e",
            _OSASCRIPT_TARGETED_PASTE,
            str(target.pid),
            target.bundle_id or "",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )


def paste(
    text: str,
    *,
    cancel_requested: Optional[Callable[[], bool]] = None,
    target: Optional[PasteTarget] = None,
) -> bool:
    def is_cancelled() -> bool:
        if cancel_requested is None:
            return False
        try:
            return bool(cancel_requested())
        except Exception as exc:
            print(f"[paste] cancel_requested raised: {exc}", file=sys.stderr)
            return False

    if not text:
        return False

    if is_cancelled():
        return False

    try:
        prev = subprocess.check_output(["pbpaste"])
    except Exception:
        prev = b""

    copied = False
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        copied = True
    except Exception as exc:
        print(f"[paste] pbcopy failed: {exc}", file=sys.stderr)
        return False

    time.sleep(0.05)
    if is_cancelled():
        try:
            subprocess.run(["pbcopy"], input=prev, check=True)
        except Exception:
            pass
        return False

    _activate_target(target)
    if is_cancelled():
        try:
            subprocess.run(["pbcopy"], input=prev, check=True)
        except Exception:
            pass
        return False

    pasted = False
    tried_quartz = False
    if _quartz_paste_allowed(log_unavailable=False):
        tried_quartz = True
        pasted = _post_cmd_v_quartz()

    try:
        if not pasted:
            proc = _run_paste_script(target)
            if proc.returncode != 0:
                print(
                    f"[paste] osascript paste failed (rc={proc.returncode}): "
                    f"{(proc.stderr or '').strip()}",
                    file=sys.stderr,
                )
            else:
                pasted = True
    except Exception as exc:
        print(
            f"[paste] osascript paste failed: {exc}",
            file=sys.stderr,
        )
    if (
        not pasted
        and not tried_quartz
        and _quartz_paste_allowed(log_unavailable=True)
    ):
        pasted = _post_cmd_v_quartz()

    time.sleep(PASTE_RESTORE_DELAY_SEC)
    if copied:
        try:
            subprocess.run(["pbcopy"], input=prev, check=True)
        except Exception:
            pass
    return pasted
