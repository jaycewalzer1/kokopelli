"""Multi-control runs show up on the dev panel's model runs page, described from their sidecars."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kokopelli.life import world_runs
from tests.test_life_world_runs import make_video


class MultiControlRuns(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / "wm_multicontrol"
        make_video(root / "a2" / "a2.mp4", 17)
        (root / "a2" / "a2.mp4.json").write_text(json.dumps({
            "model": "Cosmos3-Nano-Sim-Transfer", "variant": "A", "steps": 4, "weights": {"blur": 0.5, "seg": 0.5},
            "controls": {"blur": "b.mp4", "seg": "s.mp4"}, "size": "832x480", "frames": 17, "seed": 2025, "seconds": 99.9,
            "peak_gb": 14.17}))
        make_video(root / "a1" / "blur_world_transfer.mp4", 17)
        (root / "a1" / "blur_world_transfer.mp4.json").write_text(json.dumps({
            "model": "Cosmos3-Nano-Sim-Transfer", "steps": 4, "controls": {"blur": "b.mp4"}, "size": "832x480", "frames": 17,
            "seed": 2025, "seconds": 71.9, "peak_gb": 13.9}))
        make_video(root / "a4_vs_b4.mp4", 24)
        (root / "notes.json").write_text(json.dumps({"a4_vs_b4": "A4 left, B4 right."}))
        (root / "a1" / "blur_world_transfer.npy").write_bytes(b"not a video")
        patcher = mock.patch.object(world_runs, "OUT", root.parent)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runs = {run["name"]: run for run in world_runs.multicontrol_entries()}

    def test_every_video_is_listed_and_nothing_else(self):
        self.assertEqual(set(self.runs), {"a2/a2", "a1/blur_world_transfer", "a4_vs_b4"})

    def test_lines_come_from_the_sidecar(self):
        lines = self.runs["a2/a2"]["lines"]
        self.assertIn("blur 0.50 + seg 0.50", lines)
        self.assertIn("832x480, 17 frames, seed 2025", lines)
        self.assertIn("took 1.7 min, peak 14.17 GB", lines)
        self.assertIn("world_transfer_multi.py", self.runs["a2/a2"]["about"])

    def test_a_single_control_baseline_and_a_side_by_side(self):
        self.assertIn("blur 1.00", self.runs["a1/blur_world_transfer"]["lines"])
        self.assertIn("Baseline", self.runs["a1/blur_world_transfer"]["about"])
        self.assertEqual(self.runs["a4_vs_b4"]["about"], "A4 left, B4 right.")

    def test_the_group_is_on_the_page_and_its_videos_are_served(self):
        self.assertIn("multicontrol", [group["id"] for group in world_runs.GROUPS])
        run = self.runs["a2/a2"]
        self.assertEqual(world_runs.video_file(run["id"]).name, "a2.mp4")


if __name__ == "__main__":
    unittest.main()
