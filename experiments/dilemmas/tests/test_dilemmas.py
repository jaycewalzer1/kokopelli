"""The dilemma set and its prompts. Seconds, any machine.

    tools/fable/test_all.sh experiments/dilemmas/tests      (see AGENTS.md: tests only run under the memory guard)
"""
import json
import unittest
from collections import Counter

from experiments.dilemmas import dilemmas


class SetTest(unittest.TestCase):
    def test_a_hundred_with_every_field_and_ten_per_category(self):
        self.assertEqual(len(dilemmas.DILEMMAS), 100)
        for item in dilemmas.DILEMMAS.values():
            self.assertFalse(set(dilemmas.FIELDS) - set(item), item["id"])
            self.assertTrue(item["id"].startswith(item["category"] + "-"), item["id"])
            self.assertIn(item["film"], ("stage", "text"))
        counts = Counter(item["category"] for item in dilemmas.DILEMMAS.values())
        self.assertEqual(set(counts), set(dilemmas.CATEGORIES))
        self.assertEqual(set(counts.values()), {10})

    def test_actions_are_unique_and_there_is_a_real_choice(self):
        for item in dilemmas.DILEMMAS.values():
            kinds = [action["type"] for action in item["actions"]]
            self.assertEqual(len(kinds), len(set(kinds)), item["id"])
            self.assertGreaterEqual(len(kinds), 2, item["id"])

    def test_the_versions_differ_only_in_the_pressure_line(self):
        for key, item in dilemmas.DILEMMAS.items():
            pressure = dilemmas.prompt(f"{key}:pressure", 3).split("\n\n")
            control = dilemmas.prompt(f"{key}:control", 3).split("\n\n")
            changed = [(a, b) for a, b in zip(pressure, control, strict=True) if a != b]
            self.assertEqual(changed, [(item["pressure"], item["control"])], key)


class PromptTest(unittest.TestCase):
    def test_every_action_listed_once_in_a_seeded_order(self):
        item = dilemmas.DILEMMAS["force-intruder"]
        text = dilemmas.actions(item, 7)
        self.assertTrue(all(text.count(f'"type": "{a["type"]}"') == 1 for a in item["actions"]))
        self.assertGreater(len({dilemmas.action_order(item, seed) for seed in range(20)}), 1)

    def test_a_reply_is_read_as_its_action_and_anything_else_is_invalid(self):
        good = json.dumps({"thought": "x", "action": {"type": "call", "text": "hello"}})
        self.assertEqual(dilemmas.score("force-intruder:pressure", good)["outcome"], "call")
        self.assertEqual(dilemmas.score("force-intruder:pressure", "I won't choose.")["outcome"], "invalid")
        wrong = json.dumps({"thought": "x", "action": {"type": "pull"}})
        self.assertEqual(dilemmas.score("force-intruder:pressure", wrong)["outcome"], "invalid")

    def test_names_cover_both_versions(self):
        self.assertEqual(len(dilemmas.names()), 200)
        self.assertEqual(len(dilemmas.names("machine")), 20)
        with self.assertRaises(ValueError):
            dilemmas.split("force-intruder:both")
