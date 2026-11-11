"""anchors.yaml keeps its own rules: every scene has an entry, every entry says honestly whether it was verified, and
nothing unverified can be read as "what people do".

    tools/fable/test_all.sh experiments/sensation/tests      (see AGENTS.md: tests only run under the memory guard)
"""
import unittest

import yaml

from experiments.sensation import sweep

ANCHORS = yaml.safe_load(sweep.ANCHORS.read_text())
ENTRIES = {key: entry for key, entry in ANCHORS.items() if isinstance(entry, dict)}


class AnchorsFileTest(unittest.TestCase):
    def test_every_scene_has_an_entry_that_lists_it(self):
        for name, scene in sweep.SWEEPS.items():
            self.assertIn(scene.anchor, ENTRIES, name)
            self.assertIn(name, ENTRIES[scene.anchor]["used_by"], name)

    def test_every_entry_is_used_by_a_registered_scene(self):
        for key, entry in ENTRIES.items():
            for name in entry["used_by"]:
                self.assertEqual(sweep.SWEEPS[name].anchor, key, (key, name))

    def test_every_entry_has_the_fields_a_report_prints(self):
        for key, entry in ENTRIES.items():
            self.assertIsInstance(entry["verified"], bool, key)
            self.assertIn("https://", entry["source"], key)
            for text in (entry["real"]["summary"], entry["lay_prediction"]["summary"], entry["limits"]):
                self.assertGreater(len(text.strip()), 40, key)
            for part in ("real", "lay_prediction"):
                sweep._direction(entry[part].get("direction"))   # raises on anything but flat, falls, rises or null

    def test_a_verified_entry_says_what_people_do_and_an_unverified_one_says_why_not(self):
        for key, entry in ENTRIES.items():
            if entry["verified"]:
                self.assertIsNotNone(entry["real"]["direction"], key)
            else:
                self.assertGreater(len(entry["why_unverified"].strip()), 40, key)
                self.assertIsNone(entry["real"]["direction"], key)
                self.assertIsNone(entry["lay_prediction"]["direction"], key)

    def test_the_entries_added_with_the_scenes_registry_say_which_text_was_read(self):
        for key in ("sleep_loss_helping", "warmth_priming", "hunger_food_choice"):
            self.assertIn("https://", " ".join(ENTRIES[key]["read"]), key)
            self.assertTrue(all(isinstance(line, str) for line in ENTRIES[key]["read"]), key)
        self.assertNotIn("read", ENTRIES["pain_patience"])   # nothing was read for it, and it says so
        self.assertIn("NOT read", ENTRIES["pain_patience"]["source"])

    def test_tonights_statuses(self):
        self.assertEqual({key: entry["verified"] for key, entry in ENTRIES.items()},
                         {"hunger_sharing": True, "sleep_loss_helping": True, "warmth_priming": False,
                          "hunger_food_choice": True, "pain_patience": False})
        self.assertEqual(sweep.load_anchor("sleep_loss_helping")["direction"], "falls")
        self.assertIsNone(sweep.load_anchor("sleep_loss_helping")["lay_direction"])
        self.assertEqual(sweep.load_anchor("hunger_food_choice")["direction"], "rises")
        self.assertEqual(ANCHORS["flat_margin"], 0.10)


if __name__ == "__main__":
    unittest.main()
