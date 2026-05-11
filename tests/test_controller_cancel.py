import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from src.controller import Controller
from src.paste import PasteTarget
from src.state import State


class FakeRecorder:
    def __init__(self):
        self.cancel_count = 0
        self.start_count = 0

    def start(self):
        self.start_count += 1

    def cancel(self):
        self.cancel_count += 1

    def latest_level(self):
        return 0.0


class ControllerCancelTest(unittest.TestCase):
    def test_cancel_recording_is_immediate_and_discards_recorder(self):
        controller = Controller()
        recorder = FakeRecorder()
        controller._recorder = recorder
        controller._state = State.RECORDING

        with patch("src.controller.play"):
            controller.cancel()

        self.assertIs(controller.state, State.IDLE)
        self.assertIsNone(controller._cancel_event)
        self.assertEqual(recorder.cancel_count, 1)

    def test_duplicate_taps_are_suppressed(self):
        controller = Controller()
        recorder = FakeRecorder()
        controller._recorder = recorder

        with patch("src.controller.play"), patch(
            "src.controller.capture_paste_target",
            return_value=None,
        ), patch(
            "src.controller.time.monotonic",
            side_effect=[100.0, 100.05],
        ):
            controller.on_tap()
            controller.on_tap()

        self.assertIs(controller.state, State.RECORDING)
        self.assertEqual(recorder.start_count, 1)

    def test_cancel_transcribing_marks_idle_and_sets_event_immediately(self):
        controller = Controller()
        recorder = FakeRecorder()
        cancel_event = threading.Event()
        controller._recorder = recorder
        controller._state = State.TRANSCRIBING
        controller._cancel_event = cancel_event

        with patch("src.controller.play"):
            controller.cancel()

        self.assertTrue(cancel_event.is_set())
        self.assertIs(controller.state, State.IDLE)
        self.assertIsNone(controller._cancel_event)
        self.assertEqual(recorder.cancel_count, 1)

    def test_can_cancel_only_when_dictation_active(self):
        controller = Controller()
        self.assertFalse(controller.can_cancel())

        controller._state = State.RECORDING
        self.assertTrue(controller.can_cancel())

        controller._state = State.TRANSCRIBING
        self.assertTrue(controller.can_cancel())

        controller._state = State.IDLE
        self.assertFalse(controller.can_cancel())

    def test_start_recording_captures_paste_target(self):
        controller = Controller()
        recorder = FakeRecorder()
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")
        controller._recorder = recorder

        with patch("src.controller.play"), patch(
            "src.controller.capture_paste_target",
            return_value=target,
        ):
            controller._start_recording()

        self.assertIs(controller.state, State.RECORDING)
        self.assertEqual(controller._paste_target, target)

    def test_transcribe_worker_passes_paste_target_to_paste(self):
        class StopRecorder(FakeRecorder):
            def __init__(self, path):
                super().__init__()
                self.path = path

            def stop(self):
                return self.path, 1.0

        path = Path("/tmp/persowhisper_test_controller.wav")
        path.write_bytes(b"fake wav")
        target = PasteTarget(pid=123, bundle_id="com.example.Target", name="Target")
        cancel_event = threading.Event()
        controller = Controller()
        controller._recorder = StopRecorder(path)
        controller._cancel_event = cancel_event

        with patch("src.controller.transcribe", return_value="hello"), patch(
            "src.controller.paste",
            return_value=True,
        ) as paste_mock, patch("src.controller.play"):
            controller._transcribe_worker(cancel_event, target)

        paste_mock.assert_called_once()
        self.assertEqual(paste_mock.call_args.kwargs["target"], target)


if __name__ == "__main__":
    unittest.main()
