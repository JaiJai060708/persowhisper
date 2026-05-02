"""Global hotkey listener: detects 'taps' on a single key.

A tap = press + release of HOTKEY with no other key pressed in between, and
held for less than TAP_MAX_HOLD_MS. This lets the bare modifier still act as
a normal modifier (Cmd+Tab, Cmd+C, etc.) — only a clean tap toggles dictation.
"""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from pynput import keyboard

from .config import HOTKEY, TAP_MAX_HOLD_MS


class HotkeyListener:
    def __init__(
        self,
        on_tap: Callable[[], None],
        hotkey: keyboard.Key = HOTKEY,
    ) -> None:
        self._on_tap = on_tap
        self._hotkey = hotkey
        self._down_at: Optional[float] = None
        self._other_seen = False
        self._listener: Optional[keyboard.Listener] = None

    def _on_press(self, key):
        if key == self._hotkey:
            if self._down_at is None:
                self._down_at = time.monotonic()
                self._other_seen = False
        else:
            if self._down_at is not None:
                self._other_seen = True

    def _on_release(self, key):
        if key == self._hotkey and self._down_at is not None:
            held_ms = (time.monotonic() - self._down_at) * 1000.0
            other_seen = self._other_seen
            self._down_at = None
            self._other_seen = False
            if not other_seen and held_ms < TAP_MAX_HOLD_MS:
                try:
                    self._on_tap()
                except Exception as exc:
                    print(f"[listener] on_tap raised: {exc}", file=sys.stderr)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
