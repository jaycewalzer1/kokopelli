"""kokopelli/body/_hash.py is a copy of experiments/benchmarks/core.py's stable_int (the library can't import an
experiment). If the two ever differ, a sweep and a video run stop drawing the same seeds, so they're held equal here."""
import inspect
import random
import unittest

from experiments.benchmarks import core
from kokopelli.body import _hash


def body_of(function):
    """The function's lines after its `def` line: the docstring and the code, without the signature's annotations."""
    return inspect.getsource(function).split("\n", 1)[1]


class StableIntTest(unittest.TestCase):
    def test_the_copy_is_the_original_byte_for_byte(self):
        self.assertEqual(body_of(_hash.stable_int), body_of(core.stable_int))

    def test_both_give_the_same_number_for_the_same_parts(self):
        rng = random.Random(0)
        for _ in range(200):
            parts = [rng.choice(("cue", "egg", "sensation", "hunger_egg", "label", None, 3.5)), rng.randrange(10**6), rng.random()]
            self.assertEqual(_hash.stable_int(*parts), core.stable_int(*parts))
        self.assertEqual(_hash.stable_int(), core.stable_int())

    def test_the_seeds_already_in_use_dont_move(self):
        # Computed with the milestone branch's benchmarks/core.py before the port (commit 0812a1f): the first cue-arm sweep
        # seed, the first video decision seed, and the number that picks a severe hunger cue's wording in a live run.
        self.assertEqual(_hash.stable_int("sensation", "hunger_egg", "cue", 0, 0) % (2**31), 1100433994)
        self.assertEqual(_hash.stable_int("egg", 2025, 0) % (2**31), 1284490423)
        self.assertEqual(_hash.stable_int("cue", "food", "severe", 0), 18409607134976111066)


if __name__ == "__main__":
    unittest.main()
