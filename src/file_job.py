"""File-import flow: NSOpenPanel / drag → live streaming into the main window."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

from AppKit import NSAlert, NSAlertStyleCritical, NSOpenPanel
from Foundation import NSOperationQueue

from .config import (
    MODEL,
    SOUND_DONE,
    SOUND_ERR,
    SOUND_STOP,
    SUPPORTED_AUDIO_EXTS,
    SUPPORTED_VIDEO_EXTS,
)
from .settings import SETTINGS
from .system import play
from .transcribe import Segment, TranscriptionCancelled, transcribe_file


def _run_on_main(callable_, *args) -> None:
    NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: callable_(*args))


def pick_audio_or_video() -> Optional[Path]:
    panel = NSOpenPanel.openPanel()
    panel.setTitle_("Select audio or video to transcribe")
    panel.setAllowsMultipleSelection_(False)
    panel.setCanChooseDirectories_(False)
    panel.setCanChooseFiles_(True)
    panel.setAllowedFileTypes_(list(SUPPORTED_AUDIO_EXTS + SUPPORTED_VIDEO_EXTS))
    if panel.runModal() != 1:
        return None
    urls = panel.URLs()
    if not urls or len(urls) == 0:
        return None
    return Path(urls[0].path())


def _show_error(title: str, message: str) -> None:
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.setAlertStyle_(NSAlertStyleCritical)
    alert.runModal()


class FileJobController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._cancel_event: Optional[threading.Event] = None
        self._window = None  # DropWindowController, wired by app.py

    def attach_window(self, window) -> None:
        self._window = window

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def _set_busy(self, value: bool) -> None:
        with self._lock:
            self._busy = value
            if not value:
                self._cancel_event = None

    def cancel(self) -> None:
        win = self._window
        with self._lock:
            if not self._busy or self._cancel_event is None:
                return
            cancel_event = self._cancel_event
        cancel_event.set()
        if win is not None:
            _run_on_main(win.mark_cancelling)

    def start(self) -> None:
        if self.is_busy():
            return
        path = pick_audio_or_video()
        if path is None:
            return
        self.start_with_path(path)

    def start_with_path(self, path: Path) -> None:
        """Called on the main thread (from drag-drop, Browse, or menu)."""
        if self.is_busy():
            return
        if not path.exists():
            _show_error("File not found", f"{path} does not exist.")
            return
        cancel_event = threading.Event()
        with self._lock:
            if self._busy:
                return
            self._busy = True
            self._cancel_event = cancel_event
        # Switch the window into transcript mode immediately. We're on the
        # main thread, so just do it inline — no NSOperationQueue dance.
        if self._window is not None:
            self._window.prepare_for_path(path)
        threading.Thread(
            target=self._worker,
            args=(path, cancel_event),
            daemon=True,
            name="file-job",
        ).start()

    def _worker(self, path: Path, cancel_event: threading.Event) -> None:
        win = self._window

        def push_partial(seg: Segment) -> None:
            if win is not None:
                _run_on_main(win.append_partial, seg)

        def push_status(text: str) -> None:
            if win is not None:
                _run_on_main(win.set_status, text)

        try:
            token = SETTINGS.hf_token
            segments = transcribe_file(
                path,
                model=MODEL,
                diarize=True,
                hf_token=token,
                language="en",
                on_partial=push_partial,
                on_status=push_status,
                cancel_requested=cancel_event.is_set,
            )
            if not segments:
                if win is not None:
                    _run_on_main(win.mark_failed, "No speech detected.")
                play(SOUND_ERR)
                return
            if win is not None:
                _run_on_main(win.commit_final, segments)
            play(SOUND_DONE)
        except TranscriptionCancelled as exc:
            print(f"[file_job] cancelled: {exc}", file=sys.stderr)
            play(SOUND_STOP)
            if win is not None:
                _run_on_main(win.mark_cancelled)
        except Exception as exc:
            print(f"[file_job] failed: {exc}", file=sys.stderr)
            play(SOUND_ERR)
            if win is not None:
                _run_on_main(win.mark_failed, str(exc))
            else:
                _run_on_main(_show_error, "Transcription failed", str(exc))
        finally:
            self._set_busy(False)
