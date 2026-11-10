import tempfile
import unittest
from pathlib import Path

import numpy as np

from kokopelli.loop import drift, replay
from kokopelli.loop.config import Config
from kokopelli.loop.frames import save_rgb
from kokopelli.loop.interfaces import CondFrame
from kokopelli.loop.mocks.agent import NullAgent
from kokopelli.loop.mocks.sim import MockSim
from kokopelli.loop.run import run


def scene(shift=0):
    image = np.full((256, 448, 3), 200, np.uint8)
    image[100:140, 100:160] = 40
    return np.roll(image, shift, axis=1)


class ScoreTest(unittest.TestCase):
    def test_score_rises_with_the_error(self):
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            base = save_rgb(scene(), f"{folder}/a.png")
            scores = [drift.score(save_rgb(scene(shift), f"{folder}/b.png"), base)["score"] for shift in (0, 10, 30, 90)]
        self.assertEqual(scores[0], 0)
        self.assertEqual(scores, sorted(scores))
        self.assertGreater(scores[-1], 0.5)


class PolicyTest(unittest.TestCase):
    def test_reasons(self):
        config = Config(drift_threshold=0.5, reanchor_every=60)
        self.assertEqual(drift.reanchor_reason(0.6, 0, config), "threshold")
        self.assertEqual(drift.reanchor_reason(0.1, 60, config), "scheduled")
        self.assertIsNone(drift.reanchor_reason(0.1, 15, config))
        self.assertIsNone(drift.reanchor_reason(0.9, 90, Config(drift_control=False)))

    def test_anchor_replaces_only_the_oldest_frame(self):
        cond = [CondFrame(str(i), "wm") for i in range(5)]
        result = drift.anchored(cond, "sim.png", CondFrame)
        self.assertEqual([(f.path, f.source) for f in result], [("sim.png", "sim"), *[(str(i), "wm") for i in range(1, 5)]])


class LoopTest(unittest.TestCase):
    def scores(self, **settings):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        run(Config(ticks=24, counterfactual=False, **settings), folder)
        ticks = replay.summarize(folder)["ticks"]
        return [check["score"] for tick in ticks for check in tick["drift"]], sum(len(tick["reanchors"]) for tick in ticks)

    def test_drift_control_keeps_the_mock_closer(self):
        controlled, anchors = self.scores()
        loose, none = self.scores(drift_control=False)
        self.assertGreater(anchors, 0)
        self.assertEqual(none, 0)
        self.assertLess(np.mean(controlled[-8:]), np.mean(loose[-8:]))

    def test_checks_happen_every_15_sim_seconds(self):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        run(Config(ticks=2, counterfactual=False), folder)
        self.assertEqual([c["offset_s"] for t in replay.summarize(folder)["ticks"] for c in t["drift"]], [15, 30, 15, 30])


class AutonomyTest(unittest.TestCase):
    def test_a_scripted_agent_moves_away_from_the_null_agent(self):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        summary = run(Config(ticks=8), folder)
        self.assertIsNotNone(summary["run"]["totals"]["autonomy"])
        self.assertGreater(replay.summarize(folder)["run"]["counterfactual"]["max_distance"], 0)

    def test_the_null_agent_matches_its_own_counterfactual(self):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        run(Config(ticks=8), folder, agent=NullAgent())
        result = replay.summarize(folder)["run"]["counterfactual"]
        self.assertEqual(result["max_distance"], 0)
        self.assertEqual(result["objects_changed_at_end"], 0)

    def test_people_move_the_same_whatever_the_agent_does(self):
        a, b = MockSim(), MockSim()
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            a.reset(1, "2004-06-12T16:00:00", folder, [15, 30])
            b.reset(1, "2004-06-12T16:00:00", folder, [15, 30])
            first = a.step({"type": "move_to", "target": "ball"}, 1, render=False).state
            second = b.step({"type": "wait"}, 1, render=False).state
        self.assertEqual(first["npcs"], second["npcs"])
        self.assertNotEqual(first["agent"]["pos"], second["agent"]["pos"])


class SimTest(unittest.TestCase):
    def test_a_tick_is_thirty_seconds_with_two_captures(self):
        sim = MockSim()
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            sim.reset(1, "2004-06-12T16:00:00", folder, [15, 30])
            result = sim.step({"type": "wait"}, 1)
            self.assertEqual(result.state["sim_time"], "2004-06-12T16:00:30")
            self.assertEqual([c.offset_s for c in result.captures], [15, 30])

    def test_interact_needs_the_agent_nearby(self):
        sim = MockSim()
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            sim.reset(1, "2004-06-12T16:00:00", folder, [15, 30])
            far = sim.step({"type": "interact", "target": "ball"}, 1, render=False).state
            self.assertEqual(far["last_result"]["reason"], "too far")
            self.assertEqual(far["objects"]["ball"]["state"], "at rest")


if __name__ == "__main__":
    unittest.main()
