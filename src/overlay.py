"""Native AppKit floating panel that shows a live waveform / transcription progress."""

from __future__ import annotations

import collections
import math

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSFontWeightRegular,
    NSFontWeightSemibold,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSGradient,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakePoint, NSMakeRect, NSString

from .config import (
    LEVEL_GAIN,
    OVERLAY_BOTTOM_MARGIN,
    OVERLAY_HEIGHT,
    OVERLAY_WIDTH,
    WAVE_HISTORY,
)


_INK = (0.030, 0.035, 0.045)
_INK_2 = (0.075, 0.088, 0.105)
_TEAL = (0.000, 0.760, 0.720)
_CORAL = (1.000, 0.380, 0.250)
_TEXT = (0.940, 0.960, 0.965)


def _srgb(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


class WaveView(NSView):
    """Custom NSView that draws either a live waveform or an animated shimmer."""

    def initWithFrame_(self, frame):
        self = objc.super(WaveView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._levels = collections.deque(maxlen=WAVE_HISTORY)
        self._mode = "recording"
        self._phase = 0.0
        self._fraction = None  # None = indeterminate (model loading / VAD)
        return self

    def setMode_(self, mode):
        if mode != self._mode:
            self._mode = mode
            if mode != "recording":
                self._levels.clear()
                self._fraction = None
        self.setNeedsDisplay_(True)

    @objc.python_method
    def update_progress(self, fraction):
        # Stored for the next drawRect_; the caller ticks immediately after.
        self._fraction = fraction

    def pushLevel_(self, level):
        v = level * LEVEL_GAIN
        if v < 0.0:
            v = 0.0
        elif v > 1.0:
            v = 1.0
        self._levels.append(v)

    def tick(self):
        self._phase = (self._phase + 0.18) % (math.pi * 2.0)
        self.setNeedsDisplay_(True)

    def drawRect_(self, _dirty):
        bounds = self.bounds()
        bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0.5, 0.5, bounds.size.width - 1.0, bounds.size.height - 1.0),
            19.0,
            19.0,
        )
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _srgb(_INK_2, 0.94), _srgb(_INK, 0.94)
        )
        gradient.drawInBezierPath_angle_(bg, 90.0)

        NSGraphicsContext.saveGraphicsState()
        bg.addClip()
        band = NSBezierPath.bezierPath()
        band.moveToPoint_(NSMakePoint(0, bounds.size.height * 0.65))
        band.lineToPoint_(NSMakePoint(bounds.size.width, bounds.size.height * 0.82))
        band.lineToPoint_(NSMakePoint(bounds.size.width, bounds.size.height))
        band.lineToPoint_(NSMakePoint(0, bounds.size.height))
        band.closePath()
        _srgb(_TEAL, 0.12).setFill()
        band.fill()

        accent = NSBezierPath.bezierPath()
        accent.moveToPoint_(NSMakePoint(0, 0))
        accent.lineToPoint_(NSMakePoint(bounds.size.width * 0.52, 0))
        accent.lineToPoint_(NSMakePoint(bounds.size.width * 0.16, bounds.size.height * 0.24))
        accent.lineToPoint_(NSMakePoint(0, bounds.size.height * 0.18))
        accent.closePath()
        _srgb(_CORAL, 0.12).setFill()
        accent.fill()
        NSGraphicsContext.restoreGraphicsState()

        _srgb((1, 1, 1), 0.16).setStroke()
        bg.setLineWidth_(1.0)
        bg.stroke()

        if self._mode == "recording":
            title = "Recording"
            title_color = _srgb(_CORAL)
            status_color = _srgb(_CORAL)
        else:
            # No fraction yet → the model is still loading / running VAD.
            title = "Loading…" if self._fraction is None else "Transcribing…"
            title_color = _srgb(_TEXT)
            status_color = _srgb(_TEAL)

        dot = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(16.0, bounds.size.height - 23.0, 8.0, 8.0)
        )
        status_color.setFill()
        dot.fill()

        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(
                11.0, NSFontWeightSemibold
            ),
            NSForegroundColorAttributeName: title_color,
        }
        NSString.stringWithString_(title).drawAtPoint_withAttributes_(
            (30.0, bounds.size.height - 24.0), attrs
        )

        wave_rect = NSMakeRect(
            16.0, 14.0, bounds.size.width - 32.0, bounds.size.height - 38.0
        )
        if self._mode == "recording":
            self._drawWaveform_(wave_rect)
        else:
            self._drawProgress(bounds, wave_rect)

    def _drawWaveform_(self, rect):
        bar_w = 3.0
        gap = 2.0
        slot = bar_w + gap
        max_bars = max(1, int(rect.size.width // slot))
        levels = list(self._levels)[-max_bars:]
        if not levels:
            levels = [0.0]
        if len(levels) < max_bars:
            levels = [0.0] * (max_bars - len(levels)) + levels
        x = rect.origin.x + (rect.size.width - max_bars * slot) / 2.0
        cy = rect.origin.y + rect.size.height / 2.0
        for v in levels:
            h = 2.0 + v * (rect.size.height - 2.0)
            color = _TEAL if v > 0.28 else (1.0, 1.0, 1.0)
            _srgb(color, 0.46 + min(0.48, v * 0.70)).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, cy - h / 2.0, bar_w, h), 1.5, 1.5
            ).fill()
            x += slot

    @objc.python_method
    def _drawProgress(self, bounds, rect):
        """A progress bar showing the % of audio transcribed. While the model
        loads (no fraction yet) the bar sweeps as an indeterminate."""
        digit_font = NSFont.monospacedDigitSystemFontOfSize_weight_(
            11.0, NSFontWeightRegular
        )

        # Progress track, leaving room for the percentage on the right.
        pct_w = 42.0
        gap = 10.0
        track_h = 7.0
        track_x = rect.origin.x
        track_w = rect.size.width - pct_w - gap
        cy = rect.origin.y + rect.size.height / 2.0
        track_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(track_x, cy - track_h / 2.0, track_w, track_h),
            track_h / 2.0,
            track_h / 2.0,
        )
        _srgb((1.0, 1.0, 1.0), 0.10).setFill()
        track_path.fill()

        if self._fraction is None:
            # Indeterminate sweep during model load / VAD.
            NSGraphicsContext.saveGraphicsState()
            track_path.addClip()
            seg_w = track_w * 0.34
            t = math.sin(self._phase * 0.8) * 0.5 + 0.5
            seg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(track_x + t * (track_w - seg_w), cy - track_h / 2.0,
                           seg_w, track_h),
                track_h / 2.0,
                track_h / 2.0,
            )
            NSGradient.alloc().initWithStartingColor_endingColor_(
                _srgb(_TEAL, 0.0), _srgb(_TEAL, 0.85)
            ).drawInBezierPath_angle_(seg, 0.0)
            NSGraphicsContext.restoreGraphicsState()
            pct_text = "…"
        else:
            f = self._fraction
            f = 0.0 if f < 0.0 else 1.0 if f > 1.0 else f
            fill_w = track_w * f
            if 0.0 < fill_w < track_h:
                fill_w = track_h  # keep a visible rounded cap at very low %
            if fill_w > 0.0:
                _srgb(_TEAL, 0.92).setFill()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(track_x, cy - track_h / 2.0, fill_w, track_h),
                    track_h / 2.0,
                    track_h / 2.0,
                ).fill()
            pct_text = f"{int(f * 100)}%"

        # Percentage (or '…' while loading), right-aligned beside the bar.
        ns_pct = NSString.stringWithString_(pct_text)
        pct_attrs = {
            NSFontAttributeName: digit_font,
            NSForegroundColorAttributeName: _srgb(_TEXT, 0.92),
        }
        pct_size = ns_pct.sizeWithAttributes_(pct_attrs)
        px = rect.origin.x + rect.size.width - float(pct_size.width)
        py = cy - float(pct_size.height) / 2.0
        ns_pct.drawAtPoint_withAttributes_((px, py), pct_attrs)


class Overlay:
    """Lazily-built floating NSPanel that hosts a WaveView."""

    def __init__(self) -> None:
        self._panel = None
        self._view = None
        self._visible = False

    def _ensure_built(self) -> bool:
        if self._panel is not None:
            return True
        screen = NSScreen.mainScreen()
        if screen is None:
            return False
        sf_ = screen.frame()
        x = sf_.origin.x + (sf_.size.width - OVERLAY_WIDTH) / 2.0
        y = sf_.origin.y + OVERLAY_BOTTOM_MARGIN
        rect = NSMakeRect(x, y, OVERLAY_WIDTH, OVERLAY_HEIGHT)
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        # Purely informational overlay — let clicks pass straight through to
        # whatever is underneath so the foreground app keeps focus.
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        view = WaveView.alloc().initWithFrame_(
            NSMakeRect(0, 0, OVERLAY_WIDTH, OVERLAY_HEIGHT)
        )
        panel.setContentView_(view)
        self._panel = panel
        self._view = view
        return True

    def show(self, mode: str) -> None:
        if not self._ensure_built():
            return
        self._view.setMode_(mode)
        if not self._visible:
            self._panel.orderFrontRegardless()
            self._visible = True

    def hide(self) -> None:
        if self._panel is None or not self._visible:
            return
        self._panel.orderOut_(None)
        self._visible = False

    def push_level(self, level: float) -> None:
        if self._view is not None:
            self._view.pushLevel_(level)

    def update_progress(self, fraction) -> None:
        if self._view is not None:
            self._view.update_progress(fraction)

    def tick(self) -> None:
        if self._view is not None and self._visible:
            self._view.tick()
