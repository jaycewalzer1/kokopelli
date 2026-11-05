"""Items match their sources, prompts obey the rules, and scorers score correctly."""
import random
import statistics
import tempfile
import unittest
from pathlib import Path

import yaml

from benchmarks.core import BANNED_IN_PROMPTS, Parsed, option_order
from benchmarks.holt_laury import HoltLaury
from benchmarks.lotteries import Lotteries
from benchmarks.mid_travel import MidTravel
from benchmarks.mid_travel import generate as travel
from benchmarks.near_errand import NearErrand, StubErrandWorld, held_out_tasks

BOTH_ORDERS = (["safe", "risky"], ["risky", "safe"])


class HoltLauryItems(unittest.TestCase):
    def setUp(self):
        self.hl = HoltLaury()
        self.rows = self.hl.items[0]["rows"]
        self.pay = self.hl.meta["payoffs"]

    def expected_gap(self, row):
        p = row["p_high_tenths"] / 10
        safe = p * self.pay["safe_high"] + (1 - p) * self.pay["safe_low"]
        risky = p * self.pay["risky_high"] + (1 - p) * self.pay["risky_low"]
        return safe - risky

    def test_ten_rows_and_published_payoffs(self):
        self.assertEqual([r["p_high_tenths"] for r in self.rows], list(range(1, 11)))
        self.assertEqual((self.pay["safe_high"], self.pay["safe_low"], self.pay["risky_high"], self.pay["risky_low"]), (2.0, 1.6, 3.85, 0.1))

    def test_first_row_gap_matches_published_table(self):
        self.assertAlmostEqual(self.expected_gap(self.rows[0]), 1.17, delta=0.006)

    def test_risk_neutral_means_four_safe_choices(self):
        self.assertEqual(sum(self.expected_gap(r) > 0 for r in self.rows), 4)

    def test_every_template_states_every_row_for_both_options(self):
        for template in self.hl.templates:
            for order in BOTH_ORDERS:
                prompt = self.hl.build_prompt(self.hl.items[0], template, order)
                for amount in ("$2.00", "$1.60", "$3.85", "$0.10"):
                    self.assertIn(amount, prompt)
                self.assertIn("10", prompt)

    def test_order_really_swaps_the_options(self):
        for template in self.hl.templates:
            first = self.hl.build_prompt(self.hl.items[0], template, BOTH_ORDERS[0])
            second = self.hl.build_prompt(self.hl.items[0], template, BOTH_ORDERS[1])
            self.assertNotEqual(first, second)
            self.assertLess(first.index("$2.00"), first.index("$3.85"))
            self.assertLess(second.index("$3.85"), second.index("$2.00"))


class HoltLauryScore(unittest.TestCase):
    def setUp(self):
        self.hl = HoltLaury()
        self.item = self.hl.items[0]

    def score(self, answer, order=("safe", "risky")):
        return self.hl.score(Parsed(choice=answer, valid=True), self.item, list(order))

    def test_clean_switch(self):
        scored = self.score("AAAABBBBBB")
        self.assertEqual(scored.score, 4)
        self.assertEqual(scored.extras["switch_row"], 5)
        self.assertTrue(scored.extras["consistent"])

    def test_position_is_undone_before_scoring(self):
        """The same preference, shown in the other order, must score the same."""
        self.assertEqual(self.score("BBBBAAAAAA", ("risky", "safe")).score, 4)

    def test_multiple_switching_is_flagged_but_still_counted(self):
        scored = self.score("ABABABBBBB")
        self.assertEqual(scored.score, 3)
        self.assertTrue(scored.extras["multiple_switching"])
        self.assertFalse(scored.extras["consistent"])
        self.assertIsNone(scored.extras["switch_row"])

    def test_going_backwards_is_inconsistent(self):
        scored = self.score("BBBBBAAAAB")
        self.assertTrue(scored.extras["multiple_switching"])

    def test_all_safe_is_dominated(self):
        scored = self.score("AAAAAAAAAA")
        self.assertEqual(scored.score, 10)
        self.assertTrue(scored.extras["dominated"])
        self.assertFalse(scored.extras["consistent"])

    def test_all_risky_is_consistent(self):
        scored = self.score("BBBBBBBBBB")
        self.assertEqual(scored.score, 0)
        self.assertTrue(scored.extras["consistent"])
        self.assertEqual(scored.extras["switch_row"], 1)


class LotteryItems(unittest.TestCase):
    def setUp(self):
        self.lot = Lotteries()

    def test_expected_values_match_the_paper(self):
        ev = lambda option: option["outcome"] * option["p"]
        published = {"hbwe_1": (3.2, 3), "hbwe_2": (0.8, 0.75), "hbwe_3": (-3, -3.2), "hbwe_4": (-3, -3.2), "hbwe_5": (3.2, 3), "hbwe_6": (0.8, 0.75)}
        for item in self.lot.items:
            self.assertAlmostEqual(ev(item["H"]), published[item["id"]][0], places=6)
            self.assertAlmostEqual(ev(item["L"]), published[item["id"]][1], places=6)

    def test_group_gap_matches_the_papers_36_points(self):
        gaps = [abs(i["human_percent_H"]["experience"] - i["human_percent_H"]["description"]) for i in self.lot.items]
        self.assertEqual(sum(gaps) / 6, 36)

    def test_predicted_direction_matches_the_observed_gap(self):
        for item in self.lot.items:
            gap = item["human_percent_H"]["experience"] - item["human_percent_H"]["description"]
            self.assertEqual(item["predicted_by_underweighting"], "H" if gap > 0 else "L", item["id"])

    def test_norms_file_matches_items(self):
        norms = yaml.safe_load((self.lot.folder / "norms.yaml").read_text())
        by_id = {n["id"]: n["mean"] for n in norms["norms"]}
        for group, norm in (("description", "description_group"), ("experience", "experience_group")):
            rates = [i["human_percent_H"][group] if i["predicted_by_underweighting"] == "H" else 100 - i["human_percent_H"][group] for i in self.lot.items]
            self.assertAlmostEqual(statistics.mean(rates) / 100, by_id[norm], places=3)

    def test_templates_state_exact_numbers(self):
        hard = next(i for i in self.lot.items if i["id"] == "hbwe_6")
        self.assertIn("0.025", self.lot.build_prompt(hard, "plain", ["H", "L"]))
        self.assertIn("2.5%", self.lot.build_prompt(hard, "percent", ["H", "L"]))
        self.assertIn("25 of 1000", self.lot.build_prompt(hard, "tickets", ["H", "L"]))
        loss = next(i for i in self.lot.items if i["id"] == "hbwe_3")
        self.assertIn("lose 32 points", self.lot.build_prompt(loss, "percent", ["L", "H"]))

    def test_score_undoes_position(self):
        item = next(i for i in self.lot.items if i["id"] == "hbwe_1")  # Underweighting predicts H.
        self.assertEqual(self.lot.score(Parsed("A", True), item, ["H", "L"]).score, 1)
        self.assertEqual(self.lot.score(Parsed("A", True), item, ["L", "H"]).score, 0)


class PromptRules(unittest.TestCase):
    def test_far_prompts_dont_mention_the_world(self):
        for instrument in (HoltLaury(), Lotteries()):
            self.assertEqual(len(instrument.templates), 3)
            for item in instrument.items:
                for template in instrument.templates:
                    for order in (list(instrument.options), list(reversed(instrument.options))):
                        prompt = instrument.build_prompt(item, template, order)
                        self.assertIsNone(BANNED_IN_PROMPTS.search(prompt), prompt)

    def test_banned_words_are_caught(self):
        for text in ("take the shortcut", "your errand", "in the city", "past experience", "Nell walked"):
            self.assertIsNotNone(BANNED_IN_PROMPTS.search(text))


class RowsPilot(unittest.TestCase):
    def setUp(self):
        from benchmarks.holt_laury_rows import HoltLauryRows
        self.rows = HoltLauryRows()

    def test_ten_separate_items_from_the_same_verified_file(self):
        self.assertEqual(len(self.rows.items), 10)
        self.assertEqual(self.rows.items_path.resolve(), HoltLaury().items_path.resolve())

    def test_prompts_are_one_row_with_no_row_number(self):
        for template in self.rows.templates:
            prompt = self.rows.build_prompt(self.rows.items[4], template, ["safe", "risky"])
            self.assertIsNone(BANNED_IN_PROMPTS.search(prompt))
            self.assertNotIn("Decision 5", prompt)
            self.assertEqual(prompt.count("$3.85"), 1)

    def test_score_undoes_position(self):
        item = self.rows.items[0]
        self.assertEqual(self.rows.score(Parsed("A", True), item, ["safe", "risky"]).score, 1)
        self.assertEqual(self.rows.score(Parsed("A", True), item, ["risky", "safe"]).score, 0)

    def test_not_in_the_pre_registration(self):
        from benchmarks.prereg import CONTRASTS, PREREG
        self.assertNotIn("holt_laury_rows", CONTRASTS.read_text())
        self.assertNotIn("holt_laury_rows", PREREG.read_text())


class OptionOrder(unittest.TestCase):
    def test_same_key_same_order(self):
        self.assertEqual(option_order(("a", "b"), "x", "i", "t", 0, 5), option_order(("a", "b"), "x", "i", "t", 0, 5))

    def test_close_to_half_and_half(self):
        firsts = [option_order(("a", "b"), "x", "i", "t", 0, s)[0] for s in range(2000)]
        self.assertAlmostEqual(firsts.count("a") / 2000, 0.5, delta=0.05)

    def test_varies_with_every_key_part(self):
        base = [option_order(("a", "b"), "x", "i", "t", 0, s) for s in range(64)]
        for other in ([option_order(("a", "b"), "y", "i", "t", 0, s) for s in range(64)],
                      [option_order(("a", "b"), "x", "j", "t", 0, s) for s in range(64)],
                      [option_order(("a", "b"), "x", "i", "u", 0, s) for s in range(64)],
                      [option_order(("a", "b"), "x", "i", "t", 1, s) for s in range(64)]):
            self.assertNotEqual(base, other)

    def test_arm_cant_affect_order(self):
        import inspect
        self.assertNotIn("arm", inspect.signature(option_order).parameters)


class MockModels(unittest.TestCase):
    def test_tilt_moves_holt_laury_the_right_way(self):
        hl, rng = HoltLaury(), random.Random(0)
        def mean_safe(tilt):
            scores = []
            for _ in range(300):
                parsed = hl.parse(hl.mock_answer(hl.items[0], ["safe", "risky"], rng, tilt), hl.items[0], ["safe", "risky"])
                scores.append(hl.score(parsed, hl.items[0], ["safe", "risky"]).score)
            return statistics.mean(scores)
        self.assertGreater(mean_safe(0.0), mean_safe(0.5) + 0.5)
        self.assertGreater(mean_safe(-0.5), mean_safe(0.0) + 0.5)


class Travel(unittest.TestCase):
    def test_specs_are_balanced(self):
        specs = travel.build_specs()
        rare = [s for s in specs if not s["sanity"]]
        self.assertEqual(len(rare), 50)
        self.assertEqual(len(specs), 60)
        for key, levels in (("domain", travel.DOMAINS), ("frame", travel.FRAMES), ("rare_percent", travel.RARE_PERCENT), ("stakes", travel.STAKES)):
            counts = [sum(s[key] == level for s in rare) for level in levels]
            self.assertLessEqual(max(counts) - min(counts), 2, key)

    def test_specs_are_repeatable(self):
        self.assertEqual(travel.build_specs(), travel.build_specs())

    def test_writer_prompt_doesnt_suggest_an_answer(self):
        prompt = travel.writer_prompt(travel.build_specs()[0])
        self.assertIn("Do not say which option is better", prompt)

    def test_bad_generations_are_caught(self):
        spec = next(s for s in travel.build_specs() if not s["sanity"])
        good = {"scenario": "You plan a trip.", "reliable": "Take the usual way.",
                "risky": f"Saves {spec['minutes_saved']} minutes but {spec['rare_percent']}% of the time costs {spec['minutes_lost']} minutes."}
        self.assertEqual(travel.check_generated(spec, good), [])
        self.assertTrue(travel.check_generated(spec, {**good, "risky": "It is faster."}))
        self.assertTrue(travel.check_generated(spec, {**good, "scenario": "Take the shortcut."}))
        self.assertTrue(travel.check_generated(spec, {"scenario": "x"}))

    def test_failures_are_reported_rather_than_dropped(self):
        items, failures = travel.generate(lambda spec: "not json")
        self.assertEqual(items, [])
        self.assertEqual(len(failures), 60)

    def test_real_items_wait_for_approval(self):
        with self.assertRaisesRegex(FileNotFoundError, "approval"):
            MidTravel()

    def test_throwaway_items_run_and_sanity_items_stay_out_of_the_score(self):
        items, failures = travel.generate(travel._mock_write)
        self.assertEqual(failures, [])
        with tempfile.TemporaryDirectory(prefix="evals_") as folder:
            path = Path(folder) / "throwaway.jsonl"
            import json
            path.write_text("\n".join(json.dumps(i) for i in items))
            instrument = MidTravel(items_path=path)
        sanity = next(i for i in instrument.items if i["sanity"])
        self.assertIsNone(instrument.score(Parsed("A", True), sanity, ["risky", "reliable"]).score)
        rare = next(i for i in instrument.items if not i["sanity"])
        self.assertEqual(instrument.score(Parsed("A", True), rare, ["risky", "reliable"]).score, 1)


class NearStub(unittest.TestCase):
    def test_marked_as_stub(self):
        self.assertTrue(NearErrand.stub)
        self.assertFalse(NearErrand().meta["verified"])

    def test_world_is_repeatable_for_a_seed(self):
        world = StubErrandWorld(held_out_tasks()[0])
        self.assertEqual(world.walk("side_path", 3), world.walk("side_path", 3))

    def test_reliable_route_never_blocks(self):
        world = StubErrandWorld(held_out_tasks()[0])
        self.assertTrue(all(not world.walk("main_road", i)[1] for i in range(50)))

    def test_odds_are_about_right(self):
        world = StubErrandWorld(held_out_tasks()[2])
        self.assertAlmostEqual(sum(world.walk("alley", i)[1] for i in range(4000)) / 4000, 0.2, delta=0.03)


if __name__ == "__main__":
    unittest.main()
