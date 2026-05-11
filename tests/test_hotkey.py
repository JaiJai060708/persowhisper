import unittest

from pynput import keyboard

from src.hotkey import HotkeyListener


class HotkeyListenerTest(unittest.TestCase):
    def test_escape_keycode_char_cancels_on_press(self):
        calls = []
        listener = HotkeyListener(
            on_tap=lambda: calls.append("tap"),
            on_cancel=lambda: calls.append("cancel"),
        )

        listener._on_press(keyboard.KeyCode.from_char("\x1b"))

        self.assertEqual(calls, ["cancel"])

    def test_escape_keycode_char_does_not_cancel_when_inactive(self):
        calls = []
        listener = HotkeyListener(
            on_tap=lambda: calls.append("tap"),
            on_cancel=lambda: calls.append("cancel"),
            should_cancel=lambda: False,
        )

        listener._on_press(keyboard.KeyCode.from_char("\x1b"))

        self.assertEqual(calls, [])

    def test_escape_keycode_vk_cancels_on_press(self):
        calls = []
        listener = HotkeyListener(
            on_tap=lambda: calls.append("tap"),
            on_cancel=lambda: calls.append("cancel"),
        )

        listener._on_press(keyboard.KeyCode.from_vk(53))

        self.assertEqual(calls, ["cancel"])

    def test_held_escape_only_cancels_once_until_released(self):
        calls = []
        listener = HotkeyListener(
            on_tap=lambda: calls.append("tap"),
            on_cancel=lambda: calls.append("cancel"),
        )

        listener._on_press(keyboard.Key.esc)
        listener._on_press(keyboard.Key.esc)
        listener._on_release(keyboard.Key.esc)
        listener._on_press(keyboard.Key.esc)

        self.assertEqual(calls, ["cancel", "cancel"])

    def test_escape_during_cmd_press_does_not_emit_cmd_tap(self):
        calls = []
        listener = HotkeyListener(
            on_tap=lambda: calls.append("tap"),
            on_cancel=lambda: calls.append("cancel"),
        )

        listener._on_press(keyboard.Key.cmd_r)
        listener._on_press(keyboard.KeyCode.from_char("\x1b"))
        listener._on_release(keyboard.KeyCode.from_char("\x1b"))
        listener._on_release(keyboard.Key.cmd_r)

        self.assertEqual(calls, ["cancel"])


if __name__ == "__main__":
    unittest.main()
