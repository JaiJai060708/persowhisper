#!/usr/bin/env bash
# Build PersoWhisper.app via py2app and re-register it with Launch Services.
#
# py2app is required (vs. a hand-rolled bash bundle) because it produces a real
# Mach-O launcher that embeds Python in-process. Without that, the running
# binary is Homebrew's framework Python (identifier `org.python.python`), and
# macOS TCC keys Accessibility grants on that — so a grant on the .app would
# never apply. With the embedded launcher, TCC sees `com.borisploix.persowhisper`
# and the bundle's grant works.
#
# Alias mode (-A) means the bundle does NOT copy site-packages — it points at
# the live `whisperx-env`. Fast rebuilds; no need to reinstall whisperx.
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_ROOT="$PWD"
PYTHON="$PROJECT_ROOT/whisperx-env/bin/python"
ICON="$PROJECT_ROOT/AppIcon.icns"
DIST_APP="$PROJECT_ROOT/dist/PersoWhisper.app"
LINK="/Applications/PersoWhisper.app"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister

if [[ ! -x "$PYTHON" ]]; then
  echo "error: $PYTHON not found. Run ./setup.sh first." >&2
  exit 1
fi

# Ensure py2app is installed in the venv.
if ! "$PYTHON" -c "import py2app" 2>/dev/null; then
  "$PYTHON" -m pip install py2app
fi

# --- Generate AppIcon.icns --------------------------------------------------
"$PYTHON" tools/generate_app_icon.py "$ICON"

# --- Build the bundle --------------------------------------------------------
rm -rf build dist
"$PYTHON" setup.py py2app -A 2>&1 | tail -10

# --- /Applications symlink ---------------------------------------------------
if ln -sfn "$DIST_APP" "$LINK" 2>/dev/null; then
  echo "OK: symlinked $LINK -> $DIST_APP"
else
  echo "warn: could not create $LINK (try: sudo ln -sfn \"$DIST_APP\" \"$LINK\")"
fi

# --- Re-register so Launch Services drops any stale registrations -----------
"$LSREGISTER" -f "$DIST_APP" >/dev/null 2>&1 || true

cat <<EOF

OK: built $DIST_APP

Next steps:
  1. System Settings -> Privacy & Security -> Accessibility:
     click +, add /Applications/PersoWhisper.app, enable it.
  2. Launch from Finder, Spotlight, or:  open -a PersoWhisper
EOF
