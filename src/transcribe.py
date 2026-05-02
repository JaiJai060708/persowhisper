"""Run the local whisperx CLI on a recorded WAV and return the joined text."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .config import WHISPERX_BIN, WHISPERX_MODEL


def transcribe(wav_path: Path) -> str:
    out_dir = wav_path.parent
    cmd = [
        str(WHISPERX_BIN),
        str(wav_path),
        "--model", WHISPERX_MODEL,
        "--language", "en",
        "--task", "transcribe",
        "--no_align",
        "--output_format", "json",
        "--output_dir", str(out_dir),
    ]
    print(f"[transcribe] running: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:]
        raise RuntimeError(f"whisperx exited {proc.returncode}\nstderr:\n{tail}")

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
