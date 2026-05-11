"""Global hotkey listener: detects dictation taps and cancellation.

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
        on_cancel: Optional[Callable[[], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        hotkey: keyboard.Key = HOTKEY,
        cancel_key: keyboard.Key = keyboard.Key.esc,
    ) -> None:
        self._on_tap = on_tap
        self._on_cancel = on_cancel
        self._should_cancel = should_cancel
        self._hotkey = hotkey
        self._cancel_key = cancel_key
        self._down_at: Optional[float] = None
        self._other_seen = False
        self._cancel_down = False
        self._listener: Optional[keyboard.Listener] = None

    def _is_cancel_key(self, key) -> bool:
        if key == self._cancel_key:
            return True
        cancel_value = getattr(self._cancel_key, "value", None)
        if cancel_value is not None and key == cancel_value:
            return True
        if getattr(key, "char", None) == "\x1b":
            return True
        cancel_vk = getattr(cancel_value, "vk", None)
        key_vk = getattr(key, "vk", None)
        return cancel_vk is not None and key_vk == cancel_vk

    def _can_cancel(self) -> bool:
        if self._on_cancel is None:
            return False
        if self._should_cancel is None:
            return True
        try:
            return bool(self._should_cancel())
        except Exception as exc:
            print(f"[listener] should_cancel raised: {exc}", file=sys.stderr)
            return True

    def _on_press(self, key):
        if self._is_cancel_key(key):
            if not self._cancel_down:
                self._cancel_down = True
                if self._down_at is not None:
                    self._other_seen = True
                if self._can_cancel():
                    try:
                        self._on_cancel()
                    except Exception as exc:
                        print(f"[listener] on_cancel raised: {exc}", file=sys.stderr)
            return

        if key == self._hotkey:
            if self._down_at is None:
                self._down_at = time.monotonic()
                self._other_seen = False
        else:
            if self._down_at is not None:
                self._other_seen = True

    def _on_release(self, key):
        if self._is_cancel_key(key):
            self._cancel_down = False
            return

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
