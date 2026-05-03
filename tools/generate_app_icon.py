#!/usr/bin/env python3
"""Generate the PersoWhisper macOS app icon.

The app bundle is built by py2app, which expects an .icns file. This script
draws a branded 1024px source image with AppKit, creates the iconset variants,
and writes a PNG-backed .icns file directly.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from AppKit import (
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSBezierPath,
    NSColor,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
)
from Foundation import NSMakePoint, NSMakeRect


SIZE = 1024
INK = (0.030, 0.035, 0.045)
INK_2 = (0.075, 0.088, 0.105)
TEAL = (0.000, 0.760, 0.720)
BLUE = (0.180, 0.420, 0.940)
CORAL = (1.000, 0.380, 0.250)
GOLD = (1.000, 0.720, 0.240)
TEXT = (0.940, 0.960, 0.965)


def srgb(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def draw_icon_png(out_path: Path) -> None:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        SIZE,
        SIZE,
        8,
        4,
        True,
        False,
        NSDeviceRGBColorSpace,
        0,
        0,
    )

    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    inset = SIZE * 0.055
    rect = NSMakeRect(inset, inset, SIZE - inset * 2.0, SIZE - inset * 2.0)
    radius = SIZE * 0.225

    shadow = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(rect.origin.x, rect.origin.y - SIZE * 0.018, rect.size.width, rect.size.height),
        radius,
        radius,
    )
    srgb((0, 0, 0), 0.28).setFill()
    shadow.fill()

    shell = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
    base = NSGradient.alloc().initWithStartingColor_endingColor_(
        srgb(INK_2), srgb(INK)
    )
    base.drawInBezierPath_angle_(shell, 90.0)

    NSGraphicsContext.saveGraphicsState()
    shell.addClip()

    teal = NSBezierPath.bezierPath()
    teal.moveToPoint_(NSMakePoint(rect.origin.x - SIZE * 0.02, rect.origin.y + SIZE * 0.62))
    teal.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.90, rect.origin.y + SIZE * 1.00))
    teal.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 1.02, rect.origin.y + SIZE * 0.76))
    teal.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.15, rect.origin.y + SIZE * 0.45))
    teal.closePath()
    srgb(TEAL, 0.44).setFill()
    teal.fill()

    blue = NSBezierPath.bezierPath()
    blue.moveToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.40, rect.origin.y + SIZE * 0.95))
    blue.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 1.02, rect.origin.y + SIZE * 0.70))
    blue.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 1.02, rect.origin.y + SIZE * 0.38))
    blue.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.56, rect.origin.y + SIZE * 0.56))
    blue.closePath()
    srgb(BLUE, 0.30).setFill()
    blue.fill()

    coral = NSBezierPath.bezierPath()
    coral.moveToPoint_(NSMakePoint(rect.origin.x - SIZE * 0.02, rect.origin.y + SIZE * 0.12))
    coral.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.58, rect.origin.y + SIZE * 0.32))
    coral.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.98, rect.origin.y + SIZE * 0.12))
    coral.lineToPoint_(NSMakePoint(rect.origin.x + SIZE * 0.18, rect.origin.y - SIZE * 0.02))
    coral.closePath()
    srgb(CORAL, 0.46).setFill()
    coral.fill()

    for i in range(9):
        y = rect.origin.y + SIZE * (0.22 + i * 0.065)
        line = NSBezierPath.bezierPath()
        line.moveToPoint_(NSMakePoint(rect.origin.x - SIZE * 0.05, y))
        line.curveToPoint_controlPoint1_controlPoint2_(
            NSMakePoint(rect.origin.x + rect.size.width + SIZE * 0.05, y + SIZE * 0.035),
            NSMakePoint(rect.origin.x + SIZE * 0.28, y + SIZE * 0.070),
            NSMakePoint(rect.origin.x + SIZE * 0.70, y - SIZE * 0.055),
        )
        srgb((1, 1, 1), 0.028 + i * 0.002).setStroke()
        line.setLineWidth_(3.0)
        line.stroke()

    NSGraphicsContext.restoreGraphicsState()

    inner = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(SIZE * 0.185, SIZE * 0.225, SIZE * 0.630, SIZE * 0.550),
        SIZE * 0.135,
        SIZE * 0.135,
    )
    srgb((0.020, 0.026, 0.034), 0.32).setFill()
    inner.fill()

    wave = NSBezierPath.bezierPath()
    wave.moveToPoint_(NSMakePoint(SIZE * 0.245, SIZE * 0.505))
    wave.lineToPoint_(NSMakePoint(SIZE * 0.355, SIZE * 0.685))
    wave.lineToPoint_(NSMakePoint(SIZE * 0.485, SIZE * 0.330))
    wave.lineToPoint_(NSMakePoint(SIZE * 0.620, SIZE * 0.685))
    wave.lineToPoint_(NSMakePoint(SIZE * 0.775, SIZE * 0.430))
    srgb(TEXT, 0.96).setStroke()
    wave.setLineWidth_(64.0)
    wave.stroke()

    for x, h, alpha in (
        (0.250, 0.260, 0.45),
        (0.810, 0.180, 0.36),
        (0.185, 0.145, 0.26),
    ):
        bar = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(SIZE * x, SIZE * (0.505 - h / 2.0), SIZE * 0.030, SIZE * h),
            SIZE * 0.015,
            SIZE * 0.015,
        )
        srgb(TEAL, alpha).setFill()
        bar.fill()

    dot = NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(SIZE * 0.700, SIZE * 0.680, SIZE * 0.118, SIZE * 0.118)
    )
    srgb(GOLD, 0.98).setFill()
    dot.fill()

    srgb((1, 1, 1), 0.20).setStroke()
    shell.setLineWidth_(5.0)
    shell.stroke()

    NSGraphicsContext.restoreGraphicsState()

    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    if not data.writeToFile_atomically_(str(out_path), True):
        raise RuntimeError(f"failed to write {out_path}")


def make_iconset(base_png: Path, iconset: Path) -> None:
    iconset.mkdir(parents=True, exist_ok=True)
    variants = [
        (16, 1),
        (16, 2),
        (32, 1),
        (32, 2),
        (128, 1),
        (128, 2),
        (256, 1),
        (256, 2),
        (512, 1),
        (512, 2),
    ]
    for points, scale in variants:
        pixels = points * scale
        suffix = f"{points}x{points}" + ("@2x" if scale == 2 else "")
        out = iconset / f"icon_{suffix}.png"
        if pixels == SIZE:
            shutil.copyfile(base_png, out)
        else:
            subprocess.run(
                ["sips", "-z", str(pixels), str(pixels), str(base_png), "--out", str(out)],
                check=True,
                stdout=subprocess.DEVNULL,
            )


def write_icns(iconset: Path, out: Path) -> None:
    """Write a modern PNG-backed ICNS file."""
    chunk_files = [
        ("icp4", "icon_16x16.png"),
        ("ic11", "icon_16x16@2x.png"),
        ("icp5", "icon_32x32.png"),
        ("icp6", "icon_32x32@2x.png"),
        ("ic12", "icon_32x32@2x.png"),
        ("ic07", "icon_128x128.png"),
        ("ic13", "icon_128x128@2x.png"),
        ("ic08", "icon_256x256.png"),
        ("ic14", "icon_256x256@2x.png"),
        ("ic09", "icon_512x512.png"),
        ("ic10", "icon_512x512@2x.png"),
    ]
    chunks: list[bytes] = []
    for icon_type, filename in chunk_files:
        payload = (iconset / filename).read_bytes()
        chunks.append(icon_type.encode("ascii") + struct.pack(">I", len(payload) + 8) + payload)
    total_len = 8 + sum(len(chunk) for chunk in chunks)
    out.write_bytes(b"icns" + struct.pack(">I", total_len) + b"".join(chunks))


def compile_icns(iconset: Path, out: Path) -> None:
    write_icns(iconset, out)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("AppIcon.icns")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="persowhisper-icon-") as tmp:
        tmp_path = Path(tmp)
        base_png = tmp_path / "icon_1024.png"
        iconset = tmp_path / "AppIcon.iconset"
        draw_icon_png(base_png)
        make_iconset(base_png, iconset)
        compile_icns(iconset, out)

    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
