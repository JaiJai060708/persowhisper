"""Run the local whisperx CLI on an audio/video file and return the result.

``transcribe_file(audio_path, *, model, diarize, hf_token, language,
on_partial)`` is the entry point used by the file-import flow. It streams
partial segments via ``on_partial`` (no speaker labels yet — those only arrive
in the final JSON), then returns the final list of ``Segment`` records with
start/end timestamps and (when ``diarize=True``) a speaker label.

The dictation flow no longer goes through the CLI — it uses the warm in-process
model in ``engine.py`` to avoid reloading on every utterance.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import WHISPERX_BIN
from .hf_cache import clean_stale_locks


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: Optional[str]
    text: str


class TranscriptionCancelled(RuntimeError):
    """Raised when a caller requests cancellation of an active transcription."""


# whisperx prints live segment lines like
#   Transcript: [0.0 --> 3.48] Hello, this is a test.
# Some versions/tools use mm:ss.mmm or hh:mm:ss.mmm instead. Speakers are NOT
# in the stdout stream — they only appear in the final JSON after diarization.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_TS_RE = r"(?:\d+(?:\.\d+)?|\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)"
_SEG_RE = re.compile(
    rf"(?:Transcript:\s*)?\[(?P<start>{_TS_RE})"
    r"\s*-->\s*"
    rf"(?P<end>{_TS_RE})\]\s*(?P<text>.+)",
    re.IGNORECASE,
)
_PYANNOTE_WARNING_FILTERS = (
    "ignore::UserWarning:pyannote.audio.core.io",
    "ignore::UserWarning:pyannote.audio.models.blocks.pooling",
)


def _parse_ts(ts: str) -> float:
    ts = ts.strip()
    if ":" not in ts:
        try:
            return float(ts)
        except ValueError:
            return 0.0
    parts = ts.split(":")
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def _parse_segment_line(line: str) -> Optional[Segment]:
    line = _ANSI_RE.sub("", line).strip()
    m = _SEG_RE.search(line)
    if not m:
        return None
    text = m.group("text").strip()
    if not text:
        return None
    return Segment(
        start=_parse_ts(m.group("start")),
        end=_parse_ts(m.group("end")),
        speaker=None,
        text=text,
    )


def transcribe_file(
    audio_path: Path,
    *,
    model: str,
    diarize: bool,
    hf_token: Optional[str] = None,
    language: Optional[str] = "en",
    on_partial: Optional[Callable[[Segment], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    total_duration: Optional[float] = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> list[Segment]:
    if diarize and not hf_token:
        raise RuntimeError(
            "diarization requires a Hugging Face token. Set the HF_TOKEN "
            "environment variable, or add \"hf_token\": \"hf_…\" to "
            "~/.persowhisper.json. The token must have access to "
            "pyannote/segmentation-3.0 and pyannote/speaker-diarization-3.1 "
            "(accept the model terms on huggingface.co)."
        )

    def _is_cancelled() -> bool:
        if cancel_requested is None:
            return False
        try:
            return bool(cancel_requested())
        except Exception as exc:
            print(f"[transcribe] cancel_requested raised: {exc}", file=sys.stderr)
            return False

    if _is_cancelled():
        raise TranscriptionCancelled("Transcription cancelled.")

    clean_stale_locks()
    out_dir = audio_path.parent
    cmd: list[str] = [
        str(WHISPERX_BIN),
        str(audio_path),
        "--model", model,
        "--task", "transcribe",
        "--compute_type", "int8",
        "--output_format", "json",
        "--output_dir", str(out_dir),
        "--verbose", "True",
    ]
    if language:
        cmd += ["--language", language]
    if diarize:
        cmd += ["--diarize", "--hf_token", hf_token or ""]
    else:
        cmd += ["--no_align"]

    env = os.environ.copy()
    path_parts = [
        str(WHISPERX_BIN.parent),
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    existing_path = env.get("PATH")
    if existing_path:
        path_parts.append(existing_path)
    env["PATH"] = ":".join(dict.fromkeys(path_parts))
    dyld_parts = [
        "/opt/homebrew/lib",
        "/usr/local/lib",
    ]
    existing_dyld = env.get("DYLD_LIBRARY_PATH")
    if existing_dyld:
        dyld_parts.append(existing_dyld)
    env["DYLD_LIBRARY_PATH"] = ":".join(dict.fromkeys(dyld_parts))
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
    env.setdefault("HF_HUB_VERBOSITY", "info")
    env.setdefault("TRANSFORMERS_VERBOSITY", "info")
    env.setdefault("OTEL_SDK_DISABLED", "true")
    env.setdefault("OTEL_TRACES_EXPORTER", "none")
    env.setdefault("OTEL_METRICS_EXPORTER", "none")
    env.setdefault("OTEL_LOGS_EXPORTER", "none")
    existing_warnings = env.get("PYTHONWARNINGS")
    warning_filters = [
        item.strip()
        for item in (existing_warnings or "").split(",")
        if item.strip()
    ]
    for filt in reversed(_PYANNOTE_WARNING_FILTERS):
        if filt not in warning_filters:
            warning_filters.insert(0, filt)
    env["PYTHONWARNINGS"] = ",".join(warning_filters)

    log_cmd = [
        ("<hf_token>" if (i > 0 and cmd[i - 1] == "--hf_token") else c)
        for i, c in enumerate(cmd)
    ]
    print(
        f"[transcribe] starting model={model} diarize={diarize}",
        file=sys.stderr,
    )
    print(f"[transcribe] cmd: {' '.join(log_cmd)}", file=sys.stderr)
    if on_status is not None:
        on_status("Loading model…")
    t0 = time.monotonic()

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )

    saw_first_segment = False
    cancelled = False
    recent_output: list[str] = []

    def _signal_process(sig: int) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, sig)
            return
        except Exception:
            pass
        try:
            if sig == signal.SIGTERM:
                proc.terminate()
            else:
                proc.kill()
        except Exception:
            pass

    def _pump_stdout() -> None:
        nonlocal saw_first_segment
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            recent_output.append(line)
            del recent_output[:-40]
            # Mirror to our own stderr so the launching terminal still shows
            # whisperx's output (downloads, VAD progress, errors).
            print(line, file=sys.stderr)
            seg = _parse_segment_line(line)
            if seg is not None:
                if not saw_first_segment:
                    saw_first_segment = True
                    if on_status is not None:
                        on_status("Transcribing…")
                if on_partial is not None:
                    try:
                        on_partial(seg)
                    except Exception as exc:
                        print(f"[transcribe] on_partial raised: {exc}", file=sys.stderr)
                if on_progress is not None and total_duration and total_duration > 0:
                    frac = seg.end / total_duration
                    frac = 0.0 if frac < 0.0 else 1.0 if frac > 1.0 else frac
                    try:
                        on_progress(frac)
                    except Exception as exc:
                        print(f"[transcribe] on_progress raised: {exc}", file=sys.stderr)

    reader = threading.Thread(target=_pump_stdout, daemon=True, name="whisperx-stdout")
    reader.start()

    next_log_at = time.monotonic() + 10.0
    while True:
        if _is_cancelled():
            cancelled = True
            print("[transcribe] cancellation requested", file=sys.stderr)
            if on_status is not None:
                on_status("Stopping…")
            _signal_process(signal.SIGTERM)
            try:
                rc = proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                print("[transcribe] process did not exit; killing", file=sys.stderr)
                _signal_process(signal.SIGKILL)
                rc = proc.wait(timeout=5.0)
            break
        try:
            rc = proc.wait(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now >= next_log_at:
                elapsed = now - t0
                print(
                    f"[transcribe] still working… {elapsed:.0f}s elapsed",
                    file=sys.stderr,
                )
                next_log_at = now + 10.0

    reader.join(timeout=2.0)
    elapsed = time.monotonic() - t0
    print(f"[transcribe] finished in {elapsed:.1f}s (rc={rc})", file=sys.stderr)
    if cancelled or _is_cancelled():
        raise TranscriptionCancelled("Transcription cancelled.")
    if rc != 0:
        tail = "\n".join(recent_output[-12:]).strip()
        if tail:
            tail = f"\n\nLast whisperx output:\n{tail}"
        raise RuntimeError(
            f"whisperx exited {rc} after {elapsed:.1f}s "
            f"(see ~/Library/Logs/PersoWhisper.log for full output){tail}"
        )

    if diarize and on_status is not None:
        on_status("Assigning speakers…")

    json_path = out_dir / (audio_path.stem + ".json")
    if not json_path.exists():
        raise RuntimeError(f"whisperx json output missing: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    raw_segments = data.get("segments", [])
    segments: list[Segment] = []
    for seg in raw_segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker")
        if isinstance(speaker, str):
            speaker = speaker.strip() or None
        else:
            speaker = None
        segments.append(
            Segment(
                start=float(seg.get("start") or 0.0),
                end=float(seg.get("end") or 0.0),
                speaker=speaker,
                text=" ".join(text.split()),
            )
        )

    try:
        json_path.unlink()
    except Exception:
        pass
    return segments
