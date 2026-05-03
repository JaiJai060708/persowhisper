"""Native AppKit floating panel that shows a live waveform / progress shimmer."""

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
    NSFontWeightMedium,
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
    AVAILABLE_MODELS,
    LEVEL_GAIN,
    OVERLAY_BOTTOM_MARGIN,
    OVERLAY_HEIGHT,
    OVERLAY_WIDTH,
    WAVE_HISTORY,
)
from .settings import SETTINGS


_INK = (0.030, 0.035, 0.045)
_INK_2 = (0.075, 0.088, 0.105)
_TEAL = (0.000, 0.760, 0.720)
_CORAL = (1.000, 0.380, 0.250)
_GOLD = (1.000, 0.720, 0.240)
_TEXT = (0.940, 0.960, 0.965)


def _srgb(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def _point_in_rect(pt, r) -> bool:
    return (
        r.origin.x <= pt.x < r.origin.x + r.size.width
        and r.origin.y <= pt.y < r.origin.y + r.size.height
    )


class WaveView(NSView):
    """Custom NSView that draws either a live waveform or an animated shimmer."""

    def initWithFrame_(self, frame):
        self = objc.super(WaveView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._levels = collections.deque(maxlen=WAVE_HISTORY)
        self._mode = "recording"
        self._phase = 0.0
        self._button_rects: dict = {}
        return self

    def acceptsFirstMouse_(self, _event):
        # Receive clicks even when our (nonactivating) panel isn't key —
        # otherwise the first click on a non-key window is swallowed.
        return True

    def mouseDown_(self, event):
        loc = event.locationInWindow()
        pt = self.convertPoint_fromView_(loc, None)
        for model, rect in self._button_rects.items():
            if _point_in_rect(pt, rect):
                if SETTINGS.set_model(model):
                    self.setNeedsDisplay_(True)
                return

    def setMode_(self, mode):
        if mode != self._mode:
            self._mode = mode
            if mode != "recording":
                self._levels.clear()
        self.setNeedsDisplay_(True)

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
            title = "Transcribing…"
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

        self._drawButtons_(bounds)

        wave_rect = NSMakeRect(
            16.0, 14.0, bounds.size.width - 32.0, bounds.size.height - 38.0
        )
        if self._mode == "recording":
            self._drawWaveform_(wave_rect)
        else:
            self._drawShimmer_(wave_rect)

    def _drawButtons_(self, bounds):
        """Draw the model picker pills, right-aligned in the title row.
        Updates self._button_rects so mouseDown_ can hit-test them."""
        self._button_rects.clear()
        font = NSFont.systemFontOfSize_weight_(10.0, NSFontWeightMedium)
        sizing_attrs = {NSFontAttributeName: font}
        widths = {}
        for m in AVAILABLE_MODELS:
            sz = NSString.stringWithString_(m).sizeWithAttributes_(sizing_attrs)
            widths[m] = float(sz.width) + 14.0  # internal padding

        gap = 6.0
        btn_h = 18.0
        btn_y = bounds.size.height - 27.0
        right_pad = 14.0
        total_w = sum(widths.values()) + gap * (len(AVAILABLE_MODELS) - 1)
        x = bounds.size.width - right_pad - total_w

        current = SETTINGS.model
        for m in AVAILABLE_MODELS:
            w = widths[m]
            rect = NSMakeRect(x, btn_y, w, btn_h)
            self._button_rects[m] = rect
            active = m == current

            fill = _srgb(_TEAL, 0.22) if active else _srgb((1.0, 1.0, 1.0), 0.07)
            fill.setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                rect, btn_h / 2.0, btn_h / 2.0
            ).fill()
            if active:
                _srgb(_TEAL, 0.82).setStroke()
                stroke_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    rect, btn_h / 2.0, btn_h / 2.0
                )
                stroke_path.setLineWidth_(1.0)
                stroke_path.stroke()

            text_color = (
                _srgb(_TEXT)
                if active
                else _srgb((1.0, 1.0, 1.0), 0.62)
            )
            text_attrs = {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: text_color,
            }
            ns_text = NSString.stringWithString_(m)
            text_size = ns_text.sizeWithAttributes_(text_attrs)
            tx = rect.origin.x + (rect.size.width - float(text_size.width)) / 2.0
            ty = rect.origin.y + (rect.size.height - float(text_size.height)) / 2.0
            ns_text.drawAtPoint_withAttributes_((tx, ty), text_attrs)

            x += w + gap

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

    def _drawShimmer_(self, rect):
        bar_w = 3.0
        gap = 2.0
        slot = bar_w + gap
        n = max(1, int(rect.size.width // slot))
        x0 = rect.origin.x + (rect.size.width - n * slot) / 2.0
        cy = rect.origin.y + rect.size.height / 2.0
        for i in range(n):
            t = i / max(1, n - 1)
            mag = 0.45 + 0.45 * (math.sin(self._phase + t * math.pi * 2.0) * 0.5 + 0.5)
            h = 2.0 + mag * (rect.size.height - 2.0)
            alpha = 0.35 + 0.55 * (
                math.sin(self._phase * 0.6 + t * math.pi * 1.5) * 0.5 + 0.5
            )
            color = _TEAL if i % 4 else _GOLD
            _srgb(color, alpha).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x0 + i * slot, cy - h / 2.0, bar_w, h), 1.5, 1.5
            ).fill()


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
        # Receive clicks (the model-picker pills) but stay nonactivating so
        # the user's foreground app keeps key focus for the eventual paste.
        panel.setIgnoresMouseEvents_(False)
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

    def tick(self) -> None:
        if self._view is not None and self._visible:
            self._view.tick()
