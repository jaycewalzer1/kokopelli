"""experiments/sensation/seen_eval.py: the labels read from a seg control frame and the scoring, on hand-made inputs.
No video, no detector, no model."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from experiments.sensation import seen_eval as ev

CYAN, OLIVE = ev.HUMAN_RGB[0], ev.HUMAN_RGB[1]


def seg_frame(*patches):
    """A 448x256 seg frame of one background colour with (colour, x0, y0, x1, y1) patches."""
    frame = np.full((256, 448, 3), (66, 105, 98), np.uint8)
    for colour, x0, y0, x1, y1 in patches:
        frame[y0:y1, x0:x1] = colour
    return frame


def row(name, truth, boxes=()):
    return {"frame": name, "truth": truth, "boxes": [list(b) for b in boxes], "part": "clean"}


def found(*scored_boxes):
    return {"detections": [{"label": ev.LABEL, "box": list(box), "score": score} for score, box in scored_boxes], "seconds": 0.1}


class LabelTest(unittest.TestCase):
    def test_a_body_sized_patch_of_a_human_colour_is_a_person_with_its_box(self):
        got = ev.people_in(seg_frame((CYAN, 200, 100, 220, 160)))
        self.assertEqual(got["boxes"], [[200, 100, 220, 160]])
        self.assertTrue(got["sized"] and got["trace"])

    def test_an_empty_frame_and_an_olive_speck_leave_no_trace(self):
        self.assertEqual(ev.people_in(seg_frame()), {"boxes": [], "sized": False, "trace": False})
        self.assertEqual(ev.people_in(seg_frame((OLIVE, 10, 10, 12, 15))), {"boxes": [], "sized": False, "trace": False})

    def test_a_few_pixels_of_a_far_walker_are_a_trace_not_a_person(self):
        got = ev.people_in(seg_frame((CYAN, 200, 100, 204, 104)))
        self.assertEqual((got["boxes"], got["sized"], got["trace"]), ([], False, True))

    def test_nobody_needs_a_clean_frame_and_no_person_sized_region_nearby_in_time(self):
        empty = {"boxes": [], "sized": False, "trace": False}
        walker = {"boxes": [], "sized": True, "trace": True}
        body = {"boxes": [[0, 0, 20, 60]], "sized": True, "trace": True}
        near = int(ev.NEAR_S * ev.FPS)
        got = ev.truths({0: empty, 200: empty, 200 + near: walker, 400: body})
        self.assertEqual(got, {0: "nobody", 200: "unclear", 200 + near: "unclear", 400: "person"})


class ScoreTest(unittest.TestCase):
    def setUp(self):
        box = (200, 100, 220, 160)
        self.rows = [row("a", "person", [box]), row("b", "person", [box]), row("c", "nobody"), row("d", "nobody"), row("e", "unclear")]
        self.found = {"a": found((0.8, box)), "b": found((0.3, (10, 10, 30, 70))), "c": found((0.5, box)), "d": found(), "e": found((0.9, box))}

    def test_counts_at_a_threshold(self):
        got = ev.score(self.rows, self.found, 0.25)
        self.assertEqual((got["tp"], got["fp"], got["fn"], got["tn"]), (2, 1, 0, 1))   # the unclear frame is not scored
        self.assertEqual((got["precision"], got["recall"]), (0.6667, 1.0))
        got = ev.score(self.rows, self.found, 0.6)
        self.assertEqual((got["tp"], got["fp"], got["fn"], got["tn"]), (1, 0, 1, 2))

    def test_with_the_sims_box_a_person_painted_elsewhere_does_not_count(self):
        got = ev.score(self.rows, self.found, 0.25, hinted=True)
        self.assertEqual((got["tp"], got["fn"], got["fp"], got["tn"]), (1, 1, 0, 0))

    def test_the_bar_takes_the_most_recall_among_thresholds_that_are_precise_enough(self):
        best = ev.best_at_bar(self.rows, self.found)
        self.assertEqual((best["threshold"], best["precision"], best["recall"]), (0.8, 1.0, 0.5))

    def test_no_threshold_precise_enough_means_no_pick(self):
        noisy = {name: found((0.99, (0, 0, 9, 9))) for name in "abcde"}
        self.assertIsNone(ev.best_at_bar(self.rows, noisy))

    def test_detectors_only_see_frames_that_get_scored_headline_first(self):
        late = [{"frame": f"late{k}", "truth": "person", "boxes": [], "part": "late"} for k in range(9)]
        got = [r["frame"] for r in ev.to_detect([late[0], *self.rows, *late[1:]])]
        self.assertEqual(got, ["a", "b", "c", "d", "late0", "late4", "late8"])   # "e" is unclear; the late ones every 4th

    def test_a_backend_that_runs_out_of_time_says_so_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = ev.detect_all(Path(tmp), self.rows, "owlv2", fake=True, budget_s=-1.0)   # the fake detector; no time at all
            self.assertEqual((entry["frames_done"], entry["frames_asked"]), (0, 4))
            self.assertIn("out of time", entry["cut_short"])

    def test_the_fake_detector_says_it_is_fake(self):
        about = ev.FakeDetector([]).start()["about"]
        self.assertTrue(about["fake"])
        self.assertIn("fake", about["model"])


if __name__ == "__main__":
    unittest.main()
