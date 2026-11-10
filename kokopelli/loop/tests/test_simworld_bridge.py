"""The whole loop against the fake SimWorld server. This needs unrealcv, so run it with simworld/.venv."""
import tempfile
import unittest
from pathlib import Path

from kokopelli.loop.config import Config
from kokopelli.loop.replay import summarize
from kokopelli.loop.run import run

try:
    import unrealcv  # noqa: F401
    from kokopelli.loop.tests.fake_unrealcv import FakeUnrealCV
    HAS_CLIENT = True
except ImportError:
    HAS_CLIENT = False

FAST = dict(tick_interval_s=0.5, control_interval_s=0.5, settle_s=0, init_settle_s=0, reconnect_backoff_s=0.01,
            agent_position=(0.0, 0.0, 100.0), request_timeout_s=5.0, connect_timeout_s=5.0)


class CrashAfter:
    """Lets the first steps through, then raises, to test resuming."""

    def __init__(self, sim, tick):
        self.sim, self.tick = sim, tick

    def __getattr__(self, name):
        return getattr(self.sim, name)

    def step(self, action, tick, render=True):
        if tick == self.tick:
            raise RuntimeError("the simulator fell over")
        return self.sim.step(action, tick, render)


@unittest.skipUnless(HAS_CLIENT, "needs unrealcv; run with simworld/.venv")
class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        self.folder = Path(tempfile.mkdtemp(prefix="wmloop_"))

    def config(self, ticks=3):
        return Config(ticks=ticks, sim="simworld", sim_settings={**FAST, "port": self.server.port}, counterfactual=False)

    def test_the_whole_loop_runs_on_simworld(self):
        summary = run(self.config(), self.folder)
        self.assertEqual(summary["run"]["totals"]["ticks"], 3)
        tick = summarize(self.folder)["ticks"][1]
        self.assertEqual(tick["sim"]["state"]["sim_time"], "2004-06-12T16:01:00")
        self.assertEqual([capture["offset_s"] for capture in tick["sim"]["captures"]], [15, 30])
        self.assertEqual(len(tick["drift"]), 2)
        self.assertTrue((self.folder / tick["sim"]["captures"][0]["rgb"]).exists())
        self.assertIn("raw", tick["sim"]["state"])

    def test_what_the_agent_can_see_are_real_ids(self):
        run(self.config(1), self.folder)
        visible = summarize(self.folder)["ticks"][0]["sim"]["visible"]
        self.assertGreater(len(visible), 0)

    def test_an_action_simworld_rejects_costs_the_turn_not_the_run(self):
        from kokopelli.loop.adapters.simworld_bridge import SimWorldSim
        sim = SimWorldSim({**FAST, "port": self.server.port})
        self.addCleanup(sim.close)
        first = sim.reset(1, "2004-06-12T16:00:00", self.folder, [15, 30])
        person = next(name for name in first.visible if name in first.state["npcs"])
        result = sim.step({"type": "interact", "target": person}, 1)
        self.assertFalse(result.state["last_result"]["ok"])
        self.assertIsNotNone(result.state["last_result"]["rejected"])
        self.assertEqual(result.state["sim_time"], "2004-06-12T16:00:30")

    def test_a_checkpoint_survives_json_and_a_crash_resumes(self):
        from kokopelli.loop.adapters.simworld_bridge import SimWorldSim
        sim = SimWorldSim({**FAST, "port": self.server.port})
        with self.assertRaises(RuntimeError):
            run(self.config(4), self.folder, sim=CrashAfter(sim, 3))
        summary = run(self.config(4), self.folder, resume=True)
        self.assertEqual(summary["run"]["totals"]["ticks"], 4)
        self.assertEqual(summary["run"]["resumes"], 1)


if __name__ == "__main__":
    unittest.main()
