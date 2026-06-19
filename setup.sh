#!/usr/bin/env bash
# Pre-download (or verify) the faster-whisper model PersoWhisper uses.
# Forwards extra args, e.g. ./setup.sh large-v3
set -euo pipefail
cd "$(dirname "$0")"

exec ./whisperx-env/bin/python -m src.download "$@"
