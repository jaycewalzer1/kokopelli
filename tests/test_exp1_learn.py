"""Experiment 1, phase 2: the learning rule and the run loop, with the table policy standing in for Qwen. No model."""
import json
import tempfile
import unittest
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from exp1 import baselines, observe
from exp1.learn import Baseline, Sleeper, replay_rows
from exp1.policy import TablePolicy, continuation
from exp1.run import Run, probes

FIELDS = ("h_pre", "h_post", "delta", "drive_pre", "drive_post", "reward", "baseline", "advantage", "pi", "choice", "schedule_index",
          "outcome_label", "felt_text", "lora_step")
SLEEP_FIELDS = ("loss_pg", "loss_kl", "kl", "grad_norm", "lr", "steps")


def quiet_run(folder, arm="lived", seed=0, days=6, lr=0.01):
    run = Run(folder, arm, seed, days, "table", {"lr": lr})
    run.live()
    return run


class BaselineTest(unittest.TestCase):
    def test_advantage_is_reward_minus_the_baseline_before_it_moves(self):
        b = Baseline(["D1"])
        self.assertEqual(b.advantage("D1", 0.1), (0.0, 0.1))
        before, advantage = b.advantage("D1", 0.1)
        self.assertAlmostEqual(before, 0.02)
        self.assertAlmostEqual(advantage, 0.08)


class SleepTest(unittest.TestCase):
    def row(self, choice, advantage, pi=None):
        shown = ["walk_main", "run_main", "check_desk", "side_path"]
        return {"shown": shown, "choice": choice, "advantage": advantage, "pi": pi or {o: 0.25 for o in shown},
                "base_logp": [float(np.log(0.25))] * 4}

    def test_first_night_has_zero_kl_and_moves_toward_positive_advantage(self):
        policy = TablePolicy()
        stats = Sleeper(policy, {"lr": 0.05, "steps": 1}).sleep([self.row("run_main", 0.1)])
        self.assertEqual(stats["kl"], 0.0)
        p = np.exp(np.array(policy.log_probs({"shown": ["walk_main", "run_main", "check_desk", "side_path"]})))
        self.assertGreater(p[1], 0.25)
        for field in SLEEP_FIELDS:
            self.assertIn(field, stats)

    def test_negative_advantage_moves_away(self):
        policy = TablePolicy()
        Sleeper(policy, {"lr": 0.05, "steps": 1}).sleep([self.row("run_main", -0.1)])
        p = np.exp(np.array(policy.log_probs({"shown": ["walk_main", "run_main", "check_desk", "side_path"]})))
        self.assertLess(p[1], 0.25)

    def test_importance_weight_is_clipped(self):
        policy = TablePolicy()
        sleeper = Sleeper(policy, {"lr": 0.05, "steps": 1})
        stale = self.row("run_main", 0.1, pi={"walk_main": 0.9, "run_main": 0.01, "check_desk": 0.045, "side_path": 0.045})
        stats = sleeper.sleep([stale])
        self.assertAlmostEqual(stats["per_step"][0]["weight_mean"], 1.2, places=5)
        self.assertEqual(stats["per_step"][0]["weights_clipped"], 1)

    def test_kl_pulls_back_toward_base_when_there_is_no_reward_signal(self):
        policy = TablePolicy()
        policy.model.logits = mx.array([2.0] + [0.0] * (policy.model.logits.size - 1))
        Sleeper(policy, {"lr": 0.05, "steps": 4, "beta": 1.0}).sleep([self.row("walk_main", 0.0)])
        self.assertLess(float(policy.model.logits[0]), 2.0)

    def test_option_by_option_gradient_equals_the_whole_gradient(self):
        policy = TablePolicy()
        policy.model.logits = mx.array(np.random.default_rng(0).normal(size=policy.model.logits.size).astype(np.float32))
        sleeper = Sleeper(policy, {"beta": 0.3})
        row = self.row("run_main", 0.2, pi={"walk_main": 0.1, "run_main": 0.3, "check_desk": 0.4, "side_path": 0.2})
        split, *_ = sleeper._sample_grad(row, 0.5)
        whole = nn.value_and_grad(policy.model, lambda model: sleeper._loss_of_scores(policy.scores(row), row, 0.5)[0])(policy.model)[1]
        np.testing.assert_allclose(np.array(split["logits"]), np.array(whole["logits"]), atol=1e-6)

    def test_a_steps_transition_shares_add_up_to_one(self):
        from exp1.diagnose_pilot import night_summary, shares_step
        policy = TablePolicy()
        policy.model.logits = mx.array(np.random.default_rng(0).normal(size=policy.model.logits.size).astype(np.float32))
        sleeper = Sleeper(policy, {"lr": 0.05, "beta": 0.3})
        pi = {"walk_main": 0.1, "run_main": 0.3, "check_desk": 0.4, "side_path": 0.2}
        rows = [self.row(c, a, pi) | {"day": 1, "decision": "D1", "outcome_label": "x"} for c, a in (("run_main", -0.3), ("check_desk", 0.1))]
        step = shares_step(sleeper, rows)
        self.assertAlmostEqual(sum(t["share_pg"] + t["share_kl"] for t in step["transitions"]), 1.0, places=5)
        summary = night_summary([step])
        self.assertEqual(summary["top_low_pi_penalty"]["choice"], "run_main")
        self.assertEqual(summary["tripped"], summary["top_low_pi_penalty"]["share_pg"] > 0.5)

    def test_replay_takes_free_days_in_the_window_only(self):
        rows = [{"forced": True, "day": None}] + [{"forced": False, "day": d} for d in range(1, 11)]
        self.assertEqual([r["day"] for r in replay_rows(rows, 10, 5)], [5, 6, 7, 8, 9, 10])


class RunTest(unittest.TestCase):
    def test_every_logged_field_is_there_and_forced_choices_are_never_trained(self):
        with tempfile.TemporaryDirectory() as folder:
            run = quiet_run(folder)
            rows = [json.loads(line) for line in Path(folder, "trajectory.jsonl").read_text().splitlines()]
            nights = [json.loads(line) for line in Path(folder, "sleep.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), len(run.life.records))
            for row in rows:
                for field in FIELDS:
                    self.assertIn(field, row)
                self.assertEqual(row["trained"], not row["forced"])
                self.assertAlmostEqual(row["advantage"], row["reward"] - row["baseline"], places=5)
            for night in nights:
                if night["phase"] == "exploration":
                    self.assertEqual(night["steps"], 0)
                else:
                    for field in SLEEP_FIELDS:
                        self.assertIn(field, night)
            self.assertEqual(sum(n["steps"] for n in nights), run.sleeper.steps_taken)
            # lora_step on a decision is the number of updates made before it
            for row in rows:
                self.assertEqual(row["lora_step"], sum(n["steps"] for n in nights if n["index"] < row["index"]))

    def test_a_killed_run_resumes_to_the_same_life(self):
        with tempfile.TemporaryDirectory() as whole, tempfile.TemporaryDirectory() as split:
            quiet_run(whole)
            first = Run(split, "lived", 0, 6, "table", {"lr": 0.01})
            # stop after the first free night
            while not any(n for n in Path(split, "sleep.jsonl").read_text().splitlines() if '"phase": "free"' in n):
                index = first.life.index
                morning = []
                while first.life.index == index:
                    morning.append(first.decide())
                Path(split, "sleep.jsonl").open("a").write(json.dumps(first.night(morning)) + "\n")
                first._save_checkpoint(len(Path(split, "sleep.jsonl").read_text().splitlines()))
            first.decide()  # a decision after the checkpoint, lost in the "crash"
            resumed = Run(split, "lived", 0, 6, "table", {"lr": 0.01})
            resumed.live()
            a = [json.loads(line) for line in Path(whole, "trajectory.jsonl").read_text().splitlines()]
            b = [json.loads(line) for line in Path(split, "trajectory.jsonl").read_text().splitlines()]
            self.assertEqual([r["choice"] for r in a], [r["choice"] for r in b])
            for x, y in zip(a, b):
                self.assertEqual(x["pi"], y["pi"])

    def test_a_polite_run_gives_memory_back_and_resumes_to_the_same_life(self):
        import sys
        from unittest import mock
        from exp1 import run as runner
        sys.path.insert(0, str(runner.ROOT))
        import ram_share
        # Plenty of room except right after the third night, when it runs short once.
        rooms = iter([50, 50, 50, -10] + [50] * 1000)
        with tempfile.TemporaryDirectory() as whole, tempfile.TemporaryDirectory() as politely, \
                mock.patch.object(ram_share, "room_gb", lambda *a: (next(rooms), [], [])), mock.patch.object(ram_share.time, "sleep", lambda s: None):
            quiet_run(whole)
            make = lambda: Run(politely, "lived", 0, 6, "table", {"lr": 0.01})
            run = runner.polite(make, Path(politely))
            self.assertTrue(run.life.finished)
            a = [json.loads(line)["choice"] for line in Path(whole, "trajectory.jsonl").read_text().splitlines()]
            b = [json.loads(line)["choice"] for line in Path(politely, "trajectory.jsonl").read_text().splitlines()]
            self.assertEqual(a, b)

    def test_probes_are_leak_free_and_cover_both_gate_states(self):
        rows = probes(0)
        self.assertEqual([r["probe"] for r in rows], ["D1", "D2 gate open", "D2 gate closed", "D3"])
        self.assertIn("front_gap", rows[1]["shown"])
        self.assertNotIn("front_gap", rows[2]["shown"])
        for row in rows:
            observe.check(row["observation"])

    def test_the_choice_continuation_is_the_json_the_prompt_asks_for(self):
        self.assertEqual(json.loads(continuation("run_main") + "}"), {"choice": "run_main"})


class PanelTest(unittest.TestCase):
    def test_the_page_data_is_plain_json_and_explains_every_decision(self):
        from exp1 import panel
        with tempfile.TemporaryDirectory() as runs:
            quiet_run(Path(runs, "t"))
            old, panel.RUNS = panel.RUNS, Path(runs)
            try:
                self.assertEqual([r["name"] for r in panel.listing()], ["t"])
                found = json.loads(json.dumps(panel.describe("t"), allow_nan=False))
                arms = json.loads(json.dumps(panel.arms(), allow_nan=False))
            finally:
                panel.RUNS = old
        for row in found["rows"]:
            self.assertIn(row["rare"], (True, False))
            self.assertTrue(0 < row["outcome_p"] <= 1)
        trained = [row for row in found["rows"] if row["trained"]]
        self.assertTrue(all(row.get("pi_after_night") for row in trained))
        for step, where in found["code"].items():
            path, line = where.rsplit(":", 1)
            self.assertTrue(Path(path).exists(), step)
        self.assertIn("lived", arms["arms"])


class BaselinesTest(unittest.TestCase):
    def test_reference_and_direction(self):
        found = baselines.reference(0, "lived", days=6, lives=5)
        self.assertIn("not available", found["do_nothing"])
        for rule in ("random", "always_safe"):
            self.assertIsNotNone(found[rule]["this_seed"]["mean_reward"]["all"])
        self.assertAlmostEqual(found["always_safe"]["this_seed"]["mean_reward"]["all"], 0.15, places=5)
        shares = {"D1": {"n": 4, "options": {"run_main": 0.5, "check_desk": 0.25}},
                  "D2 gate open": {"n": 0, "options": {"front_gap": None, "wait_for_break": None}},
                  "D3": {"n": 4, "options": {"leave_early": 0.0, "stay_and_chat": 0.5}}}
        found = baselines.direction("lived", shares)
        self.assertTrue(found["D1"]["pass"])
        self.assertIsNone(found["D2 gate open"]["pass"])
        self.assertFalse(found["D3"]["pass"])
        neither = {**shares, "D1": {"n": 4, "options": {"run_main": 0.0, "check_desk": 0.0}}}
        self.assertIsNone(baselines.direction("lived", neither)["D1"]["pass"])


if __name__ == "__main__":
    unittest.main()
