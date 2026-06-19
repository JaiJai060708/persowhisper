"""On-demand, in-process whisperx model for low-latency dictation.

The whisperx CLI can only load the model *after* recording stops (it needs the
finished audio file), so every dictation blocked on a fresh ~8 s load. Holding
the model resident the whole time would fix the latency but waste ~1–2 GB of RAM
while idle. Instead we load on demand and free it right after:

- ``ENGINE.prewarm()`` starts the load on a background thread. The controller
  calls it the moment recording starts, so the load overlaps with the user
  speaking rather than blocking after they stop.
- ``transcribe()`` blocks until the model is ready, runs inference on our own
  16 kHz WAV (read via soundfile — no ffmpeg), and streams progress through
  whisperx's ``progress_callback``.
- ``ENGINE.release()`` drops the model and frees its memory. The controller
  calls it once transcription finishes (or the dictation is cancelled), so the
  process idles at a low footprint until the next recording.

Only the dictation flow uses this. File import (with diarization) still shells
out to the whisperx CLI in ``transcribe.py``.
"""

from __future__ import annotations

import gc
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from .config import MODEL
from .transcribe import Segment, TranscriptionCancelled


class _Engine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._model = None
        self._loading = False
        self._load_error: Optional[Exception] = None
        self._ready = threading.Event()
        # Bumped on release() so an in-flight load knows to discard its result.
        self._generation = 0

    def prewarm(self) -> None:
        """Start loading the model in the background, unless it is already
        loaded or loading. Cheap and idempotent — safe to call on every record."""
        with self._lock:
            if self._model is not None or self._loading:
                return
            self._loading = True
            self._load_error = None
            self._ready.clear()
            gen = self._generation
        threading.Thread(
            target=self._load, args=(gen,), daemon=True, name="whisperx-load"
        ).start()

    def _load(self, gen: int) -> None:
        t0 = time.monotonic()
        try:
            import whisperx  # heavy (pulls in torch); kept off the main thread

            model = whisperx.load_model(
                MODEL,
                device="cpu",
                compute_type="int8",
                language="en",
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller
            print(f"[engine] model load failed: {exc}", file=sys.stderr)
            with self._lock:
                if gen == self._generation:
                    self._load_error = exc
                    self._loading = False
                    self._ready.set()
            return
        with self._lock:
            if gen != self._generation:
                # Released (e.g. dictation cancelled) while we were loading —
                # throw the freshly-loaded model away instead of caching it.
                stale = True
            else:
                self._model = model
                self._loading = False
                self._load_error = None
                self._ready.set()
                stale = False
        if stale:
            del model
            gc.collect()
            print("[engine] discarded model loaded after release", file=sys.stderr)
        else:
            print(
                f"[engine] model ready in {time.monotonic() - t0:.1f}s",
                file=sys.stderr,
            )

    def release(self) -> None:
        """Drop the model and free its memory. Invalidates any in-flight load."""
        with self._lock:
            had_model = self._model is not None or self._loading
            self._generation += 1
            self._model = None
            self._loading = False
            self._load_error = None
            self._ready.clear()
        if had_model:
            gc.collect()
            print("[engine] model released", file=sys.stderr)

    def _ensure_model(self):
        """Block until the model is loaded, kicking off the load if needed."""
        self.prewarm()
        self._ready.wait()
        with self._lock:
            if self._model is None:
                raise RuntimeError(
                    f"whisperx model failed to load: {self._load_error}"
                )
            return self._model

    def transcribe_segments(
        self,
        wav_path: Path,
        *,
        duration: Optional[float] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> list[Segment]:
        def cancelled() -> bool:
            if cancel_requested is None:
                return False
            try:
                return bool(cancel_requested())
            except Exception as exc:
                print(f"[engine] cancel_requested raised: {exc}", file=sys.stderr)
                return False

        if cancelled():
            raise TranscriptionCancelled("Transcription cancelled.")

        model = self._ensure_model()

        if cancelled():
            raise TranscriptionCancelled("Transcription cancelled.")

        # Our recorder writes 16 kHz mono PCM-16; read it straight to float32
        # in [-1, 1]. Passing an array (not a path) skips whisperx's ffmpeg load.
        audio, _sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = np.ascontiguousarray(audio, dtype=np.float32)

        def report(frac: float) -> None:
            if on_progress is None:
                return
            frac = 0.0 if frac < 0.0 else 1.0 if frac > 1.0 else frac
            try:
                on_progress(frac)
            except Exception as exc:
                print(f"[engine] on_progress raised: {exc}", file=sys.stderr)

        # whisperx's progress_callback only fires once per ~30 s VAD chunk, so a
        # typical (sub-30 s) dictation is a single chunk and we'd get just one
        # callback — at the very end. The bar would sit at 0 % then snap to done.
        # To give a smoothly advancing bar we estimate progress from elapsed
        # wall-clock against a rough transcription-time estimate, and let
        # whisperx's real per-chunk callback push it ahead on longer clips.
        t0 = time.monotonic()
        real_fraction = 0.0
        # CPU large-v3 (int8) runs faster than real time but with fixed per-call
        # overhead (VAD, tokenizer); this only needs to be in the right ballpark.
        est_total = max(1.5, 0.7 * duration) if duration and duration > 0 else None

        def estimated() -> float:
            if est_total is None:
                return real_fraction
            return min(0.95, (time.monotonic() - t0) / est_total)

        def progress_cb(percent: float) -> None:
            # Raising here aborts the batch loop promptly between VAD chunks.
            if cancelled():
                raise TranscriptionCancelled("Transcription cancelled.")
            nonlocal real_fraction
            frac = percent / 100.0
            if frac > real_fraction:
                real_fraction = frac
            report(max(real_fraction, estimated()))

        # Flip the overlay from the indeterminate "Loading…" state to
        # "Transcribing… 0%" now that the model is ready.
        report(0.0)

        stop_ticker = threading.Event()

        def ticker() -> None:
            while not stop_ticker.wait(0.1):
                if cancelled():
                    return
                report(max(real_fraction, estimated()))

        tick_thread: Optional[threading.Thread] = None
        if on_progress is not None and est_total is not None:
            tick_thread = threading.Thread(
                target=ticker, daemon=True, name="whisperx-progress"
            )
            tick_thread.start()

        try:
            with self._infer_lock:
                result = model.transcribe(
                    audio,
                    batch_size=8,
                    language="en",
                    task="transcribe",
                    progress_callback=progress_cb,
                )
        except TranscriptionCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"whisperx transcription failed: {exc}") from exc
        finally:
            stop_ticker.set()
            if tick_thread is not None:
                tick_thread.join(timeout=0.5)

        # Inference finished — fill the bar even if the (coarse) callback never
        # reached 100 %, so the overlay shows complete before the paste lands.
        report(1.0)

        if cancelled():
            raise TranscriptionCancelled("Transcription cancelled.")

        segments: list[Segment] = []
        for seg in result.get("segments", []):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                Segment(
                    start=float(seg.get("start") or 0.0),
                    end=float(seg.get("end") or 0.0),
                    speaker=None,
                    text=" ".join(text.split()),
                )
            )
        print(
            f"[engine] transcribed in {time.monotonic() - t0:.1f}s "
            f"({len(segments)} segment(s))",
            file=sys.stderr,
        )
        return segments


ENGINE = _Engine()


def transcribe(
    wav_path: Path,
    *,
    duration: Optional[float] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> str:
    """Dictation entry point: warm-model transcription returning joined text."""
    segments = ENGINE.transcribe_segments(
        wav_path,
        duration=duration,
        cancel_requested=cancel_requested,
        on_progress=on_progress,
    )
    text = " ".join(s.text for s in segments).strip()
    return " ".join(text.split())
