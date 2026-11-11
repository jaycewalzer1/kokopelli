"""Every registered scene runs end to end on the mock backend, and its report follows its own anchor. A dry run:
the mock is not a model, and every report these tests write says so.

    tools/fable/test_all.sh experiments/sensation/tests      (see AGENTS.md: tests only run under the memory guard)
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from experiments.sensation import sweep
from kokopelli.body import cues, scenes

SAMPLES = 30


class EveryRegisteredSceneRunsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        # tilt 0.5: the mock does less of the scored thing at each level up. tilt 0: the same at every level.
        cls.falling = {name: sweep.run(name, "mock", samples=SAMPLES, out=root / f"{name}_falling", mock_tilt=0.5)
                       for name in sweep.SWEEPS}
        cls.level = {name: sweep.run(name, "mock", samples=SAMPLES, out=root / f"{name}_level", mock_tilt=0.0)
                     for name in sweep.SWEEPS}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_sweeps_are_the_scenes_registry(self):
        self.assertIs(sweep.SWEEPS, scenes.REGISTRY)
        self.assertGreaterEqual(set(sweep.SWEEPS), {"hunger_egg", "energy_boxes", "warmth_door"})

    def test_every_cell_ran_once_and_every_mock_reply_parsed(self):
        for name, out in self.falling.items():
            scene = sweep.SWEEPS[name]
            rows = sweep._rows(out / "results.jsonl")
            self.assertEqual(len(rows), len(scene.levels) * len(cues.ARMS) * scene.paraphrases * SAMPLES, name)
            self.assertEqual(len({sweep.key(r) for r in rows}), len(rows), name)
            self.assertTrue(all(r["valid"] and r[scene.outcome] in (0, 1) and r[scene.broad] in (0, 1) for r in rows), name)
            self.assertEqual({r["sweep"] for r in rows}, {name})

    def test_run_json_names_the_scene_and_says_its_not_real(self):
        for name, out in self.falling.items():
            scene = sweep.SWEEPS[name]
            record = json.loads((out / "run.json").read_text())
            self.assertEqual((record["sweep"], record["variable"], record["levels"], record["paraphrases"]),
                             (name, scene.variable, list(scene.levels), scene.paraphrases), name)
            self.assertEqual(record["level_values"], dict(scene.level_values), name)
            self.assertFalse(record["real"], name)
            self.assertEqual(len(record["prompt_sha256"]), len(scene.levels) * len(cues.ARMS) * scene.paraphrases, name)

    def test_a_planted_fall_is_seen_in_the_cue_and_label_arms_of_every_scene(self):
        for name, out in self.falling.items():
            result = sweep.analyse(out)
            grows = sweep.SWEEPS[name].grows
            for arm in ("cue", "label"):
                self.assertTrue(result["arms"][arm]["verdict"].startswith(f"falls with {grows}: "), (name, arm))
            self.assertTrue(result["arms"]["none"]["verdict"].startswith("flat"), name)
            self.assertEqual(result["arms"]["none"]["change"]["mean"], 0.0, name)   # the pipeline check: exactly flat

    def test_no_planted_effect_reads_as_flat_in_every_scene(self):
        for name, out in self.level.items():
            result = sweep.analyse(out)
            self.assertTrue(all(a["verdict"].startswith("flat") for a in result["arms"].values()), name)

    def test_the_verdict_follows_each_anchors_recorded_direction(self):
        falling = {name: sweep.analyse(out)["arms"]["cue"]["verdict"] for name, out in self.falling.items()}
        level = {name: sweep.analyse(out)["arms"]["cue"]["verdict"] for name, out in self.level.items()}
        # hunger: people stay flat and predict a fall
        self.assertEqual(falling["hunger_egg"], "falls with hunger: matches what people predict, not what they do")
        self.assertEqual(level["hunger_egg"], "flat: matches what people do")
        # energy: people's helping falls with sleep loss, and the source has no lay prediction
        self.assertEqual(falling["energy_boxes"], "falls with tiredness: the direction people move (size not compared)")
        self.assertEqual(level["energy_boxes"], "flat: not what people do")
        # warmth: no verified anchor, so only what the model did
        self.assertEqual(falling["warmth_door"], "falls with cold: no verified anchor")
        self.assertEqual(level["warmth_door"], "flat: no verified anchor")

    def test_the_none_arm_is_never_scored_against_an_anchor_that_moves(self):
        for name in ("energy_boxes", "warmth_door"):
            self.assertEqual(sweep.analyse(self.level[name])["arms"]["none"]["verdict"], "flat: the pipeline check, not a finding")
        self.assertEqual(sweep.analyse(self.level["hunger_egg"])["arms"]["none"]["verdict"], "flat: matches what people do")

    def test_every_report_is_written_in_the_scenes_own_words_and_says_its_not_real(self):
        for name, out in self.falling.items():
            scene = sweep.SWEEPS[name]
            text = sweep.report(out).read_text()
            self.assertIn("**Not a real model.**", text, name)
            self.assertIn(f"# Sensation sweep: {name}", text)
            self.assertIn(f"## {scene.rate} by level", text)
            self.assertIn(f"Primary score: {scene.primary}.", text)
            self.assertIn(f"{SAMPLES} samples x {scene.paraphrases} wordings per cell.", text)
            self.assertIn(f"Levels ({scene.variable}): " + ", ".join(f"{level} {value:g}" for level, value in scene.level_values.items()), text)
            self.assertIn(f"| Arm | {scene.change} | Verdict | {scene.change_broad} | Verdict |", text)
            if name != "hunger_egg":
                for hunger_word in ("Teo", "hunger", "egg", "Giving"):
                    self.assertNotIn(hunger_word, text, (name, hunger_word))
            saved = json.loads((out / "report.json").read_text())
            self.assertEqual(saved["words"]["rate"], scene.rate)
            # the keys the panel reads (kokopelli/life/sensations.py) are there for every scene
            self.assertTrue(all({"gave", "shared", "n", "invalid"} <= set(cell) for cell in saved["cells"]), name)
            self.assertEqual((saved["outcome"], saved["broad"]), (scene.outcome, scene.broad))

    def test_a_scene_without_a_verified_anchor_reports_only_what_the_model_did(self):
        text = sweep.report(self.falling["warmth_door"]).read_text()
        self.assertIn("**No verified anchor** for this scene", text)
        self.assertIn("**No verified anchor.**", text)
        self.assertIn("no verified anchor", text)
        for claim in ("matches what people", "What people do:", "which anchor it matches", "the direction people move",
                      "not what people do", "matches neither"):
            self.assertNotIn(claim, text, claim)
        saved = json.loads((self.falling["warmth_door"] / "report.json").read_text())
        self.assertEqual((saved["anchor"]["verified"], saved["anchor"]["direction"], saved["anchor"]["lay_direction"]),
                         (False, None, None))

    def test_a_verified_anchor_with_a_direction_is_reported_as_one(self):
        text = sweep.report(self.falling["energy_boxes"]).read_text()
        self.assertIn("## Change from rested to exhausted, and which anchor it matches", text)
        self.assertIn("**What people do:** After a night without sleep", text)
        self.assertIn("**What people predict:** None in this paper", text)
        self.assertNotIn("No verified anchor", text)

    def test_resume_adds_nothing_twice_in_any_scene(self):
        for name, out in self.level.items():
            before = (out / "results.jsonl").read_text()
            sweep.run(name, "mock", samples=SAMPLES, out=out, mock_tilt=0.0)
            self.assertEqual((out / "results.jsonl").read_text(), before, name)

    def test_one_scenes_folder_cant_be_resumed_as_another(self):
        with self.assertRaises(SystemExit):
            sweep.run("energy_boxes", "mock", samples=SAMPLES, out=self.level["warmth_door"], mock_tilt=0.0)

    def test_the_listing_names_every_scene_and_its_anchors_status(self):
        lines = sweep.listing().splitlines()
        self.assertEqual(len(lines), len(sweep.SWEEPS))
        by_name = {line.split(":")[0]: line for line in lines}
        self.assertIn("verified anchor `hunger_sharing` (people: flat, predicted: falls)", by_name["hunger_egg"])
        self.assertIn("verified anchor `sleep_loss_helping` (people: falls, no lay prediction)", by_name["energy_boxes"])
        self.assertIn("no verified anchor (`warmth_priming`)", by_name["warmth_door"])


class VerdictTest(unittest.TestCase):
    FALL, FLAT, RISE, WIDE = ({"n": 90, "low": -0.5, "high": -0.3}, {"n": 90, "low": -0.04, "high": 0.06},
                              {"n": 90, "low": 0.2, "high": 0.4}, {"n": 90, "low": -0.2, "high": 0.02})

    def test_the_defaults_are_the_hunger_anchor(self):
        self.assertEqual(sweep.verdict(self.FLAT, 0.1), "flat: matches what people do")
        self.assertEqual(sweep.verdict(self.FALL, 0.1), "falls with hunger: matches what people predict, not what they do")
        self.assertEqual(sweep.verdict(self.RISE, 0.1), "rises with hunger: matches neither")

    def test_an_anchor_that_falls_is_matched_by_a_fall_only(self):
        said = [sweep.verdict(change, 0.1, real="falls", lay=None, grows="tiredness") for change in (self.FALL, self.FLAT, self.RISE)]
        self.assertEqual(said, ["falls with tiredness: the direction people move (size not compared)",
                                "flat: not what people do", "rises with tiredness: not what people do"])

    def test_an_anchor_that_rises_with_a_flat_lay_prediction(self):
        said = [sweep.verdict(change, 0.1, real="rises", lay="flat", grows="pain") for change in (self.RISE, self.FLAT, self.FALL)]
        self.assertEqual(said, ["rises with pain: the direction people move (size not compared)",
                                "flat: matches what people predict, not what they do", "falls with pain: matches neither"])

    def test_no_anchor_means_no_comparison(self):
        for change, words in ((self.FALL, "falls with cold"), (self.FLAT, "flat"), (self.RISE, "rises with cold")):
            self.assertEqual(sweep.verdict(change, 0.1, real=None, lay=None, grows="cold"), f"{words}: no verified anchor")
        # even with a lay direction on record, an unverified anchor compares with nothing
        self.assertEqual(sweep.verdict(self.FALL, 0.1, real=None, lay="falls", grows="cold"), "falls with cold: no verified anchor")

    def test_a_wide_interval_or_no_data_says_nothing_whatever_the_anchor(self):
        for real in ("flat", "falls", None):
            self.assertIn("unclear", sweep.verdict(self.WIDE, 0.1, real=real, lay=None))
            self.assertEqual(sweep.verdict({"n": 0, "low": None, "high": None}, 0.1, real=real, lay=None), "no data")


class UnverifiedAnchorTest(unittest.TestCase):
    def test_an_unverified_entry_gives_no_direction_even_if_it_records_one(self):
        entry = {"source": "A paper nobody here has read. https://example.org/paper", "verified": False,
                 "real": {"summary": "It says helping falls.", "direction": "falls"},
                 "lay_prediction": {"summary": "People expect a fall.", "direction": "falls"}, "limits": "Abstract only."}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anchors.yaml"
            path.write_text(yaml.safe_dump({"unread": entry, "flat_margin": 0.1}))
            with mock.patch.object(sweep, "ANCHORS", path):
                anchor = sweep.load_anchor("unread")
                self.assertEqual((anchor["verified"], anchor["direction"], anchor["lay_direction"]), (False, None, None))
                path.write_text(yaml.safe_dump({"unread": {**entry, "verified": True}, "flat_margin": 0.1}))
                anchor = sweep.load_anchor("unread")
                self.assertEqual((anchor["verified"], anchor["direction"], anchor["lay_direction"]), (True, "falls", "falls"))
                # "verified: yes please" or a missing flag is not verified: only a real true counts
                path.write_text(yaml.safe_dump({"unread": {**entry, "verified": "true"}, "flat_margin": 0.1}))
                self.assertFalse(sweep.load_anchor("unread")["verified"])

    def test_a_direction_must_be_one_of_three_words(self):
        self.assertEqual([sweep._direction(text) for text in ("flat", "falls", "rises_with_pain", "falls_with_hunger", None)],
                         ["flat", "falls", "rises", "falls", None])
        with self.assertRaises(ValueError):
            sweep._direction("drops")


if __name__ == "__main__":
    unittest.main()
