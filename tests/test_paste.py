import subprocess
import unittest
from unittest.mock import patch

from src.paste import PasteTarget, paste


class PasteTest(unittest.TestCase):
    def test_paste_activates_target_before_cmd_v(self):
        events = []
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")

        def fake_check_output(args):
            events.append(args[0])
            return b"previous"

        def fake_run(args, **_kwargs):
            events.append(args[0])
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", side_effect=fake_check_output), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._activate_target", side_effect=lambda _target: events.append("activate")), patch(
            "src.paste._quartz_paste_allowed",
            return_value=True,
        ), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or True,
        ), patch(
            "src.paste.time.sleep"
        ):
            self.assertTrue(paste("hello", target=target))

        self.assertEqual(
            events,
            ["pbpaste", "pbcopy", "activate", "quartz", "pbcopy"],
        )

    def test_paste_uses_quartz_before_osascript(self):
        events = []
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")

        def fake_run(args, **_kwargs):
            events.append(args[0])
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", return_value=b"previous"), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._activate_target", return_value=True), patch(
            "src.paste._quartz_paste_allowed",
            return_value=True,
        ), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or True,
        ), patch("src.paste.time.sleep"):
            self.assertTrue(paste("hello", target=target))

        self.assertEqual(events, ["pbcopy", "quartz", "pbcopy"])

    def test_paste_falls_back_to_osascript_if_quartz_unavailable(self):
        events = []
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")

        def fake_run(args, **_kwargs):
            events.append(args[0])
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", return_value=b"previous"), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._activate_target", return_value=True), patch(
            "src.paste._quartz_paste_allowed",
            return_value=False,
        ), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or True,
        ), patch("src.paste.time.sleep"):
            self.assertTrue(paste("hello", target=target))

        self.assertEqual(events, ["pbcopy", "osascript", "pbcopy"])

    def test_paste_falls_back_to_osascript_if_quartz_fails(self):
        events = []

        def fake_run(args, **_kwargs):
            events.append(args[0])
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", return_value=b"previous"), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._quartz_paste_allowed", return_value=True), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or False,
        ), patch("src.paste.time.sleep"):
            self.assertTrue(paste("hello"))

        self.assertEqual(events, ["pbcopy", "quartz", "osascript", "pbcopy"])

    def test_paste_can_try_quartz_after_osascript_fails(self):
        events = []

        def fake_run(args, **_kwargs):
            events.append(args[0])
            if args[0] == "osascript":
                return subprocess.CompletedProcess(args=args, returncode=1, stderr="nope")
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", return_value=b"previous"), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._quartz_paste_allowed", side_effect=[False, True]), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or True,
        ), patch("src.paste.time.sleep"):
            self.assertTrue(paste("hello"))

        self.assertEqual(events, ["pbcopy", "osascript", "quartz", "pbcopy"])

    def test_paste_does_not_claim_success_when_accessibility_blocks_quartz(self):
        events = []
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")

        def fake_run(args, **_kwargs):
            events.append(args[0])
            if args[0] == "osascript":
                return subprocess.CompletedProcess(args=args, returncode=1, stderr="nope")
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("src.paste.subprocess.check_output", return_value=b"previous"), patch(
            "src.paste.subprocess.run",
            side_effect=fake_run,
        ), patch("src.paste._activate_target", return_value=True), patch(
            "src.paste._quartz_paste_allowed",
            return_value=False,
        ), patch(
            "src.paste._post_cmd_v_quartz",
            side_effect=lambda: events.append("quartz") or True,
        ), patch("src.paste.time.sleep"):
            self.assertFalse(paste("hello", target=target))

        self.assertEqual(events, ["pbcopy", "osascript", "pbcopy"])


if __name__ == "__main__":
    unittest.main()
