"""Experiment 1, phase 1: the world wiring, the balance check, the leak check and the tabular reference. No model."""
import unittest
from datetime import time

import numpy as np

from experiments.exp1 import balance, observe, tabular_check
from experiments.exp1 import homeostasis as H
from experiments.exp1.world import ARMS, FLIP, Life
from kokopelli.life import scenario


def play(seed, arm, choose=None, days=25):
    """A whole life; choose(pending, rng) picks on free days, uniformly at random by default."""
    life, rng = Life(seed, arm, days), np.random.default_rng(seed)
    observations = []
    while not life.finished:
        pending = life.pending()
        observations.append(observe.observation(pending, life.records, seed))
        choice = pending.forced or (choose(pending, rng) if choose else pending.shown[rng.integers(len(pending.shown))])
        life.choose(choice)
    return life, observations


class WorldTest(unittest.TestCase):
    def test_reward_is_the_outcome_step_only_and_depletion_follows(self):
        life, _ = play(3, "lived")
        rows = life.records
        for row, after in zip(rows, rows[1:], strict=False):
            self.assertAlmostEqual(row["reward"], row["drive_pre"] - row["drive_post"], places=5)
            if after["index"] == row["index"]:  # same morning: next decision starts depleted, and that drop earned nothing
                np.testing.assert_allclose(after["h_pre"], np.clip(np.array(row["h_post"]) - H.DEPLETE, 0, 1), atol=1e-6)

    def test_needs_reset_each_morning(self):
        life, _ = play(4, "lived")
        for row in life.records:
            if row["decision"] == "D1":
                expected = H.start_state(np.random.default_rng([4, 7, row["index"]]))
                np.testing.assert_allclose(row["h_pre"], expected, atol=1e-6)

    def test_gate_follows_arrival(self):
        for seed in range(20):
            life, _ = play(seed, "lived")
            d1 = {row["index"]: row for row in life.records if row["decision"] == "D1"}
            for row in life.records:
                if row["decision"] == "D2":
                    first = d1[row["index"]]
                    outcome = scenario.outcome_of(first["choice"], first["outcome_label"])
                    expected = outcome.on_time or outcome.arrival <= time(9, 8)
                    self.assertEqual(row["gate_open"], expected)
                    self.assertEqual(scenario.FRONT_GAP in row["options_shown"], expected)

    def test_lived_outcomes_come_from_the_schedule_in_order(self):
        life, _ = play(5, "lived")
        seen = {}
        for row in life.records:
            k = seen.get(row["choice"], 0)
            self.assertEqual(row["schedule_index"], k)
            self.assertEqual(row["outcome_label"], life.schedule["by_option"][row["choice"]][k])
            seen[row["choice"]] = k + 1
        self.assertEqual(life.schedule["by_option"], scenario.schedule(5, len(life.schedule["by_option"]["walk_main"])))

    def test_exploration_forces_every_option_twice_then_25_free_days(self):
        for seed in range(30):
            life, _ = play(seed, "lived")
            forced = [row for row in life.records if row["forced"]]
            if life.explore_complete:
                for option in scenario.OPTIONS:
                    self.assertGreaterEqual(sum(row["choice"] == option.id for row in forced), 2, option.id)
            self.assertTrue(all(row["phase"] == "exploration" for row in forced))
            free = [row for row in life.records if row["phase"] == "free"]
            self.assertEqual(sorted({row["day"] for row in free}), list(range(1, 26)))
            self.assertFalse(any(row["forced"] for row in free))

    def test_forced_choice_must_be_taken(self):
        life = Life(0, "lived")
        pending = life.pending()
        other = next(o for o in pending.shown if o != pending.forced)
        with self.assertRaises(ValueError):
            life.choose(other)

    def test_shuffled_outcomes_ignore_the_choice(self):
        always_first = lambda pending, rng: pending.shown[0]
        always_last = lambda pending, rng: pending.shown[-1]
        a, _ = play(6, "shuffled", always_first)
        b, _ = play(6, "shuffled", always_last)
        d1 = lambda life: [(row["outcome_source"], row["outcome_label"]) for row in life.records if row["decision"] == "D1"]
        self.assertEqual(d1(a), d1(b))  # D1 always offers the same options, so its outcomes can't depend on the choice

    def test_flipped_swaps_rare_bad_and_rare_good_need_changes(self):
        life, _ = play(7, "flipped")
        for row in life.records:
            partner = FLIP.get(row["choice"], row["choice"])
            expected = next(d for _, d, key in H.TABLES[row["decision"]][partner] if key == row["outcome_label"])
            np.testing.assert_allclose(row["delta"], expected)


class BalanceTest(unittest.TestCase):
    def test_every_option_within_2_percent_at_the_mean_entry_state(self):
        found = balance.report(samples=4000)
        for name, row in found.items():
            self.assertTrue(row["at_mean_state"]["within_2_percent"], f"{name}: {row['at_mean_state']['vs_safe']}")


class LeakTest(unittest.TestCase):
    def test_the_checker_catches_odds_counts_numbers_and_averages(self):
        for text in ("It goes wrong 10% of the time.", "You usually make it.", "You've tripped 3 times.", "calm 0.45",
                     "On average it's fine.", "the odds are good", "twice this week", "one out of ten"):
            self.assertTrue(observe.find_leaks(text), text)
        self.assertFalse(observe.find_leaks("9:50. Buses leave the main gate at 10:00 and 10:30."))

    def test_nothing_numeric_or_statistical_reaches_any_arm(self):
        for arm in ARMS:
            for seed in range(8):
                life, observations = play(seed, arm)  # observation() raises on a leak
                for row in life.records:
                    observe.check(row["felt_text"])
                    observe.check(row["memory"])
                self.assertTrue(all("HOW YOU FEEL\nYou feel" in text for text in observations))
                for index in range(life.index):
                    observe.check("\n".join(observe.history(life.records, index)))


class TabularReferenceTest(unittest.TestCase):
    """Hot-stove direction at lr 8. D3 shows it clearly with scenario.py as written. D1 only weakly (run_main 0.255 vs
    check_desk 0.223 at 2000 lives, not reliably past the margin at 800): run_main's common outcome puts all of its gain
    on calm, which the deficit-only drive caps at 0.7, so run_main earns about 12% less than the safe option and the cap
    works against the effect (experiments/exp1/balance.py). Those cases are expected failures until that need change is decided;
    they'll report an unexpected success once it's fixed. See docs/exp1_phase1.md."""

    @classmethod
    def setUpClass(cls):
        cls.found = {arm: tabular_check.summarize(arm, 8.0, lives=800) for arm in ARMS}

    def shares(self, arm, group):
        return self.found[arm]["shares"][group]["options"]

    def test_d3_lived_keeps_rare_bad_and_drops_rare_good(self):
        d3 = self.shares("lived", "D3")
        self.assertGreater(d3["leave_early"], d3["stay_and_chat"] + 0.03)

    def test_d3_flipped_reverses(self):
        d3 = self.shares("flipped", "D3")
        self.assertGreater(d3["stay_and_chat"], d3["leave_early"] + 0.03)

    def test_shuffled_stays_near_chance(self):
        for group in ("D1", "D3"):
            for option, share in self.shares("shuffled", group).items():
                self.assertAlmostEqual(share, 0.25, delta=0.04, msg=f"{group} {option}")

    @unittest.expectedFailure
    def test_d1_lived_keeps_rare_bad_and_drops_rare_good(self):
        d1 = self.shares("lived", "D1")
        self.assertGreater(d1["run_main"], d1["check_desk"] + 0.03)

    @unittest.expectedFailure
    def test_pooled_lived_rare_bad_above_rare_good(self):
        roles = self.found["lived"]["roles"]
        self.assertGreater(roles["rare_bad"], roles["rare_good"] + 0.03)


if __name__ == "__main__":
    unittest.main()
