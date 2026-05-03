"""Menu-bar app + main entry point.

Wires together: hotkey listener → controller → overlay UI. The rumps timer
runs on the main thread and drives both the menu-bar icon and the overlay
panel's redraws.
"""

from __future__ import annotations

import sys
from typing import Optional

from .log_stream import install_stdio_bridge

install_stdio_bridge()

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyRegular

from .config import ICON_IDLE, UI_TICK_SEC, WHISPERX_BIN
from .controller import Controller
from .drop_window import DropWindowController
from .file_job import FileJobController
from .hotkey import HotkeyListener
from .overlay import Overlay
from .state import State
from .system import check_accessibility_trust


class PersoWhisperApp(rumps.App):
    def __init__(self, controller: Controller) -> None:
        super().__init__(ICON_IDLE, quit_button=None)
        self._controller = controller
        self._file_job = FileJobController()
        self._drop_window = DropWindowController.alloc().initWithFileJob_(self._file_job)
        self._file_job.attach_window(self._drop_window)
        self._status_item = rumps.MenuItem("Status: idle")
        self._new_file_item = rumps.MenuItem(
            "New transcription from file…", callback=self._on_new_file
        )
        self._show_window_item = rumps.MenuItem(
            "Show window", callback=self._on_show_window
        )
        self.menu = [
            self._show_window_item,
            self._new_file_item,
            None,
            self._status_item,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self._overlay = Overlay()
        self._last_state: Optional[State] = None
        self._last_file_busy: Optional[bool] = None
        self._poll_timer = rumps.Timer(self._sync_ui, UI_TICK_SEC)
        self._poll_timer.start()

    def _sync_ui(self, _timer):
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

    def _quit(self, _sender):
        rumps.quit_application()


def main() -> int:
    if not WHISPERX_BIN.exists():
        print(f"error: whisperx not found at {WHISPERX_BIN}", file=sys.stderr)
        return 1

    trusted = check_accessibility_trust(prompt=True)
    if trusted is False:
        print(
            "\nwarning: this process lacks Accessibility permission.\n\n"
            "macOS just opened (or will open) a dialog pointing at\n"
            "  System Settings → Privacy & Security → Accessibility\n"
            "Enable PersoWhisper, then *fully quit and relaunch* it before\n"
            "using the global right-Cmd dictation hotkey.\n",
            file=sys.stderr,
        )

    controller = Controller()
    listener: Optional[HotkeyListener] = None
    if trusted is not False:
        listener = HotkeyListener(on_tap=controller.on_tap)
        listener.start()

    app = PersoWhisperApp(controller)
    # Regular policy: app appears in the Dock and Cmd+Tab. The drag-and-drop
    # window is the primary surface; the menu bar icon stays as a secondary
    # control. Dictation paste still works because right Cmd is captured by
    # a global pynput listener — the synthetic Cmd+V lands in whichever app
    # has focus when the user releases the hotkey.
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )
    app._drop_window.show()
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
