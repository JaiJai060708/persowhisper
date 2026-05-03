"""Single-window UI: hero (drop zone) ↔ transcript view in the same window.

When a file is accepted (drop or browse), the hero view hides and the
transcript view shows. While whisperx runs, partial segments stream in. After
diarization finishes, segments get re-rendered with speaker colors. A "New
file" button returns to the hero view.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional

import objc
from AppKit import (
    NSApp,
    NSAppearance,
    NSAppearanceNameVibrantDark,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSBezierPath,
    NSButton,
    NSColor,
    NSDragOperationCopy,
    NSDragOperationNone,
    NSFont,
    NSFontAttributeName,
    NSFontWeightBold,
    NSFontWeightMedium,
    NSFontWeightRegular,
    NSFontWeightSemibold,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSGradient,
    NSMakeRange,
    NSObject,
    NSProgressIndicator,
    NSProgressIndicatorStyleSpinning,
    NSSavePanel,
    NSScrollView,
    NSSegmentSwitchTrackingSelectOne,
    NSSegmentedControl,
    NSTextAlignmentCenter,
    NSTextField,
    NSTextView,
    NSURL,
    NSView,
    NSViewHeightSizable,
    NSViewMaxXMargin,
    NSViewMaxYMargin,
    NSViewMinXMargin,
    NSViewMinYMargin,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialUnderWindowBackground,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSDictionary, NSMakePoint, NSMakeRect, NSMakeSize, NSOperationQueue

from .config import SUPPORTED_AUDIO_EXTS, SUPPORTED_VIDEO_EXTS
from .log_stream import (
    MAX_LOG_CHARS,
    add_listener as add_log_listener,
    snapshot as log_snapshot,
)
from .result_window import (
    attributed_segment,
    copy_to_clipboard,
    render_transcript_text,
)
from .transcribe import Segment


_ALL_EXTS = set(e.lower() for e in (SUPPORTED_AUDIO_EXTS + SUPPORTED_VIDEO_EXTS))
_TAB_TRANSCRIPT = 0
_TAB_LOGS = 1

_INK = (0.035, 0.041, 0.050)
_INK_2 = (0.060, 0.071, 0.084)
_PANEL = (0.105, 0.123, 0.140)
_TEAL = (0.000, 0.760, 0.720)
_CORAL = (1.000, 0.380, 0.250)
_GOLD = (1.000, 0.720, 0.240)
_TEXT = (0.940, 0.960, 0.965)
_TEXT_MUTED = (0.610, 0.670, 0.700)


def _srgb(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def _is_supported(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in _ALL_EXTS


def _label(text, *, size, weight, color, align=None):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setStringValue_(text)
    f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
    f.setTextColor_(color)
    if align is not None:
        f.setAlignment_(align)
    return f


def _hairline(frame, alpha=0.10):
    v = NSView.alloc().initWithFrame_(frame)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(
        _srgb((1, 1, 1), alpha).CGColor()
    )
    return v


def _attrs(font, color):
    return NSDictionary.dictionaryWithObjectsAndKeys_(
        font,
        NSFontAttributeName,
        color,
        NSForegroundColorAttributeName,
        None,
    )


def _run_on_main(callable_, *args) -> None:
    NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: callable_(*args))


class ThemeBackdropView(NSView):
    """Window-wide acoustic theme: ink base, angled bands, and soft wave lines."""

    def isOpaque(self):
        return True

    def drawRect_(self, _rect):
        bounds = self.bounds()
        base = NSBezierPath.bezierPathWithRect_(bounds)
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _srgb(_INK_2), _srgb(_INK)
        )
        gradient.drawInBezierPath_angle_(base, 90.0)

        NSGraphicsContext.saveGraphicsState()
        base.addClip()

        top = NSBezierPath.bezierPath()
        top.moveToPoint_(NSMakePoint(0, bounds.size.height * 0.72))
        top.lineToPoint_(NSMakePoint(bounds.size.width, bounds.size.height * 0.88))
        top.lineToPoint_(NSMakePoint(bounds.size.width, bounds.size.height))
        top.lineToPoint_(NSMakePoint(0, bounds.size.height))
        top.closePath()
        _srgb(_TEAL, 0.090).setFill()
        top.fill()

        lower = NSBezierPath.bezierPath()
        lower.moveToPoint_(NSMakePoint(0, 0))
        lower.lineToPoint_(NSMakePoint(bounds.size.width, 0))
        lower.lineToPoint_(NSMakePoint(bounds.size.width, bounds.size.height * 0.22))
        lower.lineToPoint_(NSMakePoint(0, bounds.size.height * 0.06))
        lower.closePath()
        _srgb(_CORAL, 0.060).setFill()
        lower.fill()

        for i in range(7):
            y = 42.0 + i * 54.0
            line = NSBezierPath.bezierPath()
            line.moveToPoint_(NSMakePoint(-24.0, y))
            line.curveToPoint_controlPoint1_controlPoint2_(
                NSMakePoint(bounds.size.width + 28.0, y + 20.0),
                NSMakePoint(bounds.size.width * 0.28, y + 34.0),
                NSMakePoint(bounds.size.width * 0.68, y - 24.0),
            )
            _srgb((1, 1, 1), 0.025 + i * 0.003).setStroke()
            line.setLineWidth_(1.0)
            line.stroke()

        NSGraphicsContext.restoreGraphicsState()


class ContentSurfaceView(NSView):
    """Subtle framed surface used behind transcript and logs."""

    def drawRect_(self, _rect):
        bounds = self.bounds()
        rect = NSMakeRect(
            bounds.origin.x + 0.5,
            bounds.origin.y + 0.5,
            bounds.size.width - 1.0,
            bounds.size.height - 1.0,
        )
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 14.0, 14.0)
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _srgb(_PANEL, 0.64), _srgb((0.070, 0.082, 0.096), 0.76)
        )
        gradient.drawInBezierPath_angle_(path, 90.0)
        _srgb((1, 1, 1), 0.12).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()


class LogoMarkView(NSView):
    """PersoWhisper mark used in the header and hero."""

    def drawRect_(self, _rect):
        bounds = self.bounds()
        side = min(bounds.size.width, bounds.size.height)
        x = bounds.origin.x + (bounds.size.width - side) / 2.0
        y = bounds.origin.y + (bounds.size.height - side) / 2.0
        rect = NSMakeRect(x + side * 0.04, y + side * 0.04, side * 0.92, side * 0.92)
        radius = side * 0.24
        shell = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, radius, radius
        )
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            _srgb((0.030, 0.100, 0.125)), _srgb((0.020, 0.035, 0.050))
        )
        gradient.drawInBezierPath_angle_(shell, 132.0)

        NSGraphicsContext.saveGraphicsState()
        shell.addClip()

        teal = NSBezierPath.bezierPath()
        teal.moveToPoint_(NSMakePoint(rect.origin.x, rect.origin.y + side * 0.62))
        teal.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.86, rect.origin.y + side * 0.96))
        teal.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.96, rect.origin.y + side * 0.74))
        teal.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.18, rect.origin.y + side * 0.46))
        teal.closePath()
        _srgb(_TEAL, 0.42).setFill()
        teal.fill()

        coral = NSBezierPath.bezierPath()
        coral.moveToPoint_(NSMakePoint(rect.origin.x + side * 0.04, rect.origin.y + side * 0.14))
        coral.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.68, rect.origin.y + side * 0.36))
        coral.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.96, rect.origin.y + side * 0.18))
        coral.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.22, rect.origin.y))
        coral.closePath()
        _srgb(_CORAL, 0.48).setFill()
        coral.fill()

        NSGraphicsContext.restoreGraphicsState()

        _srgb((1, 1, 1), 0.20).setStroke()
        shell.setLineWidth_(1.0)
        shell.stroke()

        wave = NSBezierPath.bezierPath()
        wave.moveToPoint_(NSMakePoint(rect.origin.x + side * 0.20, rect.origin.y + side * 0.50))
        wave.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.34, rect.origin.y + side * 0.68))
        wave.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.48, rect.origin.y + side * 0.30))
        wave.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.62, rect.origin.y + side * 0.68))
        wave.lineToPoint_(NSMakePoint(rect.origin.x + side * 0.80, rect.origin.y + side * 0.42))
        _srgb(_TEXT, 0.94).setStroke()
        wave.setLineWidth_(max(2.0, side * 0.065))
        wave.stroke()

        dot = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(
                rect.origin.x + side * 0.72,
                rect.origin.y + side * 0.66,
                side * 0.13,
                side * 0.13,
            )
        )
        _srgb(_GOLD, 0.95).setFill()
        dot.fill()


class DropView(NSView):
    """Rounded acoustic drop zone with waveform texture and drag highlight."""

    def initWithFrame_(self, frame):
        self = objc.super(DropView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._dragging = False
        self._on_drop: Optional[Callable[[Path], None]] = None
        self.registerForDraggedTypes_(["public.file-url", "NSFilenamesPboardType"])
        return self

    def setOnDrop_(self, callback):
        self._on_drop = callback

    def acceptsFirstMouse_(self, _e):
        return True

    def isFlipped(self):
        return False

    def drawRect_(self, _rect):
        bounds = self.bounds()
        inset = 24.0
        rect = NSMakeRect(
            bounds.origin.x + inset,
            bounds.origin.y + inset,
            bounds.size.width - 2 * inset,
            bounds.size.height - 2 * inset,
        )
        radius = 22.0
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)

        if self._dragging:
            top = _srgb((0.050, 0.600, 0.650), 0.36)
            bot = _srgb((0.090, 0.240, 0.500), 0.30)
            border = _srgb(_TEAL, 0.98)
            border_w = 2.0
        else:
            top = _srgb((0.150, 0.190, 0.210), 0.56)
            bot = _srgb((0.065, 0.074, 0.086), 0.76)
            border = _srgb((1.0, 1.0, 1.0), 0.18)
            border_w = 1.5

        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(bot, top)
        gradient.drawInBezierPath_angle_(path, 90.0)

        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        band = NSBezierPath.bezierPath()
        band.moveToPoint_(NSMakePoint(rect.origin.x, rect.origin.y + rect.size.height * 0.64))
        band.lineToPoint_(NSMakePoint(rect.origin.x + rect.size.width, rect.origin.y + rect.size.height * 0.78))
        band.lineToPoint_(NSMakePoint(rect.origin.x + rect.size.width, rect.origin.y + rect.size.height))
        band.lineToPoint_(NSMakePoint(rect.origin.x, rect.origin.y + rect.size.height))
        band.closePath()
        _srgb(_TEAL, 0.105 if self._dragging else 0.065).setFill()
        band.fill()

        wave_y = rect.origin.y + rect.size.height * 0.30
        wave_h = rect.size.height * 0.26
        slots = 34
        slot = rect.size.width / slots
        for i in range(slots):
            t = i / max(1, slots - 1)
            mag = 0.20 + 0.80 * (
                math.sin(t * math.pi * 3.0) * math.sin(t * math.pi) * 0.5 + 0.5
            )
            h = 4.0 + mag * wave_h
            x = rect.origin.x + i * slot + slot * 0.35
            alpha = 0.11 + 0.11 * math.sin(t * math.pi)
            _srgb(_TEAL if i % 3 else _GOLD, alpha).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, wave_y - h / 2.0, max(2.0, slot * 0.22), h),
                2.0,
                2.0,
            ).fill()
        NSGraphicsContext.restoreGraphicsState()

        border.setStroke()
        path.setLineWidth_(border_w)
        if not self._dragging:
            path.setLineDash_count_phase_([8.0, 6.0], 2, 0.0)
        path.stroke()

    def _first_supported_url(self, sender):
        pb = sender.draggingPasteboard()
        urls = pb.readObjectsForClasses_options_([NSURL], None)
        if urls:
            for u in urls:
                p = Path(u.path())
                if _is_supported(p):
                    return p
        files = pb.propertyListForType_("NSFilenamesPboardType")
        if files:
            for f in files:
                p = Path(f)
                if _is_supported(p):
                    return p
        return None

    def draggingEntered_(self, sender):
        if self._first_supported_url(sender) is None:
            return NSDragOperationNone
        self._dragging = True
        self.setNeedsDisplay_(True)
        return NSDragOperationCopy

    def draggingExited_(self, _sender):
        self._dragging = False
        self.setNeedsDisplay_(True)

    def draggingEnded_(self, _sender):
        self._dragging = False
        self.setNeedsDisplay_(True)

    def prepareForDragOperation_(self, sender):
        return self._first_supported_url(sender) is not None

    def performDragOperation_(self, sender):
        path = self._first_supported_url(sender)
        self._dragging = False
        self.setNeedsDisplay_(True)
        if path is None:
            return False
        if self._on_drop is not None:
            self._on_drop(path)
        return True


class DropWindowController(NSObject):
    """One window, two states. Public API used by FileJobController:
        prepare_for_path(path) → switches to transcript mode, blank
        append_partial(seg)    → live-append a streamed segment
        commit_final(segs)     → replace with diarized final
        mark_failed(msg)
        mark_cancelling()
        mark_cancelled()
        set_status(text)
    All public methods must be called on the main thread.
    """

    def initWithFileJob_(self, file_job):
        self = objc.super(DropWindowController, self).init()
        if self is None:
            return None
        self._file_job = file_job
        self._segments: list[Segment] = []
        self._final = False
        self._stopping = False
        self._active_tab = _TAB_TRANSCRIPT
        self._current_path: Optional[Path] = None
        self._build_window()
        self._attach_logs()
        self._show_hero()
        return self

    # --- construction ------------------------------------------------------

    def _build_window(self) -> None:
        width, height = 760.0, 560.0
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskFullSizeContentView
        )
        rect = NSMakeRect(0.0, 0.0, width, height)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        win.setTitle_("PersoWhisper")
        win.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameVibrantDark))
        win.setTitlebarAppearsTransparent_(True)
        win.setReleasedWhenClosed_(False)
        win.setMinSize_(NSMakeSize(560.0, 380.0))
        win.setMovableByWindowBackground_(True)
        win.setDelegate_(self)
        win.center()

        bg = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        bg.setMaterial_(NSVisualEffectMaterialUnderWindowBackground)
        bg.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        bg.setState_(NSVisualEffectStateActive)
        bg.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        win.setContentView_(bg)

        cw, ch = width, height
        header_h = 72.0
        footer_h = 56.0

        chrome = ThemeBackdropView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        chrome.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        bg.addSubview_(chrome)

        # --- Header -------------------------------------------------------
        header = NSView.alloc().initWithFrame_(NSMakeRect(0, ch - header_h, cw, header_h))
        header.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)

        header_logo = LogoMarkView.alloc().initWithFrame_(NSMakeRect(20, 16, 40, 40))
        header.addSubview_(header_logo)

        title = _label(
            "PersoWhisper", size=16, weight=NSFontWeightSemibold,
            color=_srgb(_TEXT),
        )
        title.setFrame_(NSMakeRect(70, header_h - 52, cw - 380, 22))
        title.setAutoresizingMask_(NSViewWidthSizable)
        header.addSubview_(title)

        subtitle = _label(
            "Local transcription workspace",
            size=11.5, weight=NSFontWeightRegular,
            color=_srgb(_TEXT_MUTED),
        )
        subtitle.setFrame_(NSMakeRect(70, 8, cw - 260, 16))
        subtitle.setAutoresizingMask_(NSViewWidthSizable)
        header.addSubview_(subtitle)

        # Status pill (top-right)
        pill_w, pill_h = 70.0, 22.0
        tabs_w, tabs_h = 178.0, 24.0
        tabs = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(
                cw - 20 - pill_w - 10 - tabs_w,
                header_h - tabs_h - 14,
                tabs_w,
                tabs_h,
            )
        )
        tabs.setSegmentCount_(2)
        tabs.setLabel_forSegment_("Transcript", _TAB_TRANSCRIPT)
        tabs.setLabel_forSegment_("Logs", _TAB_LOGS)
        tabs.setWidth_forSegment_(98.0, _TAB_TRANSCRIPT)
        tabs.setWidth_forSegment_(70.0, _TAB_LOGS)
        tabs.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
        tabs.setSelectedSegment_(_TAB_TRANSCRIPT)
        tabs.setTarget_(self)
        tabs.setAction_("_onTabChanged:")
        tabs.setHidden_(True)
        tabs.setAutoresizingMask_(NSViewMinXMargin)
        header.addSubview_(tabs)

        pill = NSView.alloc().initWithFrame_(
            NSMakeRect(cw - 20 - pill_w, header_h - pill_h - 14, pill_w, pill_h)
        )
        pill.setWantsLayer_(True)
        pill.layer().setCornerRadius_(pill_h / 2.0)
        pill.setHidden_(True)
        pill.setAutoresizingMask_(NSViewMinXMargin)
        pill_label = _label(
            "", size=10, weight=NSFontWeightBold,
            color=_srgb(_TEXT), align=NSTextAlignmentCenter,
        )
        pill_label.setFrame_(NSMakeRect(0, 3, pill_w, pill_h - 4))
        pill.addSubview_(pill_label)
        header.addSubview_(pill)

        bg.addSubview_(header)

        sep_top = _hairline(NSMakeRect(20, ch - header_h, cw - 40, 0.5))
        sep_top.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        bg.addSubview_(sep_top)

        # --- Body container (hero + transcript layered, only one visible) -
        body_y = footer_h
        body_h = ch - header_h - footer_h
        body_frame = NSMakeRect(0, body_y, cw, body_h)

        # Hero subview
        hero = NSView.alloc().initWithFrame_(body_frame)
        hero.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        drop = DropView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, body_h))
        drop.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        drop.setOnDrop_(self._handle_drop)
        hero.addSubview_(drop)

        hero_logo = LogoMarkView.alloc().initWithFrame_(
            NSMakeRect((cw - 72.0) / 2.0, body_h / 2.0 + 34.0, 72.0, 72.0)
        )
        hero_logo.setAutoresizingMask_(
            NSViewMinXMargin | NSViewMaxXMargin | NSViewMinYMargin | NSViewMaxYMargin
        )
        hero.addSubview_(hero_logo)

        hero_title = _label(
            "Drop audio or video",
            size=23, weight=NSFontWeightSemibold,
            color=_srgb(_TEXT), align=NSTextAlignmentCenter,
        )
        hero_title.setFrame_(NSMakeRect(24, body_h / 2 - 14, cw - 48, 30))
        hero_title.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin | NSViewMaxYMargin)
        hero.addSubview_(hero_title)

        hero_sub = _label(
            "Fast local transcripts with speaker-aware output",
            size=12.5, weight=NSFontWeightRegular,
            color=_srgb(_TEXT_MUTED), align=NSTextAlignmentCenter,
        )
        hero_sub.setFrame_(NSMakeRect(32, body_h / 2 - 42, cw - 64, 18))
        hero_sub.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin | NSViewMaxYMargin)
        hero.addSubview_(hero_sub)

        hero_meta = _label(
            "MP3 · M4A · WAV · MOV · MP4",
            size=10.5, weight=NSFontWeightMedium,
            color=_srgb((0.620, 0.860, 0.840), 0.82), align=NSTextAlignmentCenter,
        )
        hero_meta.setFrame_(NSMakeRect(32, body_h / 2 - 70, cw - 64, 16))
        hero_meta.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin | NSViewMaxYMargin)
        hero.addSubview_(hero_meta)

        bg.addSubview_(hero)

        # Transcript subview
        transcript = NSView.alloc().initWithFrame_(body_frame)
        transcript.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content_frame = NSMakeRect(20, 12, cw - 40, body_h - 24)
        transcript_panel = ContentSurfaceView.alloc().initWithFrame_(content_frame)
        transcript_panel.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        transcript.addSubview_(transcript_panel)
        scroll = NSScrollView.alloc().initWithFrame_(content_frame)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(0)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, cw - 40, body_h - 24))
        tv.setEditable_(False)
        tv.setSelectable_(True)
        tv.setRichText_(True)
        tv.setDrawsBackground_(False)
        tv.setTextContainerInset_(NSMakeSize(28.0, 22.0))
        tv.setAutoresizingMask_(NSViewWidthSizable)
        scroll.setDocumentView_(tv)
        transcript.addSubview_(scroll)
        bg.addSubview_(transcript)

        # Logs subview
        logs = NSView.alloc().initWithFrame_(body_frame)
        logs.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        log_panel = ContentSurfaceView.alloc().initWithFrame_(content_frame)
        log_panel.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        logs.addSubview_(log_panel)
        log_scroll = NSScrollView.alloc().initWithFrame_(content_frame)
        log_scroll.setHasVerticalScroller_(True)
        log_scroll.setHasHorizontalScroller_(False)
        log_scroll.setAutohidesScrollers_(True)
        log_scroll.setDrawsBackground_(False)
        log_scroll.setBorderType_(0)
        log_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        log_tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, cw - 40, body_h - 24))
        log_tv.setEditable_(False)
        log_tv.setSelectable_(True)
        log_tv.setRichText_(True)
        log_tv.setDrawsBackground_(False)
        log_tv.setTextContainerInset_(NSMakeSize(18.0, 16.0))
        log_tv.setAutoresizingMask_(NSViewWidthSizable)
        log_font = NSFont.monospacedSystemFontOfSize_weight_(11.5, NSFontWeightRegular)
        log_tv.setFont_(log_font)
        log_tv.setTextColor_(_srgb((0.770, 0.820, 0.830)))
        log_scroll.setDocumentView_(log_tv)
        logs.addSubview_(log_scroll)
        bg.addSubview_(logs)

        # --- Footer -------------------------------------------------------
        footer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, footer_h))
        footer.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)

        sep_bot = _hairline(NSMakeRect(20, footer_h - 0.5, cw - 40, 0.5))
        sep_bot.setAutoresizingMask_(NSViewWidthSizable)
        footer.addSubview_(sep_bot)

        spinner = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(24, (footer_h - 16) / 2, 16, 16)
        )
        spinner.setStyle_(NSProgressIndicatorStyleSpinning)
        spinner.setDisplayedWhenStopped_(False)
        spinner.setControlSize_(1)
        footer.addSubview_(spinner)

        status = _label(
            "", size=11.5, weight=NSFontWeightRegular,
            color=_srgb(_TEXT_MUTED),
        )
        status.setFrame_(NSMakeRect(48, (footer_h - 18) / 2, cw - 360, 18))
        status.setAutoresizingMask_(NSViewWidthSizable)
        footer.addSubview_(status)

        # Right-side buttons. Browse for hero; Copy/Export/New or Stop for transcript.
        btn_w, btn_h = 96.0, 28.0
        gap = 8.0

        browse_w = 110.0
        browse = self._make_button(
            "Browse…", cw - 20 - browse_w, (footer_h - btn_h) / 2, browse_w, btn_h, "_onBrowse:"
        )
        browse.setKeyEquivalent_("\r")
        browse.setAutoresizingMask_(NSViewMinXMargin)
        footer.addSubview_(browse)

        x = cw - 20 - btn_w
        new_btn = self._make_button("New file", x, (footer_h - btn_h) / 2, btn_w, btn_h, "_onNewFile:")
        new_btn.setAutoresizingMask_(NSViewMinXMargin)
        footer.addSubview_(new_btn)

        stop_btn = self._make_button("Stop", x, (footer_h - btn_h) / 2, btn_w, btn_h, "_onStop:")
        stop_btn.setAutoresizingMask_(NSViewMinXMargin)
        footer.addSubview_(stop_btn)

        x -= gap + btn_w
        export_btn = self._make_button("Export…", x, (footer_h - btn_h) / 2, btn_w, btn_h, "_onExport:")
        export_btn.setAutoresizingMask_(NSViewMinXMargin)
        footer.addSubview_(export_btn)

        x -= gap + btn_w
        copy_btn = self._make_button("Copy", x, (footer_h - btn_h) / 2, btn_w, btn_h, "_onCopy:")
        copy_btn.setAutoresizingMask_(NSViewMinXMargin)
        footer.addSubview_(copy_btn)

        bg.addSubview_(footer)

        # Stash references
        self._window = win
        self._title = title
        self._subtitle = subtitle
        self._tabs = tabs
        self._pill = pill
        self._pill_label = pill_label
        self._hero = hero
        self._transcript = transcript
        self._logs = logs
        self._text_view = tv
        self._log_text_view = log_tv
        self._log_attrs = _attrs(log_font, NSColor.secondaryLabelColor())
        self._spinner = spinner
        self._status = status
        self._browse_btn = browse
        self._copy_btn = copy_btn
        self._export_btn = export_btn
        self._new_btn = new_btn
        self._stop_btn = stop_btn

    def _make_button(self, title, x, y, w, h, selector):
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        btn.setTitle_(title)
        btn.setBezelStyle_(NSBezelStyleRounded)
        btn.setFont_(NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium))
        btn.setTarget_(self)
        btn.setAction_(selector)
        return btn

    # --- state transitions ------------------------------------------------

    def _show_hero(self) -> None:
        self._segments = []
        self._final = False
        self._stopping = False
        self._active_tab = _TAB_TRANSCRIPT
        self._tabs.setSelectedSegment_(_TAB_TRANSCRIPT)
        self._current_path = None
        self._hero.setHidden_(False)
        self._transcript.setHidden_(True)
        self._logs.setHidden_(True)
        self._tabs.setHidden_(True)
        self._browse_btn.setHidden_(False)
        self._copy_btn.setHidden_(True)
        self._export_btn.setHidden_(True)
        self._new_btn.setHidden_(True)
        self._stop_btn.setHidden_(True)
        self._pill.setHidden_(True)
        self._spinner.stopAnimation_(None)
        self._status.setStringValue_("")
        self._title.setStringValue_("PersoWhisper")
        self._subtitle.setStringValue_("Local transcription workspace")
        self._clear_text()

    def _show_transcript(self, path: Path) -> None:
        self._current_path = path
        self._stopping = False
        self._active_tab = _TAB_TRANSCRIPT
        self._tabs.setSelectedSegment_(_TAB_TRANSCRIPT)
        self._hero.setHidden_(True)
        self._transcript.setHidden_(False)
        self._logs.setHidden_(True)
        self._tabs.setHidden_(False)
        self._browse_btn.setHidden_(True)
        self._copy_btn.setHidden_(False)
        self._export_btn.setHidden_(False)
        self._new_btn.setHidden_(True)
        self._stop_btn.setHidden_(False)
        self._stop_btn.setEnabled_(True)
        self._new_btn.setEnabled_(False)
        self._copy_btn.setEnabled_(False)
        self._export_btn.setEnabled_(False)
        self._title.setStringValue_(path.name)
        self._subtitle.setStringValue_(str(path.parent))
        self._set_pill("LIVE", (0.30, 0.62, 1.0))
        self._spinner.startAnimation_(None)
        self._status.setStringValue_("Loading model…")
        self._clear_text()
        self._update_copy_export_enabled()

    def _set_pill(self, text: str, rgb) -> None:
        r, g, b = rgb
        self._pill.setHidden_(False)
        self._pill.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 0.20).CGColor()
        )
        self._pill_label.setStringValue_(text)
        self._pill_label.setTextColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)
        )

    def _clear_text(self) -> None:
        ts = self._text_view.textStorage()
        ts.beginEditing()
        ts.setAttributedString_(NSAttributedString.alloc().initWithString_(""))
        ts.endEditing()

    def _scroll_to_end(self) -> None:
        length = self._text_view.textStorage().length()
        self._text_view.scrollRangeToVisible_(NSMakeRange(length, 0))

    def _log_text(self) -> str:
        return self._log_text_view.string()

    def _scroll_log_to_end(self) -> None:
        length = self._log_text_view.textStorage().length()
        self._log_text_view.scrollRangeToVisible_(NSMakeRange(length, 0))

    def _append_log_text(self, text: str) -> None:
        if not text:
            return
        ts = self._log_text_view.textStorage()
        ts.beginEditing()
        ts.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                text,
                self._log_attrs,
            )
        )
        excess = ts.length() - MAX_LOG_CHARS
        if excess > 0:
            ts.deleteCharactersInRange_(NSMakeRange(0, excess))
        ts.endEditing()
        if self._active_tab == _TAB_LOGS:
            self._scroll_log_to_end()
            self._update_copy_export_enabled()

    def _attach_logs(self) -> None:
        self._append_log_text(log_snapshot())
        add_log_listener(lambda text: _run_on_main(self._append_log_text, text))

    def _set_active_tab(self, tab: int) -> None:
        self._active_tab = _TAB_LOGS if tab == _TAB_LOGS else _TAB_TRANSCRIPT
        self._tabs.setSelectedSegment_(self._active_tab)
        self._hero.setHidden_(True)
        self._transcript.setHidden_(self._active_tab != _TAB_TRANSCRIPT)
        self._logs.setHidden_(self._active_tab != _TAB_LOGS)
        if self._active_tab == _TAB_LOGS:
            self._scroll_log_to_end()
        else:
            self._scroll_to_end()
        self._update_copy_export_enabled()

    def _update_copy_export_enabled(self) -> None:
        if self._active_tab == _TAB_LOGS:
            enabled = bool(self._log_text())
        else:
            enabled = bool(self._segments)
        self._copy_btn.setEnabled_(enabled)
        self._export_btn.setEnabled_(enabled)

    # --- public API (main thread only) ------------------------------------

    def show(self) -> None:
        NSApp.activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)

    def prepare_for_path(self, path: Path) -> None:
        self._segments = []
        self._final = False
        self._show_transcript(path)

    def append_partial(self, seg: Segment) -> None:
        if self._final:
            return
        self._segments.append(seg)
        count = len(self._segments)
        ts = self._text_view.textStorage()
        ts.beginEditing()
        ts.appendAttributedString_(attributed_segment(seg))
        ts.endEditing()
        self._scroll_to_end()
        if not self._stopping:
            suffix = "segment" if count == 1 else "segments"
            self._status.setStringValue_(f"Transcribing… {count} {suffix}")
        if count == 1:
            self._update_copy_export_enabled()

    def commit_final(self, segments: list[Segment]) -> None:
        self._final = True
        self._stopping = False
        self._segments = list(segments)
        ts = self._text_view.textStorage()
        ts.beginEditing()
        ts.setAttributedString_(NSAttributedString.alloc().initWithString_(""))
        for seg in self._segments:
            ts.appendAttributedString_(attributed_segment(seg))
        ts.endEditing()
        self._scroll_to_end()
        self._set_pill("DONE", (0.30, 0.70, 0.45))
        self._spinner.stopAnimation_(None)
        self._stop_btn.setHidden_(True)
        self._new_btn.setHidden_(False)
        self._status.setStringValue_(
            f"{len(self._segments)} segments · ready to copy or export"
        )
        self._update_copy_export_enabled()
        self._new_btn.setEnabled_(True)

    def mark_failed(self, message: str) -> None:
        self._final = True
        self._stopping = False
        self._spinner.stopAnimation_(None)
        self._set_pill("FAILED", (0.90, 0.40, 0.40))
        self._stop_btn.setHidden_(True)
        self._new_btn.setHidden_(False)
        self._status.setStringValue_(message[:200])
        self._new_btn.setEnabled_(True)
        self._update_copy_export_enabled()

    def mark_cancelling(self) -> None:
        if self._final:
            return
        self._stopping = True
        self._stop_btn.setEnabled_(False)
        self._set_pill("STOP", (0.95, 0.60, 0.25))
        self._status.setStringValue_("Stopping transcription…")

    def mark_cancelled(self) -> None:
        self._final = True
        self._stopping = False
        self._spinner.stopAnimation_(None)
        self._set_pill("STOPPED", (0.95, 0.60, 0.25))
        self._stop_btn.setHidden_(True)
        self._new_btn.setHidden_(False)
        if self._segments:
            count = len(self._segments)
            suffix = "segment" if count == 1 else "segments"
            self._status.setStringValue_(
                f"Stopped with {count} partial {suffix}"
            )
        else:
            self._status.setStringValue_("Stopped before any speech was transcribed")
        self._update_copy_export_enabled()
        self._new_btn.setEnabled_(True)

    def set_status(self, text: str) -> None:
        if self._stopping and text != "Stopping…":
            return
        self._status.setStringValue_(text)

    def update_busy(self, busy: bool) -> None:
        # Kept for app.py compatibility; no-op now since the same window
        # handles everything visually.
        pass

    # --- handlers ----------------------------------------------------------

    def _handle_drop(self, path: Path) -> None:
        if self._file_job.is_busy():
            self._status.setStringValue_("Already transcribing — please wait.")
            return
        self._file_job.start_with_path(path)

    def _onBrowse_(self, _sender):
        if self._file_job.is_busy():
            return
        self._file_job.start()

    def _onCopy_(self, _sender):
        if self._active_tab == _TAB_LOGS:
            logs = self._log_text()
            if not logs:
                return
            copy_to_clipboard(logs)
            self._status.setStringValue_("Copied logs to clipboard")
            return
        if not self._segments:
            return
        copy_to_clipboard(render_transcript_text(self._segments))
        self._status.setStringValue_("Copied to clipboard")

    def _onExport_(self, _sender):
        exporting_logs = self._active_tab == _TAB_LOGS
        export_text = (
            self._log_text()
            if exporting_logs
            else render_transcript_text(self._segments)
        )
        if not export_text:
            return
        panel = NSSavePanel.savePanel()
        panel.setTitle_("Export logs" if exporting_logs else "Export transcript")
        if exporting_logs:
            default_name = "persowhisper.log"
        else:
            stem = self._current_path.stem if self._current_path else "transcript"
            default_name = stem + ".txt"
        panel.setNameFieldStringValue_(default_name)
        if self._current_path is not None:
            try:
                panel.setDirectoryURL_(
                    NSURL.fileURLWithPath_(str(self._current_path.parent))
                )
            except Exception:
                pass
        panel.setExtensionHidden_(False)
        panel.setCanCreateDirectories_(True)
        if panel.runModal() != 1:
            return
        url = panel.URL()
        if url is None:
            return
        try:
            Path(url.path()).write_text(export_text, encoding="utf-8")
            kind = "logs" if exporting_logs else "transcript"
            self._status.setStringValue_(
                f"Exported {kind} to {Path(url.path()).name}"
            )
        except Exception as exc:
            self._status.setStringValue_(f"Export failed: {exc}")

    def _onNewFile_(self, _sender):
        if self._file_job.is_busy():
            return
        self._show_hero()

    def _onStop_(self, _sender):
        if not self._file_job.is_busy():
            return
        self._file_job.cancel()

    def _onTabChanged_(self, sender):
        self._set_active_tab(sender.selectedSegment())

    # --- NSWindowDelegate --------------------------------------------------

    def windowShouldClose_(self, _sender):
        self._window.orderOut_(None)
        return False
