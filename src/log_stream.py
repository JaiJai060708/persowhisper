"""Capture Python stdout/stderr for the in-app Logs tab.

The bridge tees writes to the original terminal streams and keeps a bounded
in-memory copy for AppKit views to observe.
"""

from __future__ import annotations

from pathlib import Path
import sys
import threading
from typing import Callable, TextIO


MAX_LOG_CHARS = 120_000
LOG_PATH = Path.home() / "Library" / "Logs" / "PersoWhisper.log"

_lock = threading.RLock()
_chunks: list[str] = []
_chunk_len = 0
_listeners: list[Callable[[str], None]] = []
_installed = False
_log_file: TextIO | None = None


def _append(text: str) -> None:
    global _chunk_len
    if not text:
        return
    with _lock:
        _chunks.append(text)
        _chunk_len += len(text)
        while _chunks and _chunk_len > MAX_LOG_CHARS:
            overflow = _chunk_len - MAX_LOG_CHARS
            first = _chunks[0]
            if len(first) <= overflow:
                _chunk_len -= len(first)
                del _chunks[0]
            else:
                _chunks[0] = first[overflow:]
                _chunk_len -= overflow
        listeners = list(_listeners)
        log_file = _log_file
        if log_file is not None:
            try:
                log_file.write(text)
                log_file.flush()
            except Exception:
                pass
    for listener in listeners:
        try:
            listener(text)
        except Exception:
            pass


class _TeeStream:
    def __init__(self, wrapped: TextIO) -> None:
        self._wrapped = wrapped

    def write(self, text: str) -> int:
        try:
            written = self._wrapped.write(text)
        except Exception:
            written = len(text)
        _append(text)
        return written if written is not None else len(text)

    def flush(self) -> None:
        try:
            self._wrapped.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return self._wrapped.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._wrapped.fileno()

    @property
    def encoding(self) -> str | None:
        return getattr(self._wrapped, "encoding", None)

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


def install_stdio_bridge() -> None:
    global _installed, _log_file
    with _lock:
        if _installed:
            return
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _log_file = LOG_PATH.open("a", buffering=1, encoding="utf-8")
            _log_file.write("\n--- PersoWhisper log started ---\n")
            _log_file.flush()
        except Exception:
            _log_file = None
        sys.stdout = _TeeStream(sys.stdout)  # type: ignore[assignment]
        sys.stderr = _TeeStream(sys.stderr)  # type: ignore[assignment]
        _installed = True


def add_listener(listener: Callable[[str], None]) -> None:
    with _lock:
        _listeners.append(listener)


def snapshot() -> str:
    with _lock:
        return "".join(_chunks)
