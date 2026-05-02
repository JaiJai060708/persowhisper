"""Menu-bar app + main entry point.

Wires together: hotkey listener → controller → overlay UI. The rumps timer
runs on the main thread and drives both the menu-bar icon and the overlay
panel's redraws.
"""

from __future__ import annotations

import sys
from typing import Optional

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

from .config import ICON_IDLE, UI_TICK_SEC, WHISPERX_BIN
from .controller import Controller
from .hotkey import HotkeyListener
from .overlay import Overlay
from .state import State
from .system import check_accessibility_trust


class PersoWhisperApp(rumps.App):
    def __init__(self, controller: Controller) -> None:
        super().__init__(ICON_IDLE, quit_button=None)
        self._controller = controller
        self._status_item = rumps.MenuItem("Status: idle")
        self.menu = [
            self._status_item,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self._overlay = Overlay()
        self._last_state: Optional[State] = None
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

    def _quit(self, _sender):
        rumps.quit_application()


def main() -> int:
    if not WHISPERX_BIN.exists():
        print(f"error: whisperx not found at {WHISPERX_BIN}", file=sys.stderr)
        return 1

    trusted = check_accessibility_trust(prompt=True)
    if trusted is False:
        print(
            "\nerror: this process lacks Accessibility permission.\n\n"
            "macOS just opened (or will open) a dialog pointing at\n"
            "  System Settings → Privacy & Security → Accessibility\n"
            "Enable the parent app you used to launch ./run.sh (Terminal,\n"
            "iTerm2, VS Code's integrated terminal, …), then *fully quit and\n"
            "relaunch* it before running this script again.\n",
            file=sys.stderr,
        )
        return 1

    controller = Controller()
    listener = HotkeyListener(on_tap=controller.on_tap)
    listener.start()

    app = PersoWhisperApp(controller)
    # Accessory policy: no Dock icon, no Cmd+Tab entry, never steals key
    # focus from the foreground app — so the synthetic Cmd+V at paste time
    # lands in whatever text field the user is currently in.
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )
    print(
        "PersoWhisper running. Tap right Cmd to start/stop dictation.",
        file=sys.stderr,
    )
    app.run()
    return 0
