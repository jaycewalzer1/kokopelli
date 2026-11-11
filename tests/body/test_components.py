"""The components a body block is built from (kokopelli/body/components.py). No model, no sim.

    tools/fable/test_all.sh tests/body      (see AGENTS.md: tests only run under the memory guard)

The first test is the one that lets the components replace the old code path: on a grid of bodies, arms, wordings,
ticks and touches, they give exactly what cues.sensations and cues.block give. The egg prompts themselves are pinned in
test_egg_prompts_pinned.py and tests/agents/test_egg_wm.py.
"""
import itertools
import re
import unittest

from kokopelli.body import components, cues, egg
from kokopelli.body.components import Contact, Interoception, Moment, Senses, Situation
from kokopelli.body.state import Body

QUIET = Body(food=60, energy=60, warmth=60)
STARVING = Body(food=8, energy=60, warmth=60)
MILD = Body(food=32, energy=60, warmth=60)

FOODS = (2, 8, 20, 32, 60, 92)
ENERGIES = (8, 60, 95)
WARMTHS = (10, 35, 60, 85, 95)
PARAPHRASES = (None, 0, 1, 2)
TICKS = (None, 0, 1, 2, 3, 7)
TOUCHES = ((), ("hot_pan",), ("hot_pan", "hot_pan", "cold_floor"),
           ("not_in_the_table", "chair", "egg_in_hand", "chair"))


class SameAsTheOldPathTest(unittest.TestCase):
    def test_the_components_give_exactly_what_cues_gives(self):
        checked = 0
        for food, energy, warmth, arm, paraphrase, tick, touched in itertools.product(
                FOODS, ENERGIES, WARMTHS, cues.ARMS, PARAPHRASES, TICKS, TOUCHES):
            body = Body(food=food, energy=energy, warmth=warmth)
            senses = Senses(Interoception(arm, paraphrase=paraphrase), Contact(arm))
            senses.update(Moment(tick=tick, touched=touched))
            case = (food, energy, warmth, arm, paraphrase, tick, touched)
            old = {"paraphrase": paraphrase, "tick": tick, "contact": touched}
            self.assertEqual(senses.lines(body), cues.sensations(body.values(), arm, **old), case)
            self.assertEqual(senses.pre_act(body), cues.block(body.values(), arm, **old), case)
            checked += 1
        self.assertEqual(checked, 6 * 3 * 5 * 3 * 4 * 6 * 4)

    def test_no_number_reaches_the_block_at_any_body(self):
        for food, energy, warmth, arm in itertools.product(FOODS, ENERGIES, WARMTHS, ("cue", "label")):
            senses = Senses(Interoception(arm), Contact(arm))
            senses.update(Moment(tick=0, touched=tuple(cues.CONTACT)))
            self.assertIsNone(re.search(r"\d", senses.pre_act(Body(food=food, energy=energy, warmth=warmth))))


class BlockTest(unittest.TestCase):
    def test_lines_become_a_bulleted_section_and_no_lines_become_nothing(self):
        self.assertEqual(components.block(["One.", "Two."]), "Right now:\n- One.\n- Two.")
        self.assertEqual(components.block([]), "")


class SituationTest(unittest.TestCase):
    def test_it_says_who_and_where_and_nothing_changes_it(self):
        scene = Situation("You are Ines, a baker.", "It's noon and the queue is long.")
        said = "You are Ines, a baker.\n\nSituation: It's noon and the queue is long."
        self.assertEqual(scene.pre_act(), said)
        self.assertEqual(scene.pre_act(STARVING), said)
        scene.update(Moment(tick=3, touched=("hot_pan",)))
        self.assertEqual(scene.pre_act(STARVING), said)

    def test_it_has_no_felt_lines_so_among_senses_it_adds_nothing(self):
        scene = Situation("You are Ines, a baker.", "It's noon and the queue is long.")
        self.assertEqual(scene.lines(STARVING), [])
        self.assertEqual(Senses(scene, Interoception("label")).pre_act(STARVING), Interoception("label").pre_act(STARVING))

    def test_the_egg_scenes_opening_is_its_two_paragraphs(self):
        opening = Situation(egg.WHO, egg.SITUATION).pre_act()
        self.assertTrue(egg.text_prompt("half", "none").startswith(opening + "\n\n"))
        self.assertEqual(opening, f"{egg.WHO}\n\nSituation: {egg.SITUATION}")


class InteroceptionTest(unittest.TestCase):
    def test_a_quiet_body_adds_nothing_in_any_arm(self):
        for arm in cues.ARMS:
            self.assertEqual(Interoception(arm).lines(QUIET), [])
            self.assertEqual(Interoception(arm).pre_act(QUIET), "")

    def test_the_three_arms(self):
        self.assertEqual(Interoception("label").pre_act(STARVING), "Right now:\n- You are extremely hungry.")
        self.assertEqual(Interoception("none").pre_act(STARVING), "")
        self.assertEqual(Interoception("cue", paraphrase=0).lines(STARVING), [cues.CUES["food"]["severe"][0]])

    def test_an_unknown_arm_is_refused_when_the_component_is_made(self):
        with self.assertRaises(ValueError):
            Interoception("vibes")
        with self.assertRaises(ValueError):
            Contact("vibes")

    def test_a_sweep_always_shows_a_mild_cue_and_each_wording_differs(self):
        said = {Interoception("cue", paraphrase=k).pre_act(MILD) for k in range(3)}
        self.assertEqual(len(said), 3)
        self.assertNotIn("", said)

    def test_in_a_live_run_mild_cues_come_and_go_with_the_tick_and_strong_ones_stay(self):
        part = Interoception("cue")
        shown, strong = [], []
        for tick in range(40):
            part.update(Moment(tick=tick))
            shown.append(bool(part.lines(MILD)))
            strong.append(bool(part.lines(STARVING)))
        self.assertTrue(any(shown) and not all(shown))
        self.assertTrue(all(strong))
        # the lead's log: half shows at decisions 0, 3 and 7 of the first 8
        self.assertEqual([tick for tick in range(8) if shown[tick]], [0, 3, 7])

    def test_a_tick_given_when_made_is_the_same_as_one_sent_later(self):
        sent = Interoception("cue")
        for tick in range(8):
            sent.update(Moment(tick=tick))
            self.assertEqual(sent.lines(MILD), Interoception("cue", tick=tick).lines(MILD))
            self.assertEqual(sent.tick, tick)

    def test_energy_and_warmth_are_felt_the_same_way_as_food(self):
        # A scene that isn't the egg: only the body it starts from differs.
        self.assertEqual(Interoception("label").lines(Body(energy=8)), ["You are exhausted."])
        self.assertEqual(Interoception("label").lines(Body(warmth=10)), ["You are freezing."])
        self.assertEqual(Interoception("cue", paraphrase=1).lines(Body(energy=20, warmth=35)),
                         [cues.CUES["energy"]["strong"][1], cues.CUES["warmth"]["cool"][1]])


class ContactTest(unittest.TestCase):
    def test_nothing_touched_adds_nothing(self):
        self.assertEqual(Contact("cue").lines(), [])
        self.assertEqual(Contact("cue").pre_act(QUIET), "")

    def test_each_thing_is_reported_once_in_the_order_it_happened(self):
        part = Contact("cue")
        part.update(Moment(touched=("hot_pan", "cold_floor", "hot_pan")))
        self.assertEqual(part.lines(), [cues.CONTACT["hot_pan"][0], cues.CONTACT["cold_floor"][0]])
        self.assertEqual(part.pre_act(QUIET), "Right now:\n- " + "\n- ".join(part.lines()))

    def test_a_touch_belongs_to_one_decision_only(self):
        part = Contact("cue")
        part.update(Moment(tick=0, touched=("warm_mug",)))
        self.assertEqual(len(part.lines()), 1)
        self.assertEqual(part.lines(), part.lines())      # reading doesn't use it up: a log may read it again
        part.update(Moment(tick=1))
        self.assertEqual(part.lines(), [])

    def test_the_label_arm_states_it_and_the_none_arm_says_nothing(self):
        for arm, expected in (("label", ["You are holding a warm mug."]), ("none", [])):
            part = Contact(arm)
            part.update(Moment(touched=("warm_mug",)))
            self.assertEqual(part.lines(), expected)

    def test_a_thing_with_no_words_is_left_out(self):
        part = Contact("cue")
        part.update(Moment(touched=("a_thing_nobody_wrote_words_for", "chair")))
        self.assertEqual(part.lines(), [cues.CONTACT["chair"][0]])

    def test_a_scene_can_bring_its_own_words(self):
        words = {"stubbed_toe": ("Your big toe throbs where it caught the step.", "You have stubbed your toe.")}
        felt, told = Contact("cue", words=words), Contact("label", words=words)
        for part in (felt, told):
            part.update(Moment(touched=("stubbed_toe", "hot_pan")))    # hot_pan isn't in this scene's table
        self.assertEqual(felt.lines(), ["Your big toe throbs where it caught the step."])
        self.assertEqual(told.lines(), ["You have stubbed your toe."])


class SensesTest(unittest.TestCase):
    def test_components_share_one_header_in_the_order_given(self):
        senses = Senses(Interoception("label"), Contact("label"))
        senses.update(Moment(tick=0, touched=("chair",)))
        self.assertEqual(senses.pre_act(STARVING), "Right now:\n- You are extremely hungry.\n- You are sitting in a chair.")
        swapped = Senses(Contact("label"), Interoception("label"))
        swapped.update(Moment(tick=0, touched=("chair",)))
        self.assertEqual(swapped.lines(STARVING), ["You are sitting in a chair.", "You are extremely hungry."])

    def test_an_event_reaches_every_component(self):
        inside, touch = Interoception("cue"), Contact("cue")
        Senses(inside, touch).update(Moment(tick=5, touched=("chair",)))
        self.assertEqual((inside.tick, touch.touched), (5, ("chair",)))

    def test_no_components_or_nothing_felt_gives_an_empty_string(self):
        self.assertEqual(Senses().pre_act(STARVING), "")
        self.assertEqual(Senses().lines(STARVING), [])
        self.assertEqual(Senses(Interoception("cue"), Contact("cue")).pre_act(QUIET), "")


if __name__ == "__main__":
    unittest.main()
