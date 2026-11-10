import tempfile
import unittest
from pathlib import Path

from kokopelli.loop.config import Config
from kokopelli.loop.memory import MemorySampler, used_gb
from kokopelli.loop.replay import summarize
from kokopelli.loop.run import run


class MemoryTest(unittest.TestCase):
    def test_used_memory_is_a_believable_number(self):
        value = used_gb()
        self.assertIsNotNone(value)
        self.assertGreater(value, 0.1)

    def test_take_returns_the_peak_and_starts_over(self):
        sampler = MemorySampler()
        sampler.peak = 9999.0
        self.assertEqual(sampler.take(), 9999.0)
        self.assertLess(sampler.peak, 9999.0)
        sampler.close()

    def test_a_run_reports_memory_per_stage(self):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        summary = run(Config(ticks=1, counterfactual=False), folder)
        self.assertEqual(set(summary["run"]["totals"]["peak_memory_gb"]), {"sim", "wm", "agent"})
        self.assertEqual(set(summarize(folder)["ticks"][0]["timing"]["memory_gb"]), {"sim", "wm", "agent"})
