"""kokopelli/wm/video_check.py: the mosaic and drift scores, the push-by-push run check, and its hook in world_stream_multi.
Synthetic frames only; the calibration on real painted clips is `python -m kokopelli.wm.video_check calibrate`."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

from kokopelli.wm import video_check as vc  # noqa: E402
from kokopelli.wm.world_stream_multi import MultiWorldStream  # noqa: E402


def scene(h=128, w=224, seed=0):
    """A clean stand-in for a painted frame: a smooth sky-to-ground gradient, a few flat blocks, light noise."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([90 + 80 * y / h, 120 + 60 * x / w, 200 - 60 * y / h], -1)
    for _ in range(6):
        x0, y0 = rng.integers(0, w - 40), rng.integers(0, h - 30)
        img[y0:y0 + rng.integers(10, 30), x0:x0 + rng.integers(10, 40)] = rng.integers(30, 220, 3)
    img += rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def tiled(frame, seed=1, strength=0.9):
    """The failure seen in the lunch films: a saturated colour blob in every 16 px latent tile."""
    rng = np.random.default_rng(seed)
    out = frame.astype(np.float32)
    yy, xx = np.mgrid[0:16, 0:16].astype(np.float32)
    blob = strength * np.exp(-((yy - 8) ** 2 + (xx - 8) ** 2) / 18)[..., None]
    for ty in range(0, frame.shape[0], 16):
        for tx in range(0, frame.shape[1], 16):
            colour = rng.integers(0, 256, 3).astype(np.float32)
            out[ty:ty + 16, tx:tx + 16] = out[ty:ty + 16, tx:tx + 16] * (1 - blob) + colour * blob
    return np.clip(out, 0, 255).astype(np.uint8)


class Scores(unittest.TestCase):
    def test_a_clean_frame_is_under_the_mosaic_line_and_a_tiled_one_over_it(self):
        clean = scene()
        self.assertLess(vc.frame_scores(clean)["mosaic"], vc.MOSAIC_MAX)
        self.assertGreater(vc.frame_scores(tiled(clean))["mosaic"], vc.MOSAIC_MAX)

    def test_a_flat_frame_scores_zero_not_nan(self):
        scores = vc.frame_scores(np.full((64, 64, 3), 90, np.uint8), np.full((64, 64, 3), 90, np.uint8))
        self.assertEqual(scores["mosaic"], 0.0)
        self.assertFalse(np.isnan(scores["drift"]))

    def test_drift_is_high_when_the_painting_follows_its_control_and_low_when_it_does_not(self):
        frame = scene()
        self.assertGreater(vc.frame_scores(frame, frame)["drift"], 0.9)
        self.assertLess(vc.frame_scores(frame, frame[:, ::-1].copy())["drift"], vc.DRIFT_MIN)

    def test_no_control_means_no_drift_verdict(self):
        verdict = vc.judge([vc.frame_scores(scene())])
        self.assertIsNone(verdict["drift"])
        self.assertEqual(verdict["bad"], [])


class Runs(unittest.TestCase):
    def setUp(self):
        self.clean = np.stack([scene(seed=s % 3) for s in range(24)])
        self.bad = np.stack([tiled(f, seed=i) for i, f in enumerate(self.clean)])

    def test_three_bad_pushes_in_a_row_fail_the_run(self):
        rc = vc.RunCheck()
        for _ in range(2):
            self.assertTrue(rc.feed(self.bad, self.clean)["bad"])
        self.assertFalse(rc.failed)
        rc.feed(self.bad, self.clean)
        self.assertTrue(rc.failed)
        self.assertIn("mosaic", rc.reason)

    def test_a_good_push_resets_the_count(self):
        rc = vc.RunCheck()
        for frames in (self.bad, self.bad, self.clean, self.bad, self.bad):
            rc.feed(frames, self.clean)
        self.assertFalse(rc.failed)
        self.assertEqual([bool(p["bad"]) for p in rc.pushes], [True, True, False, True, True])

    def test_painting_that_ignores_its_control_fails_as_drift(self):
        rc = vc.RunCheck()
        for _ in range(3):
            rc.feed(self.clean, self.clean[:, :, ::-1])
        self.assertTrue(rc.failed)
        self.assertIn("drift", rc.reason)

    def test_painted_frames_are_matched_to_the_controls_they_lag(self):
        """The first push paints 21 of 24 frames; the 3 held back meet their controls in the next push."""
        rc = vc.RunCheck()
        rc.feed(self.clean[:21], self.clean)
        self.assertEqual(len(rc.waiting), 3)
        rc.feed(self.clean[21:], self.clean)
        self.assertEqual(len(rc.waiting), 24)
        self.assertEqual(rc.frames, 24)

    def test_a_push_too_short_to_judge_is_skipped(self):
        rc = vc.RunCheck()
        self.assertIsNone(rc.feed(self.bad[:vc.MIN_FRAMES - 1]))
        self.assertEqual(rc.pushes, [])

    def test_the_record_is_written_when_given_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = vc.RunCheck(Path(tmp) / "check.json", "mara")
            rc.feed(self.clean, self.clean)
            saved = json.loads((Path(tmp) / "check.json").read_text())
        self.assertEqual(saved["stream"], "mara")
        self.assertFalse(saved["failed"])
        self.assertEqual(saved["thresholds"]["mosaic_max"], vc.MOSAIC_MAX)

    def test_windows_and_first_failure_match_the_hook(self):
        rows = [{"frame": i, "mosaic": 1.5 if i >= 48 else 0.5, "drift": 0.7} for i in range(0, 144, 2)]
        wins = vc.windows(rows, fps=16)
        self.assertEqual(len(wins), 6)
        self.assertEqual(vc.first_failure(wins)["t"], 6.0)   # windows at 3.0, 4.5 and 6.0 s are bad
        self.assertEqual(vc.classify(wins, 0, 3), "good")


class Hook(unittest.TestCase):
    """The check inside MultiWorldStream.push, with the fake painter (0.6 blur + 0.4 edge) and no model."""

    def controls(self, blur, edge):
        return {"blur": blur, "seg": blur, "depth": blur, "edge": edge}

    def test_the_fake_painter_is_not_checked_by_default(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KOKO_VIDEO_CHECK": ""}):
            wm = MultiWorldStream(out_dir=tmp, fake=True)
            try:
                wm.open("mara", "p", size="224x128")
                bad = np.stack([tiled(scene(), seed=i) for i in range(24)])
                for _ in range(4):
                    wm.push("mara", self.controls(bad, bad))
            finally:
                wm.close()
            self.assertFalse((Path(tmp) / "check.json").exists())

    def test_a_tiled_stream_stops_on_the_third_bad_push_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KOKO_VIDEO_CHECK": ""}):
            wm = MultiWorldStream(out_dir=tmp, fake=True, check="stop")
            try:
                wm.open("mara", "p", size="224x128")
                wm.open("iris", "p", size="224x128", seed=2026)
                clean = np.stack([scene() for _ in range(24)])
                bad = np.stack([tiled(scene(), seed=i) for i in range(24)])
                wm.push("iris", self.controls(clean, clean))
                wm.push("mara", self.controls(bad, bad))
                wm.push("mara", self.controls(bad, bad))
                with self.assertRaisesRegex(RuntimeError, "video check failed for mara"):
                    wm.push("mara", self.controls(bad, bad))
            finally:
                wm.close()
            saved = json.loads((Path(tmp) / "check.json").read_text())
        self.assertTrue(saved["failed"])
        self.assertTrue(saved["streams"]["mara"]["failed"])
        self.assertFalse(saved["streams"]["iris"]["failed"])

    def test_warn_records_the_failure_without_stopping(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KOKO_VIDEO_CHECK": "warn"}):
            wm = MultiWorldStream(out_dir=tmp, fake=True, check="stop")
            try:
                wm.open("mara", "p", size="224x128")
                bad = np.stack([tiled(scene(), seed=i) for i in range(24)])
                for _ in range(4):
                    wm.push("mara", self.controls(bad, bad))
            finally:
                wm.close()
            saved = json.loads((Path(tmp) / "check.json").read_text())
        self.assertEqual(saved["mode"], "warn")
        self.assertTrue(saved["failed"])


if __name__ == "__main__":
    unittest.main()
