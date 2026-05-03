#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

APP="$PWD/dist/PersoWhisper.app"

if [[ -d "$APP" && "${PERSOWHISPER_RAW_PYTHON:-0}" != "1" ]]; then
  exec open -W "$APP"
fi

exec ./whisperx-env/bin/python -m src
