"""Persistent runtime settings (currently: which whisperx model to use).

A small JSON file at SETTINGS_PATH carries selections across restarts. The
module exposes a singleton `SETTINGS` so the controller, the transcribe
function and the menu bar all read/write the same place.
"""

from __future__ import annotations

import json
import sys
import threading

from .config import AVAILABLE_MODELS, DEFAULT_MODEL, SETTINGS_PATH


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = DEFAULT_MODEL
        self._load()

    def _load(self) -> None:
        try:
            raw = SETTINGS_PATH.read_text()
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[settings] failed to read {SETTINGS_PATH}: {exc}", file=sys.stderr)
            return
        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[settings] failed to parse {SETTINGS_PATH}: {exc}", file=sys.stderr)
            return
        m = data.get("model")
        if m in AVAILABLE_MODELS:
            self._model = m

    def _save(self) -> None:
        try:
            SETTINGS_PATH.write_text(json.dumps({"model": self._model}, indent=2))
        except Exception as exc:
            print(f"[settings] failed to save {SETTINGS_PATH}: {exc}", file=sys.stderr)

    @property
    def model(self) -> str:
        with self._lock:
            return self._model

    def set_model(self, value: str) -> bool:
        """Update the selected model. Returns True if it changed."""
        if value not in AVAILABLE_MODELS:
            return False
        with self._lock:
            if value == self._model:
                return False
            self._model = value
        self._save()
        return True


SETTINGS = Settings()
