"""Microphone capture to a 16 kHz mono WAV file, with thread-safe RMS levels."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from .config import SAMPLE_RATE


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._started_at: Optional[float] = None
        self._stream_lock = threading.Lock()
        self._chunks_lock = threading.Lock()
        self._level_lock = threading.Lock()
        self._latest_level = 0.0

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[recorder] sounddevice status: {status}", file=sys.stderr)
        with self._chunks_lock:
            self._chunks.append(indata.copy())
        if indata.size:
            chunk = indata.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(chunk * chunk)))
        else:
            rms = 0.0
        with self._level_lock:
            self._latest_level = rms

    def latest_level(self) -> float:
        with self._level_lock:
            return self._latest_level

    def start(self) -> None:
        with self._stream_lock:
            with self._chunks_lock:
                self._chunks = []
            with self._level_lock:
                self._latest_level = 0.0
            self._started_at = time.monotonic()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> tuple[Optional[Path], float]:
        with self._stream_lock:
            if self._stream is None:
                return None, 0.0
            started_at = self._started_at
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
                self._started_at = None

        duration = time.monotonic() - (started_at or time.monotonic())
        with self._chunks_lock:
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return None, duration

        audio = np.concatenate(chunks, axis=0)
        if audio.shape[0] == 0:
            return None, duration

        tmp = tempfile.NamedTemporaryFile(
            prefix="persowhisper_", suffix=".wav", delete=False
        )
        tmp.close()
        path = Path(tmp.name)
        sf.write(str(path), audio, SAMPLE_RATE, subtype="PCM_16")
        return path, duration

    def cancel(self) -> None:
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None
            self._started_at = None

        with self._chunks_lock:
            self._chunks = []
        with self._level_lock:
            self._latest_level = 0.0
