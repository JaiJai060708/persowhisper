"""Shared helpers for the local Hugging Face hub cache."""

from __future__ import annotations

import sys
import time
from pathlib import Path


HF_LOCKS_DIR = Path.home() / ".cache" / "huggingface" / "hub" / ".locks"
STALE_LOCK_AGE_SEC = 30.0


def clean_stale_locks() -> int:
    """Remove HF Hub download lock files older than STALE_LOCK_AGE_SEC.

    Lock files are left behind when a download is interrupted (e.g. Ctrl+C
    mid-transcribe); subsequent runs then deadlock waiting for the orphan.
    Active downloads continuously refresh their lock's mtime, so this pass
    only touches stale orphans. Returns the number of files removed.
    """
    if not HF_LOCKS_DIR.exists():
        return 0
    now = time.time()
    cleared = 0
    for lock in HF_LOCKS_DIR.rglob("*.lock"):
        try:
            age = now - lock.stat().st_mtime
        except FileNotFoundError:
            continue
        if age < STALE_LOCK_AGE_SEC:
            continue
        try:
            lock.unlink()
            cleared += 1
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[hf_cache] could not remove {lock}: {exc}", file=sys.stderr)
    if cleared:
        print(
            f"[hf_cache] cleared {cleared} stale HF lock file(s) "
            f"(age > {STALE_LOCK_AGE_SEC:.0f}s)",
            file=sys.stderr,
        )
    return cleared
