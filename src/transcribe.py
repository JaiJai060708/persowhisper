"""Run the local whisperx CLI on a recorded WAV and return the joined text."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import WHISPERX_BIN
from .hf_cache import clean_stale_locks
from .settings import SETTINGS


def transcribe(wav_path: Path) -> str:
    clean_stale_locks()
    out_dir = wav_path.parent
    model = SETTINGS.model
    cmd = [
        str(WHISPERX_BIN),
        str(wav_path),
        "--model", model,
        "--language", "en",
        "--task", "transcribe",
        "--no_align",
        # int8 is ~3-4x faster than float32 on Apple Silicon CPU with
        # negligible quality loss for English speech.
        "--compute_type", "int8",
        "--output_format", "json",
        "--output_dir", str(out_dir),
    ]
    env = os.environ.copy()
    # Force unbuffered output and verbose HF downloads so you can see exactly
    # where a hang is happening (model download? VAD load? inference?).
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
    env.setdefault("HF_HUB_VERBOSITY", "info")
    env.setdefault("TRANSFORMERS_VERBOSITY", "info")
    # pyannote-audio initializes an OTel MeterProvider with OTLP exporters at
    # import; with no collector listening, the export daemon thread blocks on
    # send and atexit MeterProvider.shutdown() then hangs joining it for ~30s
    # — leaving whisperx alive long after the transcript is written.
    env.setdefault("OTEL_SDK_DISABLED", "true")
    env.setdefault("OTEL_TRACES_EXPORTER", "none")
    env.setdefault("OTEL_METRICS_EXPORTER", "none")
    env.setdefault("OTEL_LOGS_EXPORTER", "none")

    print(
        f"[transcribe] starting model={model} (first run of a new model "
        f"downloads it from huggingface — watch this terminal)",
        file=sys.stderr,
    )
    print(f"[transcribe] cmd: {' '.join(cmd)}", file=sys.stderr)
    t0 = time.monotonic()

    # Use Popen + poll() so we can print our own heartbeat. If whisperx is
    # silent (e.g. a stalled HF download), at least you can see whether our
    # process is alive and how long it's been waiting.
    proc = subprocess.Popen(cmd, env=env)
    while True:
        try:
            rc = proc.wait(timeout=10.0)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t0
            print(
                f"[transcribe] still working… {elapsed:.0f}s elapsed",
                file=sys.stderr,
            )
    elapsed = time.monotonic() - t0
    print(
        f"[transcribe] finished in {elapsed:.1f}s (rc={rc})",
        file=sys.stderr,
    )
    if rc != 0:
        raise RuntimeError(
            f"whisperx exited {rc} after {elapsed:.1f}s "
            f"(see this terminal for whisperx output)"
        )

    json_path = out_dir / (wav_path.stem + ".json")
    if not json_path.exists():
        raise RuntimeError(f"whisperx json output missing: {json_path}")

    data = json.loads(json_path.read_text())
    segments = data.get("segments", [])
    text = " ".join((seg.get("text") or "").strip() for seg in segments).strip()
    text = " ".join(text.split())

    try:
        json_path.unlink()
    except Exception:
        pass
    return text
