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

# --- Generate AppIcon.icns (cached) -----------------------------------------
if [[ ! -f "$ICON" ]]; then
  TMP_ROOT="$(mktemp -d)"
  ICONSET="$TMP_ROOT/AppIcon.iconset"
  BASE_PNG="$TMP_ROOT/icon_1024.png"
  mkdir -p "$ICONSET"

  "$PYTHON" - "$BASE_PNG" <<'PY'
import sys
from AppKit import (
    NSBitmapImageRep, NSColor, NSBezierPath, NSAttributedString,
    NSFont, NSGraphicsContext, NSDeviceRGBColorSpace,
    NSBitmapImageFileTypePNG, NSFontAttributeName,
)
from Foundation import NSMakeRect, NSMakePoint

out_path = sys.argv[1]
SIZE = 1024

rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, SIZE, SIZE, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
)

ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(ctx)

inset = SIZE * 0.06
radius = SIZE * 0.225
rect = NSMakeRect(inset, inset, SIZE - 2 * inset, SIZE - 2 * inset)
path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.20, 0.30, 1.0).setFill()
path.fill()

glyph = "\U0001F399"  # studio microphone
font = NSFont.fontWithName_size_("Apple Color Emoji", SIZE * 0.58)
if font is None:
    font = NSFont.systemFontOfSize_(SIZE * 0.58)
attrs = {NSFontAttributeName: font}
s = NSAttributedString.alloc().initWithString_attributes_(glyph, attrs)
text_size = s.size()
x = (SIZE - text_size.width) / 2.0
y = (SIZE - text_size.height) / 2.0 - SIZE * 0.04
s.drawAtPoint_(NSMakePoint(x, y))

NSGraphicsContext.restoreGraphicsState()

data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
if not data.writeToFile_atomically_(out_path, True):
    sys.exit("failed to write png")
PY

  for sz in 16 32 64 128 256 512; do
    sips -z $sz $sz "$BASE_PNG" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
    sz2=$((sz * 2))
    sips -z $sz2 $sz2 "$BASE_PNG" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  cp "$BASE_PNG" "$ICONSET/icon_512x512@2x.png"
  iconutil -c icns "$ICONSET" -o "$ICON"
  rm -rf "$TMP_ROOT"
fi

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
