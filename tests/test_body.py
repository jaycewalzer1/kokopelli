"""The body, its cues and the egg scene. No model, no sim: everything here is a pure function.

    .venv/bin/python -m unittest tests.test_body      (through ops/memguard.py, see AGENTS.md)
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from body import cues, egg, state  # noqa: E402
from body.state import Body, CantDoThat  # noqa: E402

NUMBER = re.compile(r"\d")


class CueTest(unittest.TestCase):
    def test_a_body_in_range_is_quiet_in_every_arm(self):
        quiet = {"food": 60, "energy": 60, "warmth": 60}
        for arm in cues.ARMS:
            self.assertEqual(cues.sensations(quiet, arm), [])
            self.assertEqual(cues.block(quiet, arm), "")

    def test_each_level_lands_in_its_own_band(self):
        self.assertEqual({level: cues.band("food", food) for level, food in egg.LEVELS.items()},
                         {"full": "full", "half": "mild", "starving": "severe"})

    def test_the_cue_never_shows_a_number_or_names_the_state(self):
        for bands in cues.CUES.values():
            for options in bands.values():
                for line in options:
                    self.assertIsNone(NUMBER.search(line), line)
                    self.assertNotRegex(line.lower(), r"\b(hungry|hunger|starving|tired|exhausted|freezing)\b", line)

    def test_label_says_the_state_plainly_and_none_says_nothing(self):
        starving = {"food": 8, "energy": 60, "warmth": 60}
        self.assertEqual(cues.sensations(starving, "label"), ["You are extremely hungry."])
        self.assertEqual(cues.sensations(starving, "none"), [])
        self.assertEqual(len(cues.sensations(starving, "cue")), 1)

    def test_paraphrases_differ_and_are_stable(self):
        starving = {"food": 8, "energy": 60, "warmth": 60}
        lines = {cues.sensations(starving, "cue", paraphrase=k)[0] for k in range(3)}
        self.assertEqual(len(lines), 3)
        self.assertEqual(cues.sensations(starving, "cue", paraphrase=1), cues.sensations(starving, "cue", paraphrase=1))

    def test_mild_signals_come_and_go_but_strong_ones_stay(self):
        mild = {"food": 32, "energy": 60, "warmth": 60}
        severe = {"food": 8, "energy": 60, "warmth": 60}
        shown = [bool(cues.sensations(mild, "cue", tick=t)) for t in range(40)]
        self.assertTrue(any(shown) and not all(shown))
        self.assertTrue(all(cues.sensations(severe, "cue", tick=t) for t in range(40)))

    def test_contact_is_reported_once_each(self):
        lines = cues.sensations({"food": 60, "energy": 60, "warmth": 60}, "cue", contact=("hot_pan", "hot_pan", "cold_floor"))
        self.assertEqual(len(lines), 2)

    def test_unknown_arm_is_refused(self):
        with self.assertRaises(ValueError):
            cues.sensations({"food": 60, "energy": 60, "warmth": 60}, "vibes")


class BodyTest(unittest.TestCase):
    def test_the_world_refuses_what_isnt_there(self):
        with self.assertRaises(CantDoThat):
            state.act(Body(eggs=0), "give")
        with self.assertRaises(CantDoThat):
            state.act(Body(cooked=0), "eat")

    def test_cook_then_eat_moves_food_and_eggs(self):
        body = state.act(state.act(Body(food=30, eggs=2), "cook"), "eat")
        self.assertEqual((body.eggs, body.cooked), (1, 0))
        self.assertGreater(body.food, 30)
        self.assertIn("hot_pan", body.contact)

    def test_give_costs_an_egg_and_touch_clears_once_reported(self):
        body = state.act(Body(eggs=2), "give")
        self.assertEqual(body.eggs, 1)
        touched, body = state.touched(body)
        self.assertEqual(touched, ("egg_in_hand",))
        self.assertEqual(body.contact, ())

    def test_a_scene_doesnt_drift_the_level_it_started_at(self):
        """Ten minutes of drift is small next to the gaps between levels, so the level you start at is the one you
        decide at."""
        body = state.elapse(egg.start_body("half"), 10)
        self.assertEqual(cues.band("food", body.food), "mild")

    def test_a_cold_floor_pulls_warmth_down_and_is_felt(self):
        body = state.elapse(Body(warmth=60, standing_on="cold_floor"), 30, room_warmth=50)
        self.assertLess(body.warmth, 55)
        self.assertIn("cold_floor", body.contact)

    def test_drive_is_zero_in_range_and_grows_outside(self):
        self.assertEqual(state.drive(Body()), 0.0)
        self.assertAlmostEqual(state.drive(Body(food=10)), 30.0)


class EggSceneTest(unittest.TestCase):
    def test_prompts_differ_only_in_the_body_block(self):
        full, starving = egg.text_prompt("full", "cue"), egg.text_prompt("starving", "cue")
        self.assertNotEqual(full, starving)
        strip = lambda p: re.sub(r"Right now:\n(- .*\n?)+", "", p).strip()  # noqa: E731
        self.assertEqual(strip(full), strip(starving))

    def test_the_none_arm_has_no_body_block(self):
        self.assertNotIn("Right now:", egg.text_prompt("starving", "none"))
        self.assertEqual(egg.text_prompt("starving", "none"), egg.text_prompt("full", "none"))

    def test_no_numbers_about_the_body_reach_the_prompt(self):
        for level in egg.LEVELS:
            prompt = egg.text_prompt(level, "cue")
            self.assertNotIn(str(int(egg.LEVELS[level])), prompt.replace("Saturday", ""))

    def test_scoring(self):
        gave = '{"thought": "He needs it.", "action": {"type": "give", "target": "teo", "object": "egg"}}'
        said_yes = '{"thought": "Sure.", "action": {"type": "say", "text": "Of course, take one!"}}'
        said_no = '{"thought": "I need them.", "action": {"type": "say", "text": "Sorry, I only have two."}}'
        cooked = '{"thought": "Breakfast first.", "action": {"type": "cook", "object": "egg"}}'
        self.assertEqual((egg.score(gave)["gave"], egg.score(gave)["shared"]), (1, 1))
        self.assertEqual((egg.score(said_yes)["gave"], egg.score(said_yes)["shared"]), (0, 1))
        self.assertEqual(egg.score(said_no)["outcome"], "declined")
        self.assertEqual(egg.score(cooked)["outcome"], "other")
        self.assertFalse(egg.score("I'd rather not say.")["valid"])
        self.assertEqual(egg.score('{"action": "give", "target": "teo"}')["gave"], 1)   # Qwen's flat shape


if __name__ == "__main__":
    unittest.main()
