"""Thin wrappers over OS-level helpers: sounds, notifications, accessibility."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
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


def accessibility_identity_summary() -> str:
    """Describe the process identity macOS uses for Accessibility decisions."""
    parts = [
        f"executable={sys.executable}",
    ]
    try:
        parts.append(f"resolved_executable={Path(sys.executable).resolve()}")
    except Exception:
        pass

    code_target = sys.executable
    try:
        from AppKit import NSBundle

        bundle = NSBundle.mainBundle()
        bundle_id = bundle.bundleIdentifier()
        bundle_path = bundle.bundlePath()
        if bundle_id:
            parts.append(f"bundle_id={bundle_id}")
        if bundle_path:
            code_target = str(bundle_path)
            parts.append(f"bundle_path={bundle_path}")
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["codesign", "-d", "-r-", code_target],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = "\n".join(
            line.strip()
            for line in (proc.stdout + proc.stderr).splitlines()
            if line.strip().startswith("designated =>")
            or line.strip().startswith("# designated =>")
        )
        if output:
            parts.append(output.replace("\n", " "))
    except Exception:
        pass

    return "; ".join(parts)
