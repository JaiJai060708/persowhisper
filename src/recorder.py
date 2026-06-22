"""Microphone capture, resampled to 16 kHz mono WAV, with thread-safe RMS levels.

We capture at the input device's *native* sample rate and resample to
``SAMPLE_RATE`` (16 kHz) in software. Forcing PortAudio to open a 48 kHz device
directly at 16 kHz makes its CoreAudio backend build an internal rate converter,
which intermittently fails with ``paInternalError`` (-9986) right after a device
switch. Opening at the native rate avoids that whole failure mode.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from math import gcd
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

from .config import SAMPLE_RATE

# Native rates to try, in order, if the device's reported default fails. macOS
# input devices are almost always 48 kHz; 44.1 kHz and 16 kHz cover the rest.
_FALLBACK_RATES: tuple[int, ...] = (48_000, 44_100, 32_000, SAMPLE_RATE)


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._capture_rate: int = SAMPLE_RATE
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
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        else:
            rms = 0.0
        with self._level_lock:
            self._latest_level = rms

    def latest_level(self) -> float:
        with self._level_lock:
            return self._latest_level

    def _candidate_rates(self) -> list[int]:
        """Native device rate first, then sensible fallbacks (deduped)."""
        rates: list[int] = []
        try:
            dev = sd.query_devices(kind="input")
            native = int(round(dev["default_samplerate"]))
            if native > 0:
                rates.append(native)
        except Exception as exc:  # no default device, query failure, etc.
            print(f"[recorder] could not query input device: {exc}", file=sys.stderr)
        for rate in _FALLBACK_RATES:
            if rate not in rates:
                rates.append(rate)
        return rates

    @staticmethod
    def _reinitialize_portaudio() -> None:
        """Drop PortAudio's cached device list. The usual trigger for
        ``paInternalError`` is a device that changed since PortAudio last
        enumerated; a terminate/initialize cycle picks up the new state."""
        try:
            sd._terminate()
            sd._initialize()
            print("[recorder] re-initialized PortAudio", file=sys.stderr)
        except Exception as exc:
            print(f"[recorder] PortAudio re-init failed: {exc}", file=sys.stderr)

    def _open_stream(self) -> sd.InputStream:
        last_exc: Optional[Exception] = None
        # Two passes: the second runs after re-initializing PortAudio, which
        # recovers the common "mic was unplugged/swapped since launch" case.
        for attempt in range(2):
            for rate in self._candidate_rates():
                stream = None
                try:
                    stream = sd.InputStream(
                        samplerate=rate,
                        channels=1,
                        dtype="float32",
                        callback=self._callback,
                    )
                    stream.start()
                    self._capture_rate = int(rate)
                    return stream
                except Exception as exc:
                    last_exc = exc
                    print(
                        f"[recorder] open InputStream at {rate} Hz failed: {exc}",
                        file=sys.stderr,
                    )
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
            if attempt == 0:
                self._reinitialize_portaudio()
        raise RuntimeError(
            "Could not open the microphone. Check System Settings ▸ Privacy & "
            "Security ▸ Microphone, and that no other app is using the mic."
        ) from last_exc

    def start(self) -> None:
        with self._stream_lock:
            with self._chunks_lock:
                self._chunks = []
            with self._level_lock:
                self._latest_level = 0.0
            self._started_at = time.monotonic()
            self._stream = self._open_stream()

    def _resample_to_target(self, audio: np.ndarray) -> np.ndarray:
        """Resample mono float32 from the capture rate down to SAMPLE_RATE."""
        if self._capture_rate == SAMPLE_RATE:
            return audio
        divisor = gcd(self._capture_rate, SAMPLE_RATE)
        up = SAMPLE_RATE // divisor
        down = self._capture_rate // divisor
        resampled = resample_poly(audio, up, down)
        # resample_poly can overshoot slightly; clip before PCM-16 conversion.
        return np.clip(resampled, -1.0, 1.0).astype(np.float32)

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

        audio = np.concatenate(chunks, axis=0).reshape(-1).astype(np.float32)
        if audio.shape[0] == 0:
            return None, duration

        audio = self._resample_to_target(audio)

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
