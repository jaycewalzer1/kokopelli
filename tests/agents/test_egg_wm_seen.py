"""The egg scene's dry closed loop (tests/agents/test_egg_wm.py: fake sim, fake world model, scripted brain) with the
painted-frame check of kokopelli/wm/seen.py switched on and off. A fake detector stands in throughout: no real
detector, worker process or model is ever started here, and any path that would start one fails the test.

Two things are checked. As staged, Teo stands inside arm's reach, so the check is never consulted and every prompt is
the pinned one with the flag on or off. Moved out of reach but within talking distance, he is in the prompt only if the
detector finds a person in the painted frame, or if the flag is off.
"""
import functools
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kokopelli.agents import egg_wm, live, live_wm
from kokopelli.wm import llm_model
from kokopelli.wm import seen as seen_wm
from tests.agents import test_egg_wm as base

TEO_LINE = "- teo:"


class FakeDetector:
    """A fake detector: finds a person, finds nothing, or breaks, as told; counts how often it was asked."""

    def __init__(self, finds):
        self.finds, self.asked = finds, 0

    def detect(self, frame, labels):
        self.asked += 1
        if self.finds == "breaks":
            raise RuntimeError("the fake detector was told to break")
        return [seen_wm.Detection(labels[0], (20.0, 4.0, 40.0, 34.0), 0.9)] if self.finds else []


def refuse(*args, **kwargs):
    raise AssertionError("a real detector was about to be started in a dry test")


class NoRealDetector(unittest.TestCase):
    """Starts the dry loop's stand-ins plus a guard on the worker, for one test class."""

    @classmethod
    def stand_ins(cls, tmp):
        return [mock.patch.object(live, "SimWorldPhysics", base.FakeSim), mock.patch.object(live_wm, "WorldStream", base.FakeStream),
                mock.patch.object(live, "ROOT", tmp), mock.patch.object(llm_model, "ask", base.scripted_ask),
                mock.patch.object(llm_model, "load_llm", lambda: None), mock.patch.object(llm_model, "unload", lambda: None),
                mock.patch.object(llm_model, "LLM_MODEL_WEIGHTS", Path("models/fake")),
                mock.patch.object(seen_wm.WorkerDetector, "start", refuse)]


class SeenOnTest(base.EggLoopTest):
    """Every test of the dry loop again, the golden prompts included, with the flag on (the default) and the worker
    guarded: as staged the detector must not even be asked."""
    SEEN = True

    @classmethod
    def setUpClass(cls):
        cls.detector = FakeDetector(finds=False)   # if it were asked, Teo would vanish and the pinned prompts would fail
        cls.extra = [mock.patch.object(seen_wm.WorkerDetector, "start", refuse),
                     mock.patch.object(seen_wm, "default_detector", lambda: cls.detector),
                     mock.patch.object(base, "SimpleArgs", functools.partial(base.SimpleArgs, seen=cls.SEEN))]
        for patch in cls.extra:
            patch.start()
        try:
            super().setUpClass()
        except BaseException:
            for patch in cls.extra:
                patch.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        for patch in cls.extra:
            patch.stop()

    def test_the_detector_was_never_asked(self):
        self.assertEqual(self.detector.asked, 0)

    def test_the_sidecar_says_whether_the_check_was_on(self):
        self.assertEqual(self.result("full")["seen"], {"on": self.SEEN, "asked": 0, "dropped": 0, "failed": 0, "detector": None})


class SeenOffTest(SeenOnTest):
    SEEN = False


class TeoOutOfReachTest(NoRealDetector):
    """Teo 5 m away: past arm's reach (3 m), inside talking distance (10 m)."""

    def first_prompt(self, finds, seen=True):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        detector = FakeDetector(finds)
        patches = [*self.stand_ins(tmp), mock.patch.object(egg_wm, "TEO_OFFSET_M", 5.0),
                   mock.patch.object(seen_wm, "default_detector", lambda: detector)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        base.PROMPTS.clear()
        life = egg_wm.EggLife(base.SimpleArgs(level="half", minutes=0.25, seen=seen))
        life.run()
        return base.PROMPTS[0], detector, life

    def test_painted_he_is_in_the_prompt(self):
        prompt, detector, life = self.first_prompt(finds=True)
        self.assertIn(TEO_LINE, prompt)
        self.assertGreater(detector.asked, 0)
        self.assertEqual(life.seen_dropped, 0)

    def test_not_painted_he_is_not(self):
        prompt, detector, life = self.first_prompt(finds=False)
        self.assertNotIn(TEO_LINE, prompt)
        self.assertIn("Who is right next to you (close enough to talk):\n- nobody", prompt)
        self.assertGreater(life.seen_dropped, 0)

    def test_a_detector_that_breaks_leaves_the_sims_word_standing_and_is_recorded(self):
        prompt, detector, life = self.first_prompt(finds="breaks")
        self.assertIn(TEO_LINE, prompt)
        self.assertGreater(life.seen_failed, 0)
        self.assertEqual((life.seen_asked, life.seen_dropped), (0, 0))

    def test_with_the_check_off_the_sim_alone_decides(self):
        prompt, detector, _ = self.first_prompt(finds=False, seen=False)
        self.assertIn(TEO_LINE, prompt)
        self.assertEqual(detector.asked, 0)


if __name__ == "__main__":
    unittest.main()
