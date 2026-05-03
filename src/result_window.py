"""Rendering helpers for diarized transcripts.

The actual window has been merged into [src/drop_window.py] — one window now
swaps between the hero (drop zone) and transcript states. This module owns the
attributed-string rendering, plain-text rendering, and the speaker color
palette so both modules can use them.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable, Optional

from AppKit import (
    NSAttributedString,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSFontWeightRegular,
    NSFontWeightSemibold,
    NSForegroundColorAttributeName,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
)
from Foundation import NSDictionary

from .transcribe import Segment


_SPEAKER_COLORS = [
    (0.30, 0.62, 1.00),
    (0.95, 0.45, 0.55),
    (0.45, 0.78, 0.55),
    (1.00, 0.62, 0.25),
    (0.72, 0.50, 0.95),
    (0.30, 0.78, 0.78),
    (0.95, 0.78, 0.30),
    (0.62, 0.62, 0.62),
]


def format_timestamp(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        seconds = 0.0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _speaker_index(label: Optional[str]) -> int:
    if not label:
        return -1
    digits = "".join(ch for ch in label if ch.isdigit())
    if digits:
        try:
            return int(digits)
        except ValueError:
            return 0
    return abs(hash(label)) % len(_SPEAKER_COLORS)


def speaker_color(label: Optional[str]) -> NSColor:
    idx = _speaker_index(label)
    if idx < 0:
        return NSColor.colorWithSRGBRed_green_blue_alpha_(0.55, 0.55, 0.55, 1.0)
    r, g, b = _SPEAKER_COLORS[idx % len(_SPEAKER_COLORS)]
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)


def speaker_short(label: Optional[str]) -> str:
    if not label:
        return "·"
    digits = "".join(ch for ch in label if ch.isdigit())
    if digits:
        return f"S{int(digits) + 1}"
    return label[:2].upper()


def render_transcript_text(segments: Iterable[Segment]) -> str:
    lines: list[str] = []
    for seg in segments:
        ts = format_timestamp(seg.start)
        speaker = speaker_short(seg.speaker)
        lines.append(f"[{ts}] {speaker}: {seg.text}")
    return "\n".join(lines)


def _attrs(font, color, paragraph=None) -> NSDictionary:
    pairs: list = [font, NSFontAttributeName, color, NSForegroundColorAttributeName]
    if paragraph is not None:
        pairs += [paragraph, NSParagraphStyleAttributeName]
    pairs.append(None)
    return NSDictionary.dictionaryWithObjectsAndKeys_(*pairs)


def _make_paragraph():
    p = NSMutableParagraphStyle.alloc().init()
    p.setLineHeightMultiple_(1.35)
    p.setParagraphSpacing_(8.0)
    p.setHeadIndent_(64.0)
    return p


def attributed_segment(seg: Segment) -> NSAttributedString:
    ts = format_timestamp(seg.start)
    speaker = speaker_short(seg.speaker)
    body = seg.text

    mono = NSFont.monospacedSystemFontOfSize_weight_(11.0, NSFontWeightRegular)
    badge_font = NSFont.systemFontOfSize_weight_(11.0, NSFontWeightSemibold)
    body_font = NSFont.systemFontOfSize_weight_(13.5, NSFontWeightRegular)
    para = _make_paragraph()

    out = NSMutableAttributedString.alloc().init()
    out.appendAttributedString_(
        NSAttributedString.alloc().initWithString_attributes_(
            f"{ts}  ",
            _attrs(mono, NSColor.tertiaryLabelColor(), para),
        )
    )
    out.appendAttributedString_(
        NSAttributedString.alloc().initWithString_attributes_(
            f"{speaker}  ",
            _attrs(badge_font, speaker_color(seg.speaker), para),
        )
    )
    out.appendAttributedString_(
        NSAttributedString.alloc().initWithString_attributes_(
            body + "\n",
            _attrs(body_font, NSColor.labelColor(), para),
        )
    )
    return out


def copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    except Exception as exc:
        print(f"[result_window] pbcopy failed: {exc}", file=sys.stderr)
