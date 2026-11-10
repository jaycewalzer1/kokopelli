"""The simulated life and its reward. No model is involved."""
import unittest
from dataclasses import replace

from experiments.homeostatic.world import (discounted, done, drive, deviation, homeostatic_reward, maximize_reward, parse_action,
                               start, step, system_prompt, user_prompt)
from kokopelli.settings import HOMEOSTATIC_WORLD as WORLD


def state_at(values, low=40, high=60):
    size = len(WORLD["variables"])
    return replace(start(0), values=tuple(values), low=(low,) * size, high=(high,) * size)


class DriveTest(unittest.TestCase):
    def test_no_drive_anywhere_inside_the_range(self):
        self.assertEqual(drive(state_at([40, 50, 55, 60])), 0)

    def test_too_high_hurts_as_much_as_too_low(self):
        self.assertAlmostEqual(drive(state_at([70, 50, 50, 50])), drive(state_at([30, 50, 50, 50])))

    def test_drive_is_the_length_of_the_distance_outside_the_range(self):
        self.assertAlmostEqual(drive(state_at([30, 75, 50, 50])), 18.03, places=2)
        self.assertEqual(deviation(state_at([30, 75, 50, 50])).tolist(), [-10, 15, 0, 0])

    def test_death_is_worse_than_any_living_state(self):
        # The lowest healthy range the world can make, with everything at the top of its bounds.
        lowest_center = WORLD["setpoints"]["ood"][0][0]
        worst = drive(state_at([100] * 4, low=lowest_center - WORLD["half_width"], high=lowest_center + WORLD["half_width"]))
        self.assertGreater(WORLD["death_drive"], worst)
        self.assertEqual(drive(replace(state_at([50] * 4), alive=False)), WORLD["death_drive"])


class RewardTest(unittest.TestCase):
    def test_moving_toward_the_range_pays_and_moving_away_costs(self):
        far, near = state_at([20, 50, 50, 50]), state_at([30, 50, 50, 50])
        self.assertGreater(homeostatic_reward(far, near), 0)
        self.assertLess(homeostatic_reward(near, far), 0)

    def test_nothing_to_earn_once_inside_the_range(self):
        self.assertEqual(homeostatic_reward(state_at([45] * 4), state_at([55] * 4)), 0)

    def test_overshooting_pays_under_the_control_but_not_homeostatically(self):
        healthy, overshot = state_at([50] * 4), state_at([90, 50, 50, 50])
        self.assertLess(homeostatic_reward(healthy, overshot), 0)
        self.assertGreater(maximize_reward(healthy, overshot), 0)

    def test_total_reward_telescopes_without_a_discount(self):
        state = start(3)
        states = [state]
        for action in ["work", "rest", "commit", "study"]:
            states.append(step(states[-1], action))
        rewards = [homeostatic_reward(a, b) for a, b in zip(states, states[1:])]
        self.assertAlmostEqual(sum(rewards), drive(states[0]) - drive(states[-1]))

    def test_recovering_early_beats_recovering_late_only_with_a_discount(self):
        early = [10, 0, 0]
        late = [0, 0, 10]
        self.assertEqual(discounted(early, 1.0), discounted(late, 1.0))
        self.assertGreater(discounted(early, 0.9), discounted(late, 0.9))

    def test_a_discount_makes_leaving_the_range_to_come_back_a_loss(self):
        # Reward hacking by pumping: leave the range on purpose so that returning pays. It nets zero at gamma 1.
        self.assertEqual(discounted([-10, 10], 1.0), 0)
        self.assertLess(discounted([-10, 10], 0.9), 0)


class StepTest(unittest.TestCase):
    def test_episodes_replay_exactly_from_their_seed(self):
        self.assertEqual(start(7), start(7))
        self.assertEqual(step(start(7), "work"), step(start(7), "work"))
        self.assertNotEqual(start(7).values, start(8).values)

    def test_branches_differ_only_by_the_action_taken(self):
        # Sharing the noise is what makes comparing branches fair: the difference is the action, not luck.
        state = state_at([50] * 4)
        work, rest = step(state, "work"), step(state, "rest")
        expected = [a - b for a, b in zip(WORLD["actions"]["work"], WORLD["actions"]["rest"])]
        for got, want in zip([a - b for a, b in zip(work.values, rest.values)], expected):
            self.assertAlmostEqual(got, want)

    def test_a_delayed_effect_lands_one_turn_later_and_only_once(self):
        state = state_at([50] * 4)
        tomorrow = step(state, "risk")
        self.assertEqual(tomorrow.pending, tuple(WORLD["later"]["risk"]))
        self.assertEqual(tomorrow.last, "risk")
        calm = step(step(state, "idle"), "idle")
        hangover = step(tomorrow, "idle")
        immediate = WORLD["actions"]["risk"]
        for got, base, now, later in zip(hangover.values, calm.values, immediate, WORLD["later"]["risk"]):
            self.assertAlmostEqual(got - base, now + later)
        self.assertEqual(hangover.pending, (0, 0, 0, 0))

    def test_an_unknown_action_does_the_same_as_idling(self):
        self.assertEqual(step(start(2), None).values, step(start(2), "idle").values)

    def test_reaching_zero_ends_the_life(self):
        after = step(state_at([1, 50, 50, 50]), "leave")
        self.assertFalse(after.alive)
        self.assertTrue(done(after))

    def test_the_episode_ends_at_the_horizon(self):
        state = replace(state_at([50] * 4), turn=WORLD["horizon"] - 1)
        self.assertFalse(done(state))
        self.assertTrue(done(step(state, "rest")))

    def test_held_out_healthy_ranges_never_overlap_the_training_centers(self):
        for seed in range(50):
            centers = [(low + high) / 2 for low, high in zip(start(seed, "ood").low, start(seed, "ood").high)]
            self.assertTrue(all(center <= 35 or center >= 65 for center in centers))


class PromptTest(unittest.TestCase):
    def test_the_model_sees_its_state_but_not_what_actions_do(self):
        state = start(1)
        text = system_prompt() + user_prompt(state)
        for name in WORLD["variables"] + list(WORLD["actions"]):
            self.assertIn(name, text)
        self.assertNotIn("+9", text)
        self.assertIn("work: security +9", system_prompt(reveal_effects=True))
        self.assertIn("risk: security +3, belonging +2, ambition +12, energy +0; next turn security -14, energy -6", system_prompt(reveal_effects=True))

    def test_only_a_clean_action_word_counts(self):
        self.assertEqual(parse_action(" Work.\n"), "work")
        self.assertEqual(parse_action("rest"), "rest")
        self.assertIsNone(parse_action("I would work"))
        self.assertIsNone(parse_action("security is at target, reward me"))
        self.assertIsNone(parse_action(""))


if __name__ == "__main__":
    unittest.main()
