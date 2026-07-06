"""Regression tests for the engine's model-load wait.

These pin down the cancel-path deadlock: a concurrent ``release()`` (triggered
by Escape + starting a new dictation) used to clear ``_ready`` out from under a
worker parked in ``_ensure_model()``, leaving it blocked forever — the overlay
"stuck on Loading…". ``_ensure_model`` now loops over a bounded wait and re-arms
the load, so it must recover instead of hanging.

The whisperx model is never actually loaded here; ``_Engine._load`` is replaced
with a fake that drives the same shared state (``_model``/``_loading``/
``_ready``/``_generation``/``_load_error``) the real loader touches.
"""

import threading
import unittest

from src.engine import _Engine


def _run_with_timeout(fn, timeout=5.0):
    """Run ``fn`` on a daemon thread; fail loudly if it does not return.

    A regression here manifests as a deadlock, so a timeout is the assertion:
    against the old unconditional ``_ready.wait()`` the thread never returns.
    """
    box = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as exc:  # propagate to the test thread
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(
            f"{getattr(fn, '__name__', fn)!r} did not return within {timeout}s "
            f"(deadlock?)"
        )
    if "error" in box:
        raise box["error"]
    return box.get("result")


class EnsureModelTest(unittest.TestCase):
    def test_returns_model_on_normal_load(self):
        eng = _Engine()
        sentinel = object()

        def fake_load(gen):
            with eng._lock:
                if gen == eng._generation:
                    eng._model = sentinel
                    eng._loading = False
                    eng._ready.set()

        eng._load = fake_load
        self.assertIs(_run_with_timeout(eng._ensure_model), sentinel)

    def test_recovers_when_load_invalidated_midflight(self):
        """The cancel-path race: the first load is invalidated by a concurrent
        release() (generation bumped, _ready cleared, no live loader). The old
        code parked here forever; the fix must re-arm and return the model."""
        eng = _Engine()
        sentinel = object()
        loads = []

        def fake_load(gen):
            loads.append(gen)
            if len(loads) == 1:
                # Simulate release() landing during this load — exactly what
                # _Engine.release() does: bump gen, drop the model/loader,
                # clear _ready. This loader is now stale and sets nothing.
                with eng._lock:
                    eng._generation += 1
                    eng._model = None
                    eng._loading = False
                    eng._ready.clear()
                return
            with eng._lock:
                if gen == eng._generation:
                    eng._model = sentinel
                    eng._loading = False
                    eng._ready.set()

        eng._load = fake_load
        self.assertIs(_run_with_timeout(eng._ensure_model), sentinel)
        self.assertGreaterEqual(len(loads), 2)  # the load was re-armed

    def test_raises_on_load_failure_without_infinite_retry(self):
        """A genuine load failure must surface as an error, not spin forever
        re-arming the load."""
        eng = _Engine()
        loads = []

        def fake_load(gen):
            loads.append(gen)
            with eng._lock:
                if gen == eng._generation:
                    eng._load_error = RuntimeError("boom")
                    eng._loading = False
                    eng._ready.set()

        eng._load = fake_load
        with self.assertRaises(RuntimeError):
            _run_with_timeout(eng._ensure_model)
        self.assertEqual(len(loads), 1)  # did not retry past a real failure


if __name__ == "__main__":
    unittest.main()
