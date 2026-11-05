"""Stats on known answers, then the whole pipeline on planted effects and on no effect."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from benchmarks import report, stats
from benchmarks.run import main as run_main, read_results


class Holm(unittest.TestCase):
    def test_known_example(self):
        self.assertEqual([round(p, 3) for p in stats.holm([0.01, 0.04, 0.03, 0.005])], [0.03, 0.06, 0.06, 0.02])

    def test_never_exceeds_one_and_handles_nan(self):
        adjusted = stats.holm([0.9, float("nan"), 0.8])
        self.assertEqual(adjusted[0], 1.0)
        self.assertNotEqual(adjusted[1], adjusted[1])


class Bootstrap(unittest.TestCase):
    def test_interval_contains_mean_and_narrows_with_n(self):
        rng = np.random.default_rng(0)
        small, large = rng.normal(5, 2, 50), rng.normal(5, 2, 5000)
        low_s, high_s = stats.bootstrap_ci(small)
        low_l, high_l = stats.bootstrap_ci(large)
        self.assertLess(low_s, small.mean())
        self.assertGreater(high_s, small.mean())
        self.assertLess(high_l - low_l, high_s - low_s)

    def test_covers_truth_about_95_percent(self):
        rng = np.random.default_rng(1)
        hits = 0
        for i in range(200):
            low, high = stats.bootstrap_ci(rng.normal(0, 1, 100), n_boot=500, seed=i)
            hits += low <= 0 <= high
        self.assertGreater(hits / 200, 0.90)
        self.assertLess(hits / 200, 0.99)

    def test_empty(self):
        self.assertTrue(np.isnan(stats.bootstrap_ci([])[0]))


class Permutation(unittest.TestCase):
    def test_finds_a_clear_gap(self):
        rng = np.random.default_rng(0)
        self.assertLess(stats.permutation_test(rng.normal(1, 1, 100), rng.normal(0, 1, 100), n_perm=999), 0.01)

    def test_false_alarms_near_alpha(self):
        rng = np.random.default_rng(2)
        ps = [stats.permutation_test(rng.normal(0, 1, 40), rng.normal(0, 1, 40), n_perm=199, seed=i) for i in range(200)]
        self.assertLess(np.mean(np.array(ps) < 0.05), 0.10)

    def test_stratifying_removes_item_difficulty(self):
        """Arm a answers mostly the easy item. Unstratified, that looks like an arm effect. Stratified, it doesn't."""
        rng = np.random.default_rng(3)
        a = np.concatenate([rng.normal(10, 1, 90), rng.normal(0, 1, 10)])
        b = np.concatenate([rng.normal(10, 1, 10), rng.normal(0, 1, 90)])
        a_labels, b_labels = np.array(["easy"] * 90 + ["hard"] * 10), np.array(["easy"] * 10 + ["hard"] * 90)
        self.assertLess(stats.permutation_test(a, b, n_perm=499), 0.01)
        self.assertGreater(stats.permutation_test(a, b, a_labels, b_labels, n_perm=499), 0.01)

    def test_p_is_never_zero(self):
        self.assertGreater(stats.permutation_test(np.ones(5), np.zeros(5), n_perm=10), 0)


class EffectSize(unittest.TestCase):
    def test_one_sd_gap(self):
        rng = np.random.default_rng(0)
        self.assertAlmostEqual(stats.cohens_d(rng.normal(1, 1, 5000), rng.normal(0, 1, 5000)), 1.0, delta=0.08)


def contrast_config(alpha=0.05):
    return {"settings": {"alpha": alpha, "min_seeds_right": 3, "max_seeds_wrong": 0}, "contrasts": [
        {"id": "hl", "kind": "difference", "instrument": "holt_laury", "a": "fake_lived", "b": "fake_null", "direction": "negative"},
        {"id": "lot", "kind": "difference", "instrument": "lotteries", "a": "fake_lived", "b": "fake_null", "direction": "positive"},
        {"id": "hl2", "kind": "difference", "instrument": "holt_laury", "a": "fake_flipped", "b": "fake_lived", "direction": "positive"},
        {"id": "near", "kind": "equivalence", "instrument": "holt_laury", "a": "fake_null", "b": "fake_base", "margin": 0.5},
    ]}


class PlantedEffects(unittest.TestCase):
    """The phase 3 gate: a planted effect is detected, no effect isn't. These go through the full runner."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="evals_")
        cls.out = Path(cls.folder.name) / "planted"
        code = run_main(["--arms", "fake_base", "fake_lived", "fake_flipped", "fake_null", "--instruments", "holt_laury", "lotteries",
                         "--samples", "40", "--seeds", "0", "1", "2", "--out", str(cls.out)])
        assert code == 0
        cls.rows = read_results(cls.out)
        cls.frame = stats.to_frame(cls.rows)
        cls.table = stats.evaluate_contrasts(cls.frame, contrast_config(), n_perm=999).set_index("id")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_planted_effect_found_on_both_instruments(self):
        self.assertEqual(self.table.loc["hl", "status"], "pass")
        self.assertEqual(self.table.loc["lot", "status"], "pass")
        self.assertLess(self.table.loc["hl", "p_holm"], 0.05)

    def test_opposite_adapter_moves_opposite(self):
        self.assertEqual(self.table.loc["hl2", "status"], "pass")
        self.assertGreater(self.table.loc["hl2", "difference"], 0)

    def test_no_effect_isnt_detected(self):
        """fake_null and fake_base have no tilt, so a test between them must not be significant."""
        config = {"settings": contrast_config()["settings"], "contrasts": [
            {"id": "null_hl", "kind": "difference", "instrument": "holt_laury", "a": "fake_null", "b": "fake_base", "direction": "negative"},
            {"id": "null_lot", "kind": "difference", "instrument": "lotteries", "a": "fake_null", "b": "fake_base", "direction": "positive"},
        ]}
        table = stats.evaluate_contrasts(self.frame, config, n_perm=999)
        for _, row in table.iterrows():
            self.assertGreaterEqual(row["p_holm"], 0.05, row["id"])
            self.assertNotEqual(row["status"], "pass")

    def test_equivalence_needs_the_whole_interval_inside_the_margin(self):
        row = self.table.loc["near"]
        inside = -0.5 <= row["ci_low"] and row["ci_high"] <= 0.5
        self.assertEqual(row["status"] == "pass", inside)

    def test_wrong_direction_fails_even_when_significant(self):
        config = {"settings": contrast_config()["settings"], "contrasts": [
            {"id": "wrong", "kind": "difference", "instrument": "holt_laury", "a": "fake_lived", "b": "fake_null", "direction": "positive"}]}
        self.assertEqual(stats.evaluate_contrasts(self.frame, config, n_perm=199).iloc[0]["status"], "fail: significant, wrong direction")

    def test_too_few_seeds_fails(self):
        two_seeds = self.frame[self.frame.seed < 2]
        table = stats.evaluate_contrasts(two_seeds, contrast_config(), n_perm=199).set_index("id")
        self.assertEqual(table.loc["hl", "status"], "fail: too few seeds agree")

    def test_a_seed_going_the_wrong_way_fails(self):
        flipped = self.frame.copy()
        mask = (flipped.seed == 2) & (flipped.arm == "fake_lived") & (flipped.instrument == "holt_laury")
        flipped.loc[mask, "score"] = 10.0
        config = {"settings": {"alpha": 0.05, "min_seeds_right": 2, "max_seeds_wrong": 0}, "contrasts": contrast_config()["contrasts"][:1]}
        self.assertNotEqual(stats.evaluate_contrasts(flipped, config, n_perm=199).iloc[0]["status"], "pass")

    def test_missing_arm_is_not_run_rather_than_failed(self):
        config = {"settings": contrast_config()["settings"], "contrasts": [
            {"id": "x", "kind": "difference", "instrument": "holt_laury", "a": "lived", "b": "described", "direction": "negative"}]}
        self.assertEqual(stats.evaluate_contrasts(self.frame, config, n_perm=9).iloc[0]["status"], "not run")

    def test_report_has_every_section(self):
        data = report.collect(self.out)
        markdown, page = report.to_markdown(data), report.to_html(data)
        for text in ("Per template", "Parse failures", "Holt-Laury consistency", "Human norms", "Mock run"):
            self.assertIn(text, markdown)
        for text in ("Parse failures", "Human norms", "Per template", "Bootstrap".lower()):
            self.assertIn(text, page)

    def test_parse_failures_are_reported(self):
        table = stats.parse_failures(self.rows)
        self.assertGreater(table.retried.sum(), 0)
        self.assertEqual(table.n.sum(), len(self.rows))


class Guardrail(unittest.TestCase):
    def frame(self, shift):
        rng = np.random.default_rng(0)
        rows = []
        for arm, rate in (("base", 70), ("lived", 70 + shift)):
            for item in range(20000):
                rows.append({"arm": arm, "instrument": "mmlu", "item_id": f"i{item % 50}", "template": "harness", "seed": 0, "sample": item, "score": float(rng.random() * 100 < rate) * 100})
        return pd.DataFrame(rows)

    CONFIG = {"settings": {"alpha": 0.05, "min_seeds_right": 3, "max_seeds_wrong": 0}, "contrasts": [
        {"id": "g", "kind": "guardrail", "instrument": "mmlu", "a": "lived", "b": "base", "margin": 1.0}]}

    def test_big_move_fails(self):
        self.assertEqual(stats.evaluate_contrasts(self.frame(5), self.CONFIG).iloc[0]["status"], "fail: moved more than margin")

    def test_no_move_passes(self):
        self.assertTrue(stats.evaluate_contrasts(self.frame(0), self.CONFIG).iloc[0]["status"].startswith("pass"))


class OneSamplePerQuestion(unittest.TestCase):
    """Guardrails have one sample per question. Redrawing inside a question once gave a zero-width interval."""

    def frame(self, shared=True):
        rng = np.random.default_rng(0)
        easy = rng.random(400) < 0.7
        rows = []
        for arm in ("base", "lived"):
            answers = easy ^ (rng.random(400) < 0.05) if shared else rng.random(400) < 0.7
            rows += [{"arm": arm, "instrument": "mmlu", "item_id": f"q{i}", "template": "harness", "seed": 0, "sample": 0, "score": float(answers[i]) * 100} for i in range(400)]
        return pd.DataFrame(rows)

    def width(self, frame):
        low, high = stats.difference_ci(frame[frame.arm == "lived"], frame[frame.arm == "base"])
        return high - low

    def test_arm_interval_has_real_width(self):
        row = stats.arm_table(self.frame()).iloc[0]
        self.assertGreater(row.ci_high - row.ci_low, 5)

    def test_difference_interval_has_real_width(self):
        self.assertGreater(self.width(self.frame()), 1)

    def test_pairing_narrows_the_interval(self):
        self.assertLess(self.width(self.frame(shared=True)), self.width(self.frame(shared=False)))

    def test_wide_interval_is_labeled_point_estimate_only(self):
        config = {"settings": {"alpha": 0.05, "min_seeds_right": 3, "max_seeds_wrong": 0}, "contrasts": [
            {"id": "g", "kind": "guardrail", "instrument": "mmlu", "a": "lived", "b": "base", "margin": 100.0}]}
        frame = self.frame()
        wide_margin = stats.evaluate_contrasts(frame, config).iloc[0]
        self.assertEqual(wide_margin["status"], "pass")
        config["contrasts"][0]["margin"] = abs(wide_margin["difference"]) + 0.01
        self.assertIn("point estimate only", stats.evaluate_contrasts(frame, config).iloc[0]["status"])


class RealContrastsFile(unittest.TestCase):
    def test_parses_and_names_known_things(self):
        config = yaml.safe_load((Path(stats.__file__).parent / "configs" / "contrasts.yaml").read_text())
        self.assertEqual(config["settings"]["min_seeds_right"], 3)
        kinds = {c["kind"] for c in config["contrasts"]}
        self.assertEqual(kinds, {"difference", "equivalence", "guardrail"})


if __name__ == "__main__":
    unittest.main()
