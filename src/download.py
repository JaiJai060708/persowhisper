"""Pre-download (or verify) the faster-whisper model snapshots used by
PersoWhisper. Run via ./setup.sh, or:

    python -m src.download                   # all models in AVAILABLE_MODELS
    python -m src.download large-v3          # only this one
    python -m src.download large-v3 medium.en

Idempotent — if a model is already in the local Hugging Face cache,
snapshot_download is a no-op verify. Stale lock files from interrupted
prior runs are swept first.
"""

from __future__ import annotations

import sys
import time
from typing import Sequence

from .config import AVAILABLE_MODELS
from .hf_cache import clean_stale_locks


_REPO_FMT = "Systran/faster-whisper-{model}"


def ensure(model: str) -> str:
    """Download (or verify) one model. Returns the local cache path."""
    from huggingface_hub import snapshot_download

    repo = _REPO_FMT.format(model=model)
    print(f"\n=== {model}  →  {repo} ===", file=sys.stderr)
    t0 = time.monotonic()
    path = snapshot_download(repo)
    elapsed = time.monotonic() - t0
    print(
        f"OK  {model}  cached at {path}  ({elapsed:.1f}s)",
        file=sys.stderr,
    )
    return path


def main(argv: Sequence[str] = tuple(sys.argv)) -> int:
    targets = list(argv[1:]) or list(AVAILABLE_MODELS)
    unknown = [m for m in targets if m not in AVAILABLE_MODELS]
    if unknown:
        print(
            f"unknown model(s): {unknown}\n"
            f"valid: {', '.join(AVAILABLE_MODELS)}",
            file=sys.stderr,
        )
        return 1

    clean_stale_locks()

    failures: list[str] = []
    for m in targets:
        try:
            ensure(m)
        except Exception as exc:
            failures.append(f"{m}: {exc}")
            print(f"FAILED  {m}  →  {exc}", file=sys.stderr)

    print("", file=sys.stderr)
    if failures:
        print(f"Done with {len(failures)} failure(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"All {len(targets)} model(s) ready.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
