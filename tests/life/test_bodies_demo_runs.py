"""The overnight bodies demo shows up on the dev panel's model runs page as its own group."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kokopelli.life import world_runs
from tests.life.test_life_world_runs import make_video


class BodiesDemoRuns(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        out = Path(self.temp.name)
        demo = out / "bodies" / "demo"
        make_video(demo / "20261108" / "demo.mp4", 24)
        (demo / "20261108" / "demo.mp4.json").write_text(json.dumps({
            "agent_model": "Qwen3-VL-8B-Instruct-4bit", "world_model": "Cosmos3-Nano-Sim-Transfer",
            "world_model_settings": {"size": "448x256", "fps": 24}, "run_dir": str(demo / "runs" / "wm")}))
        make_video(demo / "20261108" / "demo_sim_only.mp4", 24)
        (demo / "20261108" / "demo_sim_only.mp4.json").write_text(json.dumps({"agent_model": "Qwen3-VL-8B-Instruct-4bit", "world_model": None}))
        for run, fake in (("sim", True), ("wm", False)):
            (demo / "runs" / run / "film").mkdir(parents=True)
            (demo / "runs" / run / "run.json").write_text(json.dumps({
                "fake_world_model": fake, "world_model": "Cosmos3-Nano-Sim-Transfer", "size": "448x256", "fps": 24,
                "agent_model": "Qwen3-VL-8B-Instruct-4bit", "sim_steps": 12, "steps_done": 12, "finished": True}))
            for name in ("side_by_side", "sim_mara"):
                make_video(demo / "runs" / run / "film" / f"{name}.mp4", 24)
        make_video(demo / "runs" / "wm" / "film" / "parts" / "mara_0001.mp4", 24)   # segments aren't listed
        patcher = mock.patch.object(world_runs, "OUT", out)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runs = {run["name"]: run for run in world_runs.bodies_demo_entries()}

    def test_cuts_and_run_films_are_listed_and_nothing_else(self):
        self.assertEqual(set(self.runs), {"20261108 demo", "20261108 demo_sim_only", "sim side_by_side", "sim sim_mara",
                                          "wm side_by_side", "wm sim_mara"})

    def test_kind_follows_whether_the_world_model_was_real(self):
        self.assertEqual(self.runs["20261108 demo"]["kind"], "cosmos")
        self.assertEqual(self.runs["20261108 demo_sim_only"]["kind"], "sim")
        self.assertEqual(self.runs["wm side_by_side"]["kind"], "cosmos")
        self.assertEqual(self.runs["sim side_by_side"]["kind"], "sim")
        self.assertEqual(self.runs["wm sim_mara"]["kind"], "sim")

    def test_group_is_registered_and_videos_resolve(self):
        self.assertIn("bodies_demo", [g["id"] for g in world_runs.GROUPS])
        run = self.runs["20261108 demo"]
        self.assertEqual(world_runs.video_file(run["id"]), Path(run["path"]))


if __name__ == "__main__":
    unittest.main()
