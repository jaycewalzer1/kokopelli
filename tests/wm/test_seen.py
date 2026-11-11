"""kokopelli/wm/seen.py: the filter that keeps a sim candidate only when a detector finds it in the painted frame.

Every test but the last uses a fake detector (a list of boxes written by hand), so no model, torch or worker process is
involved. The last one loads a real detector on a real painted frame; it is marked slow and only runs from a GPU-queue
job with RUN_LONG_TESTS=1.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from kokopelli import settings
from kokopelli.wm import seen as seen_mod
from kokopelli.wm.seen import Candidate, Detection, Seen, confirm, iou, seen

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / "out" / "bodies" / "demo" / "runs" / "wm" / "film" / "mara.mp4"   # painted by Cosmos3-Nano-Sim-Transfer
FRAME = 832   # 52 s in, the other agent standing in front: the frame seen_eval's detectors were surest of (mara_0832)


class FakeDetector:
    """A fake detector: answers with the boxes it was given and remembers what it was asked."""

    def __init__(self, detections):
        self.detections, self.asked = list(detections), []

    def detect(self, frame, labels):
        self.asked.append((frame, list(labels)))
        return list(self.detections)


def refuse(*args, **kwargs):
    raise AssertionError("a real detector was about to be loaded in a test")


class FilterTest(unittest.TestCase):
    def setUp(self):
        # Any path that would reach a real model fails the test instead of loading one.
        patches = [mock.patch.object(seen_mod, "default_detector", refuse), mock.patch.object(seen_mod.subprocess, "Popen", refuse)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_candidate_is_kept_only_if_its_label_was_detected(self):
        fake = FakeDetector([Detection("a person", (10, 20, 50, 120), 0.8)])
        kept = seen("frame.png", [Candidate("teo", "a person"), Candidate("ball", "a ball")], detector=fake, threshold=0.3)
        self.assertEqual(kept, [Seen("teo", "a person", (10, 20, 50, 120), 0.8)])
        self.assertEqual(fake.asked, [("frame.png", ["a ball", "a person"])])

    def test_it_never_invents(self):
        # The detector sees a dog and a second person nobody asked about: neither becomes something the agent knows.
        fake = FakeDetector([Detection("a dog", (0, 0, 30, 30), 0.99), Detection("a person", (10, 20, 50, 120), 0.9),
                             Detection("a person", (200, 20, 240, 120), 0.9)])
        kept = seen("frame.png", [Candidate("teo", "a person")], detector=fake, threshold=0.3)
        self.assertEqual([s.id for s in kept], ["teo"])

    def test_a_weak_detection_does_not_confirm(self):
        fake = FakeDetector([Detection("a person", (10, 20, 50, 120), 0.29)])
        self.assertEqual(seen("frame.png", [Candidate("teo", "a person")], detector=fake, threshold=0.3), [])
        self.assertEqual(len(seen("frame.png", [Candidate("teo", "a person")], detector=fake, threshold=0.29)), 1)

    def test_no_candidates_means_no_detector_call(self):
        fake = FakeDetector([Detection("a person", (0, 0, 1, 1), 1.0)])
        self.assertEqual(seen("frame.png", [], detector=fake), [])
        self.assertEqual(fake.asked, [])
        self.assertEqual(seen("frame.png", []), [])   # and with no detector given, none is loaded (refuse would raise)

    def test_one_detection_confirms_one_candidate(self):
        # Two people in the sim, one painted: only one is confirmed, and without boxes it is the first one given.
        fake = FakeDetector([Detection("a person", (10, 20, 50, 120), 0.8)])
        kept = seen("frame.png", [Candidate("teo", "a person"), Candidate("ana", "a person")], detector=fake, threshold=0.3)
        self.assertEqual([s.id for s in kept], ["teo"])

    def test_a_box_decides_who_is_who(self):
        left, right = Detection("a person", (10, 20, 50, 120), 0.6), Detection("a person", (300, 20, 340, 120), 0.9)
        people = [Candidate("teo", "a person", box=(305, 25, 345, 125)), Candidate("ana", "a person", box=(12, 22, 52, 122))]
        kept = confirm(people, [left, right], threshold=0.3, min_iou=0.3)
        self.assertEqual({s.id: s.box for s in kept}, {"teo": right.box, "ana": left.box})

    def test_a_person_painted_somewhere_else_does_not_confirm_a_boxed_candidate(self):
        # Cosmos paints passers-by of its own. One on the left must not confirm Teo, whom the sim puts on the right.
        elsewhere = Detection("a person", (10, 20, 50, 120), 0.95)
        self.assertEqual(confirm([Candidate("teo", "a person", box=(300, 20, 340, 120))], [elsewhere], 0.3, 0.3), [])

    def test_boxed_candidates_choose_before_unboxed_ones(self):
        only = Detection("a person", (300, 20, 340, 120), 0.9)
        people = [Candidate("ana", "a person"), Candidate("teo", "a person", box=(300, 20, 340, 120))]
        self.assertEqual([s.id for s in confirm(people, [only], 0.3, 0.3)], ["teo"])

    def test_results_keep_the_candidates_order(self):
        found = [Detection("a ball", (0, 0, 9, 9), 0.9), Detection("a person", (10, 20, 50, 120), 0.5)]
        people = [Candidate("teo", "a person"), Candidate("ball", "a ball")]
        self.assertEqual([s.id for s in confirm(people, found, 0.3, 0.3)], ["teo", "ball"])

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            confirm([Candidate("teo", "a person"), Candidate("teo", "a man")], [], 0.3, 0.3)

    def test_thresholds_default_to_the_settings(self):
        fake = FakeDetector([Detection("a person", (10, 20, 50, 120), 0.5)])
        with mock.patch.dict(settings.SEEN, {"threshold": 0.6}):
            self.assertEqual(seen("frame.png", [Candidate("teo", "a person")], detector=fake), [])
        with mock.patch.dict(settings.SEEN, {"threshold": 0.4}):
            self.assertEqual(len(seen("frame.png", [Candidate("teo", "a person")], detector=fake)), 1)

    def test_iou(self):
        self.assertEqual(iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        self.assertEqual(iou((0, 0, 10, 10), (10, 0, 20, 10)), 0.0)
        self.assertAlmostEqual(iou((0, 0, 10, 10), (5, 0, 15, 10)), 1 / 3)

    def test_a_detectors_own_wording_maps_back_to_one_asked_label_or_none(self):
        self.assertEqual(seen_mod.match_label("A Person", ["a person", "a ball"]), "a person")
        self.assertEqual(seen_mod.match_label("person", ["a person", "a ball"]), "a person")
        self.assertIsNone(seen_mod.match_label("a person a ball", ["a person", "a ball"]))   # two labels merged: neither
        self.assertIsNone(seen_mod.match_label("", ["a person"]))
        self.assertEqual(seen_mod.od_label("woman", ["a person", "a ball"]), "a person")
        self.assertIsNone(seen_mod.od_label("tree", ["a person", "a ball"]))


class LazyTest(unittest.TestCase):
    def test_importing_and_choosing_a_backend_loads_nothing(self):
        # A fresh interpreter: import the module, build the default detector, and check no model library came with it
        # and no worker process was started.
        code = ("import sys, json; from kokopelli.wm import seen; d = seen.default_detector(); "
                "print(json.dumps({'heavy': sorted(m for m in ('torch', 'transformers', 'mlx', 'PIL') if m in sys.modules), "
                "'started': d.proc is not None, 'backend': d.backend}))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), {"heavy": [], "started": False, "backend": settings.SEEN["backend"]})

    def test_every_backend_names_its_weights_and_licence(self):
        self.assertIn(settings.SEEN["backend"], seen_mod.BACKENDS)
        for name in seen_mod.BACKENDS:
            about = seen_mod.about(name)
            self.assertRegex(about["revision"], r"^[0-9a-f]{40}$")
            self.assertIn(about["licence"], ("MIT", "Apache-2.0"))
            self.assertEqual(about["weights"], f"{about['repo']}@{about['revision']}")

    def test_an_unknown_backend_is_refused_before_anything_starts(self):
        with self.assertRaises(ValueError):
            seen_mod.WorkerDetector("yolo")


@pytest.mark.slow(reason="loads a real detector (the SEEN backend) in its worker; run it from a GPU-queue job")
class RealDetectorTest(unittest.TestCase):
    def test_the_person_cosmos_painted_is_confirmed_and_a_made_up_thing_is_dropped(self):
        if not FILM.exists():
            self.skipTest(f"no painted film at {FILM}")
        import cv2
        film = cv2.VideoCapture(str(FILM))
        for _ in range(FRAME + 1):   # read up to the frame: seeking in H.264 isn't exact
            ok, frame = film.read()
            self.assertTrue(ok, "the film is shorter than expected")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "painted.png")
            cv2.imwrite(path, frame)
            try:
                kept = seen(path, [Candidate("iris", "a person"), Candidate("zebra", "a zebra")])
            finally:
                seen_mod.release()
        self.assertEqual([s.id for s in kept], ["iris"])
        x0, y0, x1, y1 = kept[0].box
        self.assertTrue(0 <= x0 < x1 <= 448 and 0 <= y0 < y1 <= 256)


if __name__ == "__main__":
    unittest.main()
