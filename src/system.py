"""Thin wrappers over OS-level helpers: sounds, notifications, accessibility."""

from __future__ import annotations

import subprocess
from typing import Optional


def play(path: str) -> None:
    """Play a system sound asynchronously via afplay."""
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def notify(title: str, message: str) -> None:
    """User-facing notification via osascript.

    Avoids rumps.notification, which crashes when the script is not bundled
    (no Info.plist / bundle id) on macOS 11+.
    """
    try:
        t = title.replace("\\", "\\\\").replace('"', '\\"')
        m = message.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(
            ["osascript", "-e", f'display notification "{m}" with title "{t}"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def check_accessibility_trust(prompt: bool = True) -> Optional[bool]:
    """Return True/False if Accessibility trust status can be determined,
    or None if the API isn't available.

    With prompt=True, macOS shows its 'Open System Settings' dialog and adds
    the parent app to the Accessibility list automatically.
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except ImportError:
        try:
            from HIServices import (  # type: ignore
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
        except ImportError:
            return None
    options = {kAXTrustedCheckOptionPrompt: bool(prompt)}
    return bool(AXIsProcessTrustedWithOptions(options))
