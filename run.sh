#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

exec ./whisperx-env/bin/python -m src
