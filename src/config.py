"""Tunable constants. Edit these to change hotkey, model, sizes, sounds, etc."""

from pathlib import Path

from pynput import keyboard


# --- Paths -------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
WHISPERX_BIN = PROJECT_DIR / "whisperx-env" / "bin" / "whisperx"


# --- Hotkey ------------------------------------------------------------------

HOTKEY = keyboard.Key.cmd_r
TAP_MAX_HOLD_MS = 800


# --- Recording ---------------------------------------------------------------

SAMPLE_RATE = 16_000
MIN_RECORDING_SEC = 0.3
MAX_RECORDING_SEC = 5 * 60


# --- Transcription -----------------------------------------------------------

WHISPERX_MODEL = "large-v3"


# --- Paste -------------------------------------------------------------------

PASTE_RESTORE_DELAY_SEC = 0.4


# --- Menu bar icons ----------------------------------------------------------

ICON_IDLE = "\U0001F399"          # studio microphone
ICON_RECORDING = "\U0001F534"     # red circle
ICON_TRANSCRIBING = "⏳"      # hourglass


# --- Sounds ------------------------------------------------------------------

SOUND_START = "/System/Library/Sounds/Tink.aiff"
SOUND_STOP = "/System/Library/Sounds/Pop.aiff"
SOUND_DONE = "/System/Library/Sounds/Glass.aiff"
SOUND_BUSY = "/System/Library/Sounds/Funk.aiff"
SOUND_ERR = "/System/Library/Sounds/Basso.aiff"


# --- Overlay -----------------------------------------------------------------

OVERLAY_WIDTH = 340.0
OVERLAY_HEIGHT = 88.0
OVERLAY_BOTTOM_MARGIN = 90.0
WAVE_HISTORY = 80
LEVEL_GAIN = 4.0


# --- Main loop ---------------------------------------------------------------

UI_TICK_SEC = 0.05
