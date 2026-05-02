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
    NSForegroundColorAttributeName,
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
from Foundation import NSMakeRect, NSString

from .config import (
    LEVEL_GAIN,
    OVERLAY_BOTTOM_MARGIN,
    OVERLAY_HEIGHT,
    OVERLAY_WIDTH,
    WAVE_HISTORY,
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
        return self

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
            bounds, 18.0, 18.0
        )
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.04, 0.04, 0.06, 0.88).setFill()
        bg.fill()

        if self._mode == "recording":
            title = "● Recording"
            title_color = NSColor.systemRedColor()
        else:
            title = "Transcribing…"
            title_color = NSColor.whiteColor()

        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
            NSForegroundColorAttributeName: title_color,
        }
        NSString.stringWithString_(title).drawAtPoint_withAttributes_(
            (16.0, bounds.size.height - 24.0), attrs
        )

        wave_rect = NSMakeRect(
            16.0, 14.0, bounds.size.width - 32.0, bounds.size.height - 38.0
        )
        if self._mode == "recording":
            self._drawWaveform_(wave_rect)
        else:
            self._drawShimmer_(wave_rect)

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
        NSColor.whiteColor().setFill()
        for v in levels:
            h = 2.0 + v * (rect.size.height - 2.0)
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
            NSColor.colorWithSRGBRed_green_blue_alpha_(
                1.0, 1.0, 1.0, alpha
            ).setFill()
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

    def tick(self) -> None:
        if self._view is not None and self._visible:
            self._view.tick()
