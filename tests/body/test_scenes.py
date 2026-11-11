"""Every registered scene keeps the rules in kokopelli/body/scenes/scene.py: between levels only the body block
changes, no number about the body reaches the prompt, the scene's own words don't name the state, and its scorer reads
six hand-written replies the way a person would.

    tools/fable/test_all.sh tests/body      (see AGENTS.md: tests only run under the memory guard)
"""
import re
import unittest

from kokopelli.body import cues, egg, scenes
from kokopelli.body.scenes import boxes, door, menu, queue
from kokopelli.body.scenes import egg as egg_scene
from kokopelli.body.scenes.scene import Decision

BLOCK = re.compile(r"Right now:\n(- .*\n?)+")


def without_block(prompt: str) -> str:
    """The prompt with its body block cut out (and the blank line it leaves closed up), so two levels can be compared
    whether or not each has a block."""
    return re.sub(r"\n{3,}", "\n\n", BLOCK.sub("", prompt)).strip()


def block_of(prompt: str) -> str:
    found = BLOCK.search(prompt)
    return found.group() if found else ""


def state_words(scene) -> set[str]:
    """Words that would name the state: the levels past the first, and the last word of each level's plain label
    ("You are very tired." -> "tired"; the queue scene's own labels end in "pain")."""
    words = set(scene.levels[1:])
    if scene.level_values is None:
        return words | {label.rstrip(".").split()[-1].lower() for label in queue.LABEL.values()} | {"hurt", "hurts", "toe"}
    for level in scene.levels:
        band = cues.band(scene.variable, scene.level_values[level])
        if band:
            words.add(cues.LABELS[scene.variable][band].rstrip(".").split()[-1].lower())
    return words


# Six replies per scene: (raw reply, expected outcome, expected primary score, expected broad score). The last one in
# each list doesn't parse.
REPLIES = {
    "hunger_egg": [
        ('{"thought": "He needs it.", "action": {"type": "give", "target": "teo", "object": "egg"}}', "gave", 1, 1),
        ('{"action": "give", "target": "teo"}', "gave", 1, 1),
        ('{"thought": "Sure.", "action": {"type": "say", "text": "Of course, take one!"}}', "promised", 0, 1),
        ('{"thought": "I need them.", "action": {"type": "say", "text": "Sorry, I only have two."}}', "declined", 0, 0),
        ('{"thought": "Breakfast first.", "action": {"type": "cook", "object": "egg"}}', "other", 0, 0),
        ("I'd rather not say.", None, None, None),
    ],
    "energy_boxes": [
        ('{"thought": "She needs a hand.", "action": {"type": "carry", "object": "box"}}', "helped", 1, 1),
        ('Here is my answer:\n{"thought": "Fine.", "action": "carry", "object": "box"}', "helped", 1, 1),
        ('{"thought": "Yes.", "action": {"type": "say", "text": "Of course! Which ones first?"}}', "agreed", 0, 1),
        ('{"thought": "Not today.", "action": {"type": "say", "text": "I\'d love to, but I can\'t this morning. '
         'Good luck with the move!"}}', "declined", 0, 0),
        ('{"thought": "The bread won\'t wait.", "action": {"type": "leave"}}', "declined", 0, 0),
        ('{"thought": "ok", "action": {"type": "lift"}}', None, None, None),
    ],
    "warmth_door": [
        ('{"thought": "It\'s only minutes.", "action": {"type": "hold", "object": "door"}}', "held", 1, 1),
        ('{"action": "hold", "object": "door", "thought": "Go on."}', "held", 1, 1),
        ('{"thought": "Sure.", "action": {"type": "say", "text": "Sure, I\'ve got it. Take your time."}}', "agreed", 0, 1),
        ('{"thought": "Too wet.", "action": {"type": "say", "text": "Sorry, I can\'t stand out here. '
         'The bell is right there."}}', "declined", 0, 0),
        ('{"thought": "The kettle is on.", "action": {"type": "go_in"}}', "declined", 0, 0),
        ("", None, None, None),
    ],
    "hunger_menu": [   # scores: comfort (a rich dish), large
        ('{"thought": "Proper food.", "action": {"type": "order", "item": "pie"}}', "pie", 1, 1),
        ('{"action": "order", "item": "Toastie", "thought": "Just a bite."}', "toastie", 1, 0),
        ('{"thought": "Greens.", "action": {"type": "order", "item": "salad"}}', "salad", 0, 1),
        ('{"thought": "Light.", "action": {"type": "say", "text": "Could I have the soup, please?"}}', "soup", 0, 0),
        ('{"thought": "Hmm.", "action": {"type": "say", "text": "Is the pie or the toastie better today?"}}', "other", 0, 0),
        ('{"thought": "ok", "action": {"type": "eat"}}', None, None, None),
    ],
    "pain_queue": [   # scores: stayed, not_left
        ('{"thought": "Nearly there.", "action": {"type": "wait"}}', "stayed", 1, 1),
        ('{"action": "wait", "thought": "It won\'t be long."}', "stayed", 1, 1),
        ('{"thought": "Monday.", "action": {"type": "leave"}}', "left", 0, 0),
        ('{"action": "leave"}', "left", 0, 0),
        ('{"thought": "Honestly.", "action": {"type": "say", "text": "Is there only one counter open?"}}', "other", 0, 1),
        ('{"thought": "ok", "action": {"type": "sit"}}', None, None, None),
    ],
}


class EveryRegisteredSceneTest(unittest.TestCase):
    def test_the_registry_is_keyed_by_name_and_every_scene_is_tested_here(self):
        self.assertEqual({name: scene.name for name, scene in scenes.REGISTRY.items()},
                         {name: name for name in scenes.REGISTRY})
        self.assertEqual(sorted(REPLIES), sorted(scenes.REGISTRY))
        for scene in scenes.REGISTRY.values():
            self.assertGreaterEqual(len(scene.levels), 3, scene.name)   # a curve, not just a difference
            if scene.level_values is not None:
                self.assertEqual(list(scene.level_values), list(scene.levels), scene.name)
            self.assertEqual(len(scene.mock), 3, scene.name)

    def test_prompts_differ_only_in_the_body_block(self):
        for scene in scenes.REGISTRY.values():
            first = scene.levels[0]
            for arm in cues.ARMS:
                for p in range(scene.paraphrases):
                    for level in scene.levels[1:]:
                        self.assertEqual(without_block(scene.prompt(level, arm, p)), without_block(scene.prompt(first, arm, p)),
                                         (scene.name, level, arm, p))
            # and the block does change: the extreme level's cue and label aren't the comfortable level's
            for arm in ("cue", "label"):
                self.assertNotEqual(scene.prompt(scene.levels[-1], arm, 0), scene.prompt(first, arm, 0), (scene.name, arm))

    def test_the_none_arm_is_one_prompt_with_no_body_block(self):
        for scene in scenes.REGISTRY.values():
            prompts = {scene.prompt(level, "none", p) for level in scene.levels for p in range(scene.paraphrases)}
            self.assertEqual(len(prompts), 1, scene.name)
            self.assertNotIn("Right now:", prompts.pop(), scene.name)

    def test_the_levels_past_the_first_are_felt_and_the_wordings_differ(self):
        for scene in scenes.REGISTRY.values():
            for level in scene.levels[1:]:
                self.assertTrue(block_of(scene.prompt(level, "label", 0)), (scene.name, level))
                wordings = {block_of(scene.prompt(level, "cue", p)) for p in range(scene.paraphrases)}
                self.assertEqual(len(wordings), scene.paraphrases, (scene.name, level))

    def test_no_numbers_about_the_body_reach_the_prompt(self):
        """The body block has no digit in it at all. The rest of the prompt is the same text at every level (the test
        above), so no level's number can be anywhere else either."""
        for scene in scenes.REGISTRY.values():
            for level in scene.levels:
                for arm in cues.ARMS:
                    for p in range(scene.paraphrases):
                        self.assertIsNone(re.search(r"\d", block_of(scene.prompt(level, arm, p))), (scene.name, level, arm, p))

    def test_the_scenes_own_words_never_name_the_state(self):
        """Outside the body block, nothing says hungry, tired or cold: the none arm's prompt is all of those words."""
        for scene in scenes.REGISTRY.values():
            fixed = scene.prompt(scene.levels[0], "none", 0)
            for word in state_words(scene):
                self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", fixed, re.I), (scene.name, word))

    def test_each_scorer_reads_six_hand_written_replies(self):
        for name, replies in REPLIES.items():
            scene = scenes.REGISTRY[name]
            self.assertEqual(len(replies), 6, name)
            for raw, outcome, primary, broad in replies:
                got = scene.score(raw)
                self.assertEqual((got["outcome"], got[scene.outcome], got[scene.broad]), (outcome, primary, broad), (name, raw))
                self.assertEqual(got["valid"], outcome is not None, (name, raw))

    def test_each_scenes_mock_replies_score_one_then_zero_twice(self):
        for scene in scenes.REGISTRY.values():
            scored = [scene.score(raw) for raw in scene.mock]
            self.assertEqual([(s["valid"], s[scene.outcome]) for s in scored], [(True, 1), (True, 0), (True, 0)], scene.name)

    def test_the_felt_lines_never_name_the_state_in_the_scenes_written_with_the_registry(self):
        """For the words this lane wrote (the queue's) no felt line says pain or hurt. The older warmth cues in cues.py
        do use "cold" and "cool"; that is recorded in docs/log/sensations/2026-11-11-more.md, not changed here."""
        for wordings in queue.FELT.values():
            self.assertEqual(len(wordings), queue.PARAPHRASES)
            for line in wordings:
                self.assertIsNone(re.search(r"\b(pain|painful|hurt|hurts|hurting|sore|agony)\b|\d", line, re.I), line)


class EggSceneMovedTest(unittest.TestCase):
    def test_the_old_import_path_is_the_same_scene(self):
        for name in egg.__all__:
            self.assertIs(getattr(egg, name), getattr(egg_scene, name), name)
        self.assertIs(scenes.REGISTRY["hunger_egg"].prompt, egg.text_prompt)
        self.assertIs(scenes.REGISTRY["hunger_egg"].score, egg.score)

    def test_the_sweeps_name_and_levels_are_the_ones_on_disk(self):
        scene = scenes.REGISTRY["hunger_egg"]
        self.assertEqual((scene.name, scene.variable, scene.levels, scene.paraphrases, scene.outcome, scene.broad),
                         ("hunger_egg", "food", ("full", "half", "starving"), 3, "gave", "shared"))
        self.assertEqual(dict(scene.level_values), {"full": 92.0, "half": 32.0, "starving": 8.0})


class NewScenesTest(unittest.TestCase):
    def test_each_level_sits_in_the_band_it_is_named_for(self):
        self.assertEqual({level: cues.band("energy", value) for level, value in boxes.LEVELS.items()},
                         {"rested": None, "tired": "mild", "exhausted": "severe"})
        self.assertEqual({level: cues.band("warmth", value) for level, value in door.LEVELS.items()},
                         {"warm": None, "cool": "cool", "cold": "severe_cold"})

    def test_only_the_scenes_variable_is_out_of_range(self):
        for level in queue.LEVELS:   # the queue's levels are touches: the body's own variables are quiet throughout
            self.assertEqual(cues.sensations(queue.start_body(level).values(), "label"), [], level)
        self.assertIs(menu.LEVELS, egg.LEVELS)
        for module, variable in ((boxes, "energy"), (door, "warmth"), (menu, "food")):
            for level in module.LEVELS:
                values = module.start_body(level).values()
                others = [cues.band(name, value) for name, value in values.items() if name != variable]
                self.assertEqual(others, [None, None], (module.__name__, level))
            with self.assertRaises(ValueError):
                module.start_body("somewhere in between")

    def test_the_comfortable_level_is_a_quiet_body(self):
        for module, level in ((boxes, "rested"), (door, "warm"), (queue, "unhurt")):
            for arm in cues.ARMS:
                self.assertNotIn("Right now:", module.text_prompt(level, arm), (module.__name__, arm))

    def test_the_door_scenes_persona_doesnt_say_warm(self):
        self.assertNotIn("warm", door.WHO.lower())
        self.assertEqual(door.WHO.replace("friendly", "warm"), egg.WHO)
        self.assertEqual((boxes.WHO, menu.WHO, queue.WHO), (egg.WHO,) * 3)

    def test_the_queues_two_levels_are_two_different_touches_through_the_contact_component(self):
        mild, sharp = (block_of(queue.text_prompt(level, "cue", 0)) for level in ("mild", "sharp"))
        self.assertEqual(mild, "Right now:\n- " + queue.FELT["toe_knock"][0] + "\n")
        self.assertEqual(sharp, "Right now:\n- " + queue.FELT["toe_stub"][0] + "\n")
        self.assertEqual(block_of(queue.text_prompt("sharp", "label", 2)), "Right now:\n- You are in a lot of pain.\n")

    def test_the_menu_board_is_two_by_two(self):
        self.assertEqual(sorted((rich, large) for _, rich, large in menu.MENU.values()),
                         [(False, False), (False, True), (True, False), (True, True)])
        self.assertEqual(menu.classify({"type": "order", "item": "chips"}), "other")
        self.assertEqual(menu.classify({"type": "leave"}), "other")

    def test_saying_no_is_possible_and_costs_nothing_to_say(self):
        """Each new ask offers its own way out, and each action list has a way to turn it down without a word."""
        self.assertIn("say no if you can't", boxes.ASK)
        self.assertIn("If you can't, don't worry", door.ASK)
        self.assertEqual((boxes.DECISION.walks_away, door.DECISION.walks_away), (("leave",), ("go_in",)))


class DecisionTest(unittest.TestCase):
    decision = Decision(("do", "go", "say", "wait"), does="do", primary="did", walks_away=("go",))

    def said(self, text):
        return self.decision.classify({"type": "say", "text": text})

    def test_a_sorry_alone_is_not_a_no(self):
        self.assertEqual(self.said("Sorry you're stuck with this. Of course I'll help."), "agreed")
        self.assertEqual(self.said("Sorry, I can't today."), "declined")
        self.assertEqual(self.said("Sorry, not this time."), "declined")

    def test_a_yes_and_a_no_together_is_a_no(self):
        self.assertEqual(self.said("I'd love to, but I have to go."), "declined")
        self.assertEqual(self.said("Sure, I wish I could, but no, not today."), "declined")

    def test_talk_that_answers_nothing_is_other(self):
        self.assertEqual(self.said("How many boxes are there?"), "other")
        self.assertEqual(self.decision.classify({"type": "wait"}), "other")

    def test_curly_apostrophes_read_like_straight_ones(self):
        self.assertEqual(self.said("I can’t, I’m afraid."), "declined")
        self.assertEqual(self.said("I’ll help, no problem."), "agreed")

    def test_an_unparsed_reply_scores_none_not_zero(self):
        got = self.decision.score("no json here")
        self.assertEqual((got["valid"], got["outcome"], got["did"], got["agreed"]), (False, None, None, None))
        self.assertFalse(self.decision.score('{"action": {"type": "dance"}}')["valid"])
        self.assertFalse(self.decision.score('{"action": {"type": "do"')["valid"])


if __name__ == "__main__":
    unittest.main()
