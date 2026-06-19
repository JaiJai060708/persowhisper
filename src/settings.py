"""Persistent runtime settings (currently: the Hugging Face token).

A small JSON file at SETTINGS_PATH carries values across restarts. The module
exposes a singleton `SETTINGS` so the controller, the transcribe function and
the file-import flow all read from the same place.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Optional

from .config import SETTINGS_PATH


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hf_token_file: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            raw = SETTINGS_PATH.read_text(encoding="utf-8")
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
        t = data.get("hf_token")
        if isinstance(t, str) and t.strip():
            self._hf_token_file = t.strip()

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
