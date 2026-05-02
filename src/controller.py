"""Orchestrates the dictation flow: record → transcribe → paste.

Owns the State enum and the Recorder. Each tap of the hotkey calls `on_tap()`,
which advances the state machine. Transcription runs on a background worker
thread so the main UI loop stays responsive.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

from .config import (
    MIN_RECORDING_SEC,
    SOUND_BUSY,
    SOUND_DONE,
    SOUND_ERR,
    SOUND_START,
    SOUND_STOP,
)
from .paste import paste
from .recorder import Recorder
from .state import State
from .system import notify, play
from .transcribe import transcribe


class Controller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = State.IDLE
        self._recorder = Recorder()

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def latest_level(self) -> float:
        return self._recorder.latest_level()

    def _set_state(self, new: State) -> None:
        with self._lock:
            self._state = new

    def on_tap(self) -> None:
        with self._lock:
            current = self._state

        if current is State.IDLE:
            self._start_recording()
        elif current is State.RECORDING:
            self._stop_recording_and_transcribe()
        else:
            play(SOUND_BUSY)

    def _start_recording(self) -> None:
        try:
            self._recorder.start()
        except Exception as exc:
            print(f"[controller] failed to start recording: {exc}", file=sys.stderr)
            play(SOUND_ERR)
            notify("PersoWhisper — mic error", str(exc))
            return
        self._set_state(State.RECORDING)
        play(SOUND_START)

    def _stop_recording_and_transcribe(self) -> None:
        self._set_state(State.TRANSCRIBING)
        play(SOUND_STOP)
        threading.Thread(target=self._transcribe_worker, daemon=True).start()

    def _transcribe_worker(self) -> None:
        wav_path: Optional[Path] = None
        keep_wav = False
        try:
            wav_path, duration = self._recorder.stop()
            if wav_path is None or duration < MIN_RECORDING_SEC:
                print(
                    f"[controller] recording too short ({duration:.2f}s), skipping",
                    file=sys.stderr,
                )
                play(SOUND_BUSY)
                return

            text = transcribe(wav_path)
            if not text:
                print("[controller] transcript was empty", file=sys.stderr)
                play(SOUND_ERR)
                return

            print(f"[controller] transcript: {text!r}", file=sys.stderr)
            paste(text)
            play(SOUND_DONE)
        except Exception as exc:
            print(f"[controller] transcribe failed: {exc}", file=sys.stderr)
            play(SOUND_ERR)
            notify("PersoWhisper — transcription failed", str(exc)[:200])
            keep_wav = True
            if wav_path is not None:
                print(
                    f"[controller] kept wav for debug: {wav_path}",
                    file=sys.stderr,
                )
        finally:
            if wav_path is not None and wav_path.exists() and not keep_wav:
                try:
                    wav_path.unlink()
                except Exception:
                    pass
            self._set_state(State.IDLE)
