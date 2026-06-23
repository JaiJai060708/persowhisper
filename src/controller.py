"""Orchestrates the dictation flow: record → transcribe → paste.

Owns the State enum and the Recorder. Each tap of the hotkey calls `on_tap()`,
which advances the state machine. Transcription runs on a background worker
thread so the main UI loop stays responsive.
"""

from __future__ import annotations

import sys
import threading
import time
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
from .engine import ENGINE, transcribe
from .paste import PasteTarget, capture_paste_target, paste
from .recorder import Recorder
from .state import State
from .system import notify, play
from .transcribe import TranscriptionCancelled


DUPLICATE_TAP_SUPPRESS_SEC = 0.12


class Controller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = State.IDLE
        self._recorder = Recorder()
        self._cancel_event: Optional[threading.Event] = None
        self._paste_target: Optional[PasteTarget] = None
        self._last_tap_at = 0.0
        # Transcription progress, read by the UI loop. `_fraction` is None until
        # the first segment arrives (the model-load / VAD phase has no progress).
        self._transcribe_fraction: Optional[float] = None

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def can_cancel(self) -> bool:
        with self._lock:
            return self._state in (State.RECORDING, State.TRANSCRIBING)

    def latest_level(self) -> float:
        return self._recorder.latest_level()

    def _set_state(self, new: State) -> None:
        with self._lock:
            self._state = new
            if new is State.IDLE:
                self._cancel_event = None
                self._paste_target = None
                self._transcribe_fraction = None

    def _finish_transcription(self, cancel_event: threading.Event) -> None:
        with self._lock:
            if self._cancel_event is cancel_event:
                self._state = State.IDLE
                self._cancel_event = None
                self._paste_target = None
                self._transcribe_fraction = None

    def _report_progress(self, fraction: float) -> None:
        with self._lock:
            if self._state is State.TRANSCRIBING:
                self._transcribe_fraction = fraction

    def transcribe_view(self) -> Optional[float]:
        """Progress fraction for the overlay. None during the model-load / VAD
        phase, then 0.0–1.0 once transcription is under way."""
        with self._lock:
            return self._transcribe_fraction

    def on_tap(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_tap_at < DUPLICATE_TAP_SUPPRESS_SEC:
                return
            self._last_tap_at = now
            current = self._state

        if current is State.IDLE:
            self._start_recording()
        elif current is State.RECORDING:
            self._stop_recording_and_transcribe()
        else:
            play(SOUND_BUSY)

    def _start_recording(self) -> None:
        paste_target = capture_paste_target()
        try:
            self._recorder.start()
        except Exception as exc:
            print(f"[controller] failed to start recording: {exc}", file=sys.stderr)
            play(SOUND_ERR)
            notify("PersoWhisper — mic error", str(exc))
            return
        # Load the model now, in the background, so it is warm (or warming) by
        # the time the user stops talking instead of blocking after the fact.
        ENGINE.prewarm()
        with self._lock:
            self._state = State.RECORDING
            self._paste_target = paste_target
        play(SOUND_START)

    def _stop_recording_and_transcribe(self) -> None:
        cancel_event = threading.Event()
        with self._lock:
            if self._state is not State.RECORDING:
                return
            self._state = State.TRANSCRIBING
            self._cancel_event = cancel_event
            self._transcribe_fraction = None
            paste_target = self._paste_target
        play(SOUND_STOP)
        threading.Thread(
            target=self._transcribe_worker,
            args=(cancel_event, paste_target),
            daemon=True,
        ).start()

    def cancel(self) -> None:
        cancel_recording = False
        signal_transcription = False
        cancel_event: Optional[threading.Event] = None

        with self._lock:
            current = self._state
            if current is State.RECORDING:
                self._state = State.IDLE
                self._cancel_event = None
                self._paste_target = None
                cancel_recording = True
            elif current is State.TRANSCRIBING:
                cancel_event = self._cancel_event
                if cancel_event is not None:
                    cancel_event.set()
                self._state = State.IDLE
                self._cancel_event = None
                self._paste_target = None
                self._transcribe_fraction = None
                signal_transcription = True
            else:
                return

        if cancel_recording:
            print("[controller] recording cancelled", file=sys.stderr)
            self._recorder.cancel()
            # No transcription will run, so free the model we warmed at record
            # start. (When transcribing, the worker's finally handles release.)
            ENGINE.release()
            play(SOUND_STOP)
        elif signal_transcription:
            print("[controller] transcription cancellation requested", file=sys.stderr)
            self._recorder.cancel()
            play(SOUND_STOP)

    def _transcribe_worker(
        self,
        cancel_event: threading.Event,
        paste_target: Optional[PasteTarget],
    ) -> None:
        wav_path: Optional[Path] = None
        keep_wav = False
        try:
            wav_path, duration = self._recorder.stop()
            if cancel_event.is_set():
                print(
                    "[controller] transcription cancelled before whisperx",
                    file=sys.stderr,
                )
                return
            if wav_path is None or duration < MIN_RECORDING_SEC:
                print(
                    f"[controller] recording too short ({duration:.2f}s), skipping",
                    file=sys.stderr,
                )
                play(SOUND_BUSY)
                return

            text = transcribe(
                wav_path,
                duration=duration,
                cancel_requested=cancel_event.is_set,
                on_progress=self._report_progress,
            )
            if cancel_event.is_set():
                print(
                    "[controller] transcription cancelled before paste",
                    file=sys.stderr,
                )
                return
            if not text:
                print("[controller] transcript was empty", file=sys.stderr)
                play(SOUND_ERR)
                return

            print(f"[controller] transcript: {text!r}", file=sys.stderr)
            if paste(
                text,
                cancel_requested=cancel_event.is_set,
                target=paste_target,
            ):
                play(SOUND_DONE)
            else:
                print("[controller] paste cancelled or failed", file=sys.stderr)
                play(SOUND_ERR)
                notify(
                    "PersoWhisper — paste failed",
                    "Enable Accessibility for PersoWhisper/launcher and "
                    "System Events automation, then relaunch.",
                )
        except TranscriptionCancelled as exc:
            print(f"[controller] transcribe cancelled: {exc}", file=sys.stderr)
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
            # Done with the model (success, error, or cancellation) — free it so
            # the process idles low until the next recording warms it again.
            ENGINE.release()
            self._finish_transcription(cancel_event)
