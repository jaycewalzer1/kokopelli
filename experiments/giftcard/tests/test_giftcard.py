"""The gift-card scene and its runner, on canned replies. Seconds, any machine.

    tools/fable/test_all.sh experiments/giftcard/tests      (see AGENTS.md: tests only run under the memory guard)
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from experiments.giftcard import run, scene


def reply(action):
    return json.dumps({"thought": "x", "action": action})


class SceneTest(unittest.TestCase):
    def test_ages_differ_only_in_the_number(self):
        eight, sixteen = scene.prompt("record_8", 5).splitlines(), scene.prompt("record_16", 5).splitlines()
        changed = [(a, b) for a, b in zip(eight, sixteen, strict=True) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0].replace("who is 8", "who is 16"), changed[0][1])

    def test_the_versions_differ_only_in_what_owning_up_costs(self):
        record, none = scene.prompt("record_12", 2).splitlines(), scene.prompt("none_12", 2).splitlines()
        changed = [a for a, b in zip(record, none, strict=True) if a != b]
        self.assertEqual(changed, [scene.COST["record"]])
        self.assertNotIn("record until", scene.prompt("none_12", 2))

    def test_sam_has_no_pronouns(self):
        text = scene.WHO + scene.prompt("record_10", 0)
        self.assertFalse(re.search(r"\b(he|she|him|her|his|hers)\b", text, re.IGNORECASE))

    def test_every_action_is_listed_once_in_an_order_the_seed_sets(self):
        orders = {scene.action_order(seed) for seed in range(20)}
        self.assertEqual(len({order[0] for order in orders}), len(scene.ACTION_TYPES))
        text = scene.actions(4)
        self.assertTrue(all(text.count(f'"type": "{kind}"') == 1 for kind in scene.ACTION_TYPES))

    def test_each_action_reads_as_its_outcome(self):
        for kind, outcome in scene.READS.items():
            self.assertEqual(scene.score(reply({"type": kind, "text": "x"}))["outcome"], outcome)
        self.assertEqual(set(scene.READS.values()) | {"invalid"}, set(scene.OUTCOMES))
        self.assertEqual(scene.score('{"thought": "x", "action": "pay", "text": "y"}')["outcome"], "paid")

    def test_a_refusal_or_an_unknown_action_is_invalid(self):
        for raw in ("I'd rather not choose.", None, reply({"type": "call_police"}), "{not json}"):
            self.assertEqual(scene.score(raw)["outcome"], "invalid", raw)

    def test_an_unknown_scene_is_refused(self):
        for name in ("record_7", "record_17", "maybe_10", "record"):
            with self.assertRaises(ValueError):
                scene.prompt(name, 0)


class RunTest(unittest.TestCase):
    def test_a_mock_run_writes_every_decision_and_a_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "mock"
            summary = run.run(out, seeds=4, mock=True, log=lambda line: None)
            rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 4 * len(scene.SCENES))
            self.assertEqual(summary["record_8"], {"returned_with_sam": 1, "returned_alone": 1, "talked": 1, "invalid": 1})
            record = json.loads((out / "run.json").read_text())
            self.assertEqual((record["model"], record["system"]), ("mock", scene.WHO))
            with self.assertRaises(SystemExit):
                run.run(out, seeds=1, mock=True, log=lambda line: None)


if __name__ == "__main__":
    unittest.main()
