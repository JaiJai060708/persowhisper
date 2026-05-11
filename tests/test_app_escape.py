import unittest

from AppKit import (
    NSEventModifierFlagCommand,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
)
from Quartz import kCGEventFlagsChanged, kCGEventKeyDown

from src.app import ModifierTapRecognizer, PersoWhisperApp


class FakeEvent:
    def __init__(self, key_code, event_type=NSEventTypeKeyDown, modifier_flags=None):
        self._key_code = key_code
        self._event_type = event_type
        self._modifier_flags = modifier_flags

    def keyCode(self):
        return self._key_code

    def type(self):
        return self._event_type

    def modifierFlags(self):
        if self._modifier_flags is None:
            raise AttributeError("modifierFlags")
        return self._modifier_flags


class FakeController:
    def __init__(self, can_cancel=True):
        self.cancel_count = 0
        self.tap_count = 0
        self._can_cancel = can_cancel

    def cancel(self):
        self.cancel_count += 1

    def on_tap(self):
        self.tap_count += 1

    def can_cancel(self):
        return self._can_cancel


class AppEscapeMonitorTest(unittest.TestCase):
    def test_appkit_escape_keycode_cancels(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        event = FakeEvent(53)

        app._right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )
        returned = app._on_local_key_event(event)

        self.assertIs(returned, event)
        self.assertEqual(app._controller.cancel_count, 1)

    def test_appkit_escape_keycode_does_not_cancel_when_idle(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController(can_cancel=False)
        event = FakeEvent(53)

        app._right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )
        returned = app._on_local_key_event(event)

        self.assertIs(returned, event)
        self.assertEqual(app._controller.cancel_count, 0)

    def test_other_appkit_keycode_does_not_cancel(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        event = FakeEvent(36)

        app._right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )
        app._on_global_key_event(event)

        self.assertEqual(app._controller.cancel_count, 0)

    def test_global_right_cmd_tap_triggers_controller(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        app._right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )

        app._on_global_key_event(
            FakeEvent(
                54,
                NSEventTypeFlagsChanged,
                modifier_flags=NSEventModifierFlagCommand,
            )
        )
        app._on_global_key_event(
            FakeEvent(54, NSEventTypeFlagsChanged, modifier_flags=0)
        )

        self.assertEqual(app._controller.tap_count, 1)

    def test_escape_during_appkit_cmd_tap_blocks_tap(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        app._right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )

        app._on_global_key_event(
            FakeEvent(
                54,
                NSEventTypeFlagsChanged,
                modifier_flags=NSEventModifierFlagCommand,
            )
        )
        app._on_global_key_event(FakeEvent(53, NSEventTypeKeyDown))
        app._on_global_key_event(
            FakeEvent(54, NSEventTypeFlagsChanged, modifier_flags=0)
        )

        self.assertEqual(app._controller.cancel_count, 1)
        self.assertEqual(app._controller.tap_count, 0)

    def test_quartz_escape_keycode_cancels_when_unfocused(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        app._quartz_right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )

        app._handle_quartz_key_event(kCGEventKeyDown, 53, False)

        self.assertEqual(app._controller.cancel_count, 1)

    def test_quartz_escape_keycode_does_not_cancel_when_idle(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController(can_cancel=False)
        app._quartz_right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )

        app._handle_quartz_key_event(kCGEventKeyDown, 53, False)

        self.assertEqual(app._controller.cancel_count, 0)

    def test_quartz_right_cmd_tap_triggers_controller(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController()
        app._quartz_right_cmd_tap = ModifierTapRecognizer(
            key_code=54,
            on_tap=app._controller.on_tap,
        )

        app._handle_quartz_key_event(kCGEventFlagsChanged, 54, True)
        app._handle_quartz_key_event(kCGEventFlagsChanged, 54, False)

        self.assertEqual(app._controller.tap_count, 1)

    def test_escape_poll_cancels_when_active_and_freshly_pressed(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController(can_cancel=True)
        app._escape_was_down = False
        app._escape_key_is_down = lambda: True

        app._poll_escape_cancel()

        self.assertEqual(app._controller.cancel_count, 1)
        self.assertTrue(app._escape_was_down)

    def test_escape_poll_does_not_cancel_when_idle(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController(can_cancel=False)
        app._escape_was_down = False
        app._escape_key_is_down = lambda: True

        app._poll_escape_cancel()

        self.assertEqual(app._controller.cancel_count, 0)
        self.assertTrue(app._escape_was_down)

    def test_escape_poll_does_not_repeatedly_cancel_while_held(self):
        app = object.__new__(PersoWhisperApp)
        app._controller = FakeController(can_cancel=True)
        app._escape_was_down = True
        app._escape_key_is_down = lambda: True

        app._poll_escape_cancel()

        self.assertEqual(app._controller.cancel_count, 0)


class ModifierTapRecognizerTest(unittest.TestCase):
    def test_clean_modifier_tap_calls_on_tap(self):
        now = [10.0]
        calls = []
        recognizer = ModifierTapRecognizer(
            key_code=54,
            on_tap=lambda: calls.append("tap"),
            clock=lambda: now[0],
        )

        recognizer.flags_changed(54)
        now[0] += 0.1
        recognizer.flags_changed(54)

        self.assertEqual(calls, ["tap"])

    def test_other_key_during_modifier_tap_blocks_tap(self):
        calls = []
        recognizer = ModifierTapRecognizer(
            key_code=54,
            on_tap=lambda: calls.append("tap"),
        )

        recognizer.flags_changed(54)
        recognizer.key_down(48)
        recognizer.flags_changed(54)

        self.assertEqual(calls, [])

    def test_long_modifier_hold_blocks_tap(self):
        now = [10.0]
        calls = []
        recognizer = ModifierTapRecognizer(
            key_code=54,
            on_tap=lambda: calls.append("tap"),
            max_hold_ms=800,
            clock=lambda: now[0],
        )

        recognizer.flags_changed(54)
        now[0] += 0.9
        recognizer.flags_changed(54)

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
