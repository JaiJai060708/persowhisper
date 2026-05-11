"""Menu-bar app + main entry point.

Wires together: hotkey listener → controller → overlay UI. The rumps timer
runs on the main thread and drives both the menu-bar icon and the overlay
panel's redraws.
"""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from .log_stream import install_stdio_bridge

install_stdio_bridge()

import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventModifierFlagCommand,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
    NSKeyDownMask,
)
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventSourceKeyState,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskCommand,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGEventSourceStateCombinedSessionState,
    kCGEventSourceStateHIDSystemState,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

from .config import ICON_IDLE, TAP_MAX_HOLD_MS, UI_TICK_SEC, WHISPERX_BIN
from .controller import Controller
from .drop_window import DropWindowController
from .file_job import FileJobController
from .hotkey import HotkeyListener
from .overlay import Overlay
from .state import State
from .system import accessibility_identity_summary, check_accessibility_trust


ESCAPE_KEY_CODE = 53
RIGHT_COMMAND_KEY_CODE = 54
KEY_EVENT_MASK = NSKeyDownMask | NSEventMaskFlagsChanged


class ModifierTapRecognizer:
    def __init__(
        self,
        *,
        key_code: int,
        on_tap,
        max_hold_ms: int = TAP_MAX_HOLD_MS,
        clock=time.monotonic,
    ) -> None:
        self._key_code = key_code
        self._on_tap = on_tap
        self._max_hold_ms = max_hold_ms
        self._clock = clock
        self._down_at: Optional[float] = None
        self._other_seen = False

    def flags_changed(self, key_code: int, is_down: Optional[bool] = None) -> None:
        if key_code == self._key_code:
            if self._down_at is None:
                if is_down is False:
                    return
                self._down_at = self._clock()
                self._other_seen = False
                return
            held_ms = (self._clock() - self._down_at) * 1000.0
            other_seen = self._other_seen
            self._down_at = None
            self._other_seen = False
            if not other_seen and held_ms < self._max_hold_ms:
                self._on_tap()
            return

        if self._down_at is not None:
            self._other_seen = True

    def key_down(self, key_code: int) -> None:
        if self._down_at is not None:
            self._other_seen = True


class QuartzKeyEventTap:
    def __init__(self, on_event: Callable[[int, int, Optional[bool]], None]) -> None:
        self._on_event = on_event
        self._tap = None
        self._source = None
        self._callback = self._handle_event

    def start(self) -> bool:
        mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventFlagsChanged)
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if self._tap is None:
            print(
                "[app] Quartz key event tap unavailable; using AppKit/pynput fallbacks",
                file=sys.stderr,
            )
            return False
        self._source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        if self._source is None:
            print(
                "[app] Quartz key event run-loop source unavailable; using fallbacks",
                file=sys.stderr,
            )
            return False
        CFRunLoopAddSource(CFRunLoopGetMain(), self._source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        return True

    def _handle_event(self, _proxy, event_type, event, _refcon):
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
            return event

        if event_type in (kCGEventKeyDown, kCGEventFlagsChanged):
            try:
                key_code = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
                flags = int(CGEventGetFlags(event))
                command_down = bool(flags & kCGEventFlagMaskCommand)
                self._on_event(int(event_type), key_code, command_down)
            except Exception as exc:
                print(f"[app] Quartz key event handler failed: {exc}", file=sys.stderr)
        return event


class PersoWhisperApp(rumps.App):
    def __init__(self, controller: Controller, accessibility_trusted: bool) -> None:
        super().__init__(ICON_IDLE, quit_button=None)
        self._controller = controller
        self._accessibility_trusted = accessibility_trusted
        self._file_job = FileJobController()
        self._drop_window = DropWindowController.alloc().initWithFileJob_(self._file_job)
        self._file_job.attach_window(self._drop_window)
        self._status_item = rumps.MenuItem("Status: idle")
        self._accessibility_item = rumps.MenuItem("")
        self._sync_accessibility_item()
        self._new_file_item = rumps.MenuItem(
            "New transcription from file…", callback=self._on_new_file
        )
        self._show_window_item = rumps.MenuItem(
            "Show window", callback=self._on_show_window
        )
        self.menu = [
            self._show_window_item,
            self._new_file_item,
            self._accessibility_item,
            None,
            self._status_item,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self._overlay = Overlay()
        self._last_state: Optional[State] = None
        self._last_file_busy: Optional[bool] = None
        self._escape_was_down = False
        self._right_cmd_tap = ModifierTapRecognizer(
            key_code=RIGHT_COMMAND_KEY_CODE,
            on_tap=self._controller.on_tap,
        )
        self._quartz_right_cmd_tap = ModifierTapRecognizer(
            key_code=RIGHT_COMMAND_KEY_CODE,
            on_tap=self._controller.on_tap,
        )
        self._quartz_key_tap = QuartzKeyEventTap(self._handle_quartz_key_event)
        self._quartz_key_tap.start()
        self._global_key_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            KEY_EVENT_MASK,
            self._on_global_key_event,
        )
        self._local_key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            KEY_EVENT_MASK,
            self._on_local_key_event,
        )
        self._poll_timer = rumps.Timer(self._sync_ui, UI_TICK_SEC)
        self._poll_timer.start()

    def _key_code(self, event) -> Optional[int]:
        try:
            return int(event.keyCode())
        except Exception:
            return None

    def _event_type(self, event) -> Optional[int]:
        try:
            return int(event.type())
        except Exception:
            return None

    def _command_is_down(self, event) -> Optional[bool]:
        try:
            return bool(int(event.modifierFlags()) & NSEventModifierFlagCommand)
        except Exception:
            return None

    def _handle_raw_key_event(
        self,
        event_type: Optional[int],
        key_code: Optional[int],
        command_is_down: Optional[bool],
        tap_recognizer: ModifierTapRecognizer,
    ) -> None:
        if key_code is None:
            return

        if event_type == NSEventTypeFlagsChanged:
            tap_recognizer.flags_changed(
                key_code,
                is_down=command_is_down,
            )
            return

        if event_type == NSEventTypeKeyDown:
            tap_recognizer.key_down(key_code)
            if key_code == ESCAPE_KEY_CODE and self._controller.can_cancel():
                self._controller.cancel()
                return

    def _handle_key_event(self, event) -> None:
        event_type = self._event_type(event)
        key_code = self._key_code(event)
        self._handle_raw_key_event(
            event_type,
            key_code,
            self._command_is_down(event),
            self._right_cmd_tap,
        )

    def _handle_quartz_key_event(
        self,
        event_type: int,
        key_code: int,
        command_is_down: Optional[bool],
    ) -> None:
        self._handle_raw_key_event(
            event_type,
            key_code,
            command_is_down,
            self._quartz_right_cmd_tap,
        )

    def _on_global_key_event(self, event) -> None:
        self._handle_key_event(event)

    def _on_local_key_event(self, event):
        self._handle_key_event(event)
        return event

    def _escape_key_is_down(self) -> bool:
        try:
            if CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, ESCAPE_KEY_CODE):
                return True
        except Exception:
            pass
        try:
            return bool(
                CGEventSourceKeyState(
                    kCGEventSourceStateCombinedSessionState,
                    ESCAPE_KEY_CODE,
                )
            )
        except Exception:
            return False

    def _poll_escape_cancel(self) -> None:
        escape_down = self._escape_key_is_down()
        if (
            escape_down
            and not self._escape_was_down
            and self._controller.can_cancel()
        ):
            self._controller.cancel()
        self._escape_was_down = escape_down

    def _accessibility_title(self) -> str:
        if self._accessibility_trusted:
            return "Accessibility: enabled"
        return "Request Accessibility permission…"

    def _sync_accessibility_item(self) -> None:
        self._accessibility_item.title = self._accessibility_title()
        self._accessibility_item.set_callback(
            None if self._accessibility_trusted else self._request_accessibility
        )

    def _sync_ui(self, _timer):
        self._poll_escape_cancel()
        s = self._controller.state
        new_title = s.icon
        if self.title != new_title:
            self.title = new_title
        new_status = f"Status: {s.value}"
        if self._status_item.title != new_status:
            self._status_item.title = new_status

        # Grey out the file-import item while either flow is busy.
        file_busy = self._file_job.is_busy() or s is State.TRANSCRIBING
        if file_busy != self._last_file_busy:
            self._new_file_item.set_callback(
                None if file_busy else self._on_new_file
            )
            self._drop_window.update_busy(file_busy)
            self._last_file_busy = file_busy

        if s is State.RECORDING:
            if self._last_state is not State.RECORDING:
                self._overlay.show("recording")
            self._overlay.push_level(self._controller.latest_level())
            self._overlay.tick()
        elif s is State.TRANSCRIBING:
            if self._last_state is not State.TRANSCRIBING:
                self._overlay.show("transcribing")
            self._overlay.tick()
        else:
            if self._last_state is not State.IDLE:
                self._overlay.hide()

        self._last_state = s

    def _on_new_file(self, _sender):
        self._file_job.start()

    def _on_show_window(self, _sender):
        self._drop_window.show()

    def _request_accessibility(self, _sender):
        trusted = check_accessibility_trust(prompt=True)
        self._accessibility_trusted = trusted is not False
        self._sync_accessibility_item()
        if trusted is False:
            self._drop_window.set_status(
                "Enable Accessibility for PersoWhisper, then relaunch for right-Cmd dictation."
            )
        else:
            self._drop_window.set_status(
                "Accessibility is enabled. Relaunch if right-Cmd was inactive."
            )

    def _quit(self, _sender):
        rumps.quit_application()


def main() -> int:
    if not WHISPERX_BIN.exists():
        print(f"error: whisperx not found at {WHISPERX_BIN}", file=sys.stderr)
        return 1

    trusted = check_accessibility_trust(prompt=False)
    if trusted is False:
        print(
            "\nwarning: this process lacks Accessibility permission.\n\n"
            "Open PersoWhisper's menu and choose\n"
            "  Request Accessibility permission…\n"
            "or enable PersoWhisper in System Settings → Privacy & Security\n"
            "→ Accessibility, then *fully quit and relaunch* it before using\n"
            "the global right-Cmd dictation hotkey.\n",
            file=sys.stderr,
        )
        print(
            f"[accessibility] {accessibility_identity_summary()}",
            file=sys.stderr,
        )

    controller = Controller()
    listener = HotkeyListener(
        on_tap=controller.on_tap,
        on_cancel=controller.cancel,
        should_cancel=controller.can_cancel,
    )
    listener.start()

    app = PersoWhisperApp(controller, accessibility_trusted=trusted is not False)
    # Regular policy: app appears in the Dock and Cmd+Tab. The drag-and-drop
    # window is the primary surface; the menu bar icon stays as a secondary
    # control. Dictation paste still works because right Cmd is captured by
    # a global pynput listener — the synthetic Cmd+V lands in whichever app
    # has focus when the user releases the hotkey.
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )
    if trusted is False:
        app._drop_window.set_status(
            "Enable Accessibility for PersoWhisper, then relaunch for right-Cmd dictation."
        )
    print(
        "PersoWhisper running. Tap right Cmd to dictate, or drop a file on the window.",
        file=sys.stderr,
    )
    app.run()
    return 0
