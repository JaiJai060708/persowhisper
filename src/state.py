"""State enum shared by the controller and the UI."""

from enum import Enum

from .config import ICON_IDLE, ICON_RECORDING, ICON_TRANSCRIBING


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"

    @property
    def icon(self) -> str:
        return {
            State.IDLE: ICON_IDLE,
            State.RECORDING: ICON_RECORDING,
            State.TRANSCRIBING: ICON_TRANSCRIBING,
        }[self]
