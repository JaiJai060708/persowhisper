"""Persistent runtime settings (currently: which whisperx model to use).

A small JSON file at SETTINGS_PATH carries selections across restarts. The
module exposes a singleton `SETTINGS` so the controller, the transcribe
function and the menu bar all read/write the same place.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Optional

from .config import AVAILABLE_MODELS, DEFAULT_MODEL, SETTINGS_PATH


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = DEFAULT_MODEL
        self._hf_token_file: Optional[str] = None
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
        t = data.get("hf_token")
        if isinstance(t, str) and t.strip():
            self._hf_token_file = t.strip()

    def _save(self) -> None:
        payload: dict[str, str] = {"model": self._model}
        if self._hf_token_file:
            payload["hf_token"] = self._hf_token_file
        try:
            SETTINGS_PATH.write_text(json.dumps(payload, indent=2))
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

    @property
    def hf_token(self) -> Optional[str]:
        """HF token resolved from env var first, then ~/.persowhisper.json."""
        env = (
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or os.environ.get("HUGGINGFACE_TOKEN")
        )
        if env and env.strip():
            return env.strip()
        with self._lock:
            return self._hf_token_file


SETTINGS = Settings()
