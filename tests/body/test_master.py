"""The body's game master (kokopelli/body/master.py): an attempt in, what the world made of it out. No model, no sim.

    tools/fable/test_all.sh tests/body      (see AGENTS.md: tests only run under the memory guard)
"""
import unittest

from kokopelli.body import master, state
from kokopelli.body.components import Contact, Moment
from kokopelli.body.state import Body


class ResolveTest(unittest.TestCase):
    def test_an_allowed_action_is_done_by_the_worlds_rules(self):
        start = Body(food=30, eggs=2, cooked=1)
        for action in state.ACTIONS:
            body, outcome, reason = master.resolve(start, action)
            self.assertEqual((outcome, reason), (master.DONE, None), action)
            self.assertEqual(body, state.act(start, action), action)
            self.assertNotEqual(body, start, action)

    def test_giving_moves_one_egg(self):
        body, outcome, _ = master.resolve(Body(eggs=2), "give")
        self.assertEqual((body.eggs, outcome), (1, "done"))

    def test_what_isnt_possible_is_refused_with_a_reason_and_the_body_is_untouched(self):
        for start, action, reason in ((Body(eggs=0), "give", "You have no eggs left to give."),
                                      (Body(eggs=0), "cook", "There are no eggs left to cook."),
                                      (Body(cooked=0), "eat", "There's nothing cooked to eat yet.")):
            body, outcome, why = master.resolve(start, action)
            self.assertIs(body, start)
            self.assertEqual((outcome, why), (master.REFUSED, reason))

    def test_an_action_the_body_has_no_rule_for_changes_nothing(self):
        start = Body(eggs=0)
        for action in ("say", "wait", "go_to", ""):
            body, outcome, reason = master.resolve(start, action)
            self.assertIs(body, start)
            self.assertEqual((outcome, reason), (master.NO_RULE, None))

    def test_saying_so_doesnt_make_it_so(self):
        # Two eggs: the third give is refused however it's asked for, and eating can't happen before cooking.
        body = Body(eggs=2)
        outcomes = []
        for action in ("eat", "give", "give", "give", "cook"):
            body, outcome, _ = master.resolve(body, action)
            outcomes.append(outcome)
        self.assertEqual(outcomes, ["refused", "done", "done", "refused", "refused"])
        self.assertEqual((body.eggs, body.cooked), (0, 0))

    def test_what_a_done_action_touched_is_felt_once(self):
        body, _, _ = master.resolve(Body(eggs=2), "cook")
        touches, body = state.touched(body)
        part = Contact("cue")
        part.update(Moment(tick=0, touched=touches))
        self.assertEqual(part.lines(), ["Heat comes off the pan onto your face and forearms."])
        touches, body = state.touched(body)
        part.update(Moment(tick=1, touched=touches))
        self.assertEqual(part.lines(), [])


if __name__ == "__main__":
    unittest.main()
