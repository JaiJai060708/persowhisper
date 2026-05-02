"""Paste a string into the focused text field via clipboard + osascript Cmd+V.

osascript runs in its own subprocess so any failure (e.g. missing Automation
permission for 'System Events') stays contained — unlike pynput's CGEventPost
path, which can SIGTRAP this process on recent macOS releases when posting
fails.
"""

from __future__ import annotations

import subprocess
import sys
import time

from .config import PASTE_RESTORE_DELAY_SEC


_OSASCRIPT_PASTE = (
    'tell application "System Events" to keystroke "v" using {command down}'
)


def paste(text: str) -> None:
    if not text:
        return

    try:
        prev = subprocess.check_output(["pbpaste"])
    except Exception:
        prev = b""

    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    except Exception as exc:
        print(f"[paste] pbcopy failed: {exc}", file=sys.stderr)
        return

    time.sleep(0.05)
    try:
        proc = subprocess.run(
            ["osascript", "-e", _OSASCRIPT_PASTE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            print(
                f"[paste] osascript paste failed (rc={proc.returncode}): "
                f"{(proc.stderr or '').strip()}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"[paste] osascript paste failed: {exc}", file=sys.stderr)

    time.sleep(PASTE_RESTORE_DELAY_SEC)
    try:
        subprocess.run(["pbcopy"], input=prev, check=True)
    except Exception:
        pass
