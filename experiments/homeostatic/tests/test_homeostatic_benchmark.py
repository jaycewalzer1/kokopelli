"""The benchmark, the comparison statistics and the report. No model is involved."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from experiments.homeostatic.benchmark import constant_policy, paired_difference, planner_policy, random_policy, run_benchmark, run_episode, summarize
from experiments.homeostatic.evaluate import evaluate
from experiments.homeostatic.report import write_report
from kokopelli.settings import HOMEOSTATIC_SEEDS, HOMEOSTATIC_WORLD as WORLD

SEEDS = range(200000, 200040)


class EpisodeTest(unittest.TestCase):
    def test_an_episode_replays_exactly(self):
        self.assertEqual(run_episode(constant_policy("rest"), 5), run_episode(constant_policy("rest"), 5))

    def test_a_reply_that_isnt_an_action_counts_as_invalid_and_does_nothing(self):
        gibberish, idle = run_episode(lambda state: "hmm", 5), run_episode(constant_policy("idle"), 5)
        self.assertEqual(gibberish["invalid"], 1.0)
        self.assertEqual(idle["invalid"], 0.0)
        self.assertEqual(gibberish["mean_drive"], idle["mean_drive"])

    def test_dying_is_recorded_and_counts_against_mean_drive(self):
        result = run_episode(constant_policy("work"), 5)
        self.assertEqual(result["deaths"], 1.0)
        self.assertLess(len(result["actions"]), WORLD["horizon"])
        self.assertGreater(result["mean_drive"], run_episode(constant_policy("idle"), 5)["mean_drive"])

    def test_the_policies_rank_the_way_they_should(self):
        drive = lambda policy: summarize(run_benchmark(policy, SEEDS))["mean_drive"]
        self.assertLess(drive(planner_policy(3)), drive(planner_policy(1)))
        self.assertLess(drive(planner_policy(1)), drive(constant_policy("idle")))
        self.assertLess(drive(constant_policy("idle")), drive(random_policy()))

    def test_the_seed_splits_never_overlap(self):
        names = list(HOMEOSTATIC_SEEDS)
        for index, first in enumerate(names):
            for second in names[index + 1:]:
                self.assertFalse(set(HOMEOSTATIC_SEEDS[first]) & set(HOMEOSTATIC_SEEDS[second]))


class ComparisonTest(unittest.TestCase):
    def test_a_real_difference_is_clear_and_noise_is_not(self):
        rng = np.random.default_rng(0)
        base = [{"m": value} for value in rng.normal(10, 3, 100)]
        better = [{"m": row["m"] - 2 + noise} for row, noise in zip(base, rng.normal(0, 1, 100))]
        same = [{"m": row["m"] + noise} for row, noise in zip(base, rng.normal(0, 1, 100))]
        found = paired_difference(better, base, "m")
        self.assertLess(found["high"], 0)
        found = paired_difference(same, base, "m")
        self.assertLess(found["low"], 0)
        self.assertGreater(found["high"], 0)

    def test_comparing_different_lives_is_refused(self):
        with self.assertRaises(ValueError):
            paired_difference([{"m": 1}], [{"m": 1}, {"m": 2}], "m")

    def test_lives_with_no_measurement_are_left_out_of_both_sides(self):
        found = paired_difference([{"m": None}, {"m": 3}], [{"m": 100}, {"m": 1}], "m")
        self.assertEqual(found["difference"], 2)


class ReportTest(unittest.TestCase):
    def test_report_compares_each_trained_run_with_its_controls_on_saved_results(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            policies = {"base": constant_policy("idle"), "homeostatic-0": planner_policy(1), "maximize-0": constant_policy("rest"), "shuffled-0": random_policy()}
            for name, policy in policies.items():
                evaluate(policy, out / "results" / f"{name}-train.json", "train", SEEDS)
            self.assertIn("mean_drive", json.loads((out / "results" / "base-train.json").read_text())["summary"])
            text = write_report(out)
            self.assertEqual(text, (out / "report.md").read_text())
            for phrase in ("homeostatic-0 minus base, mean_drive", "homeostatic-0 minus maximize-0, above", "homeostatic-0 minus shuffled-0, in_range"):
                self.assertIn(phrase, text)
            self.assertNotIn("never trained on", text)


if __name__ == "__main__":
    unittest.main()
