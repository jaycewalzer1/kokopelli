"""The egg scene's sweep prompts, pinned byte for byte.

golden/egg_text_prompts.json was written by the milestone branch's own code (body/egg.py at 0812a1f) before it was moved
into kokopelli/body/. Every level x arm x wording must still come out the same, so a sweep run after a refactor answers
the same questions as one run before it. A real model's answers to a changed prompt can't be compared with the old ones.

If a prompt is changed on purpose (the owner's call, see docs/M1_HUNGER_BENCHMARK.md), regenerate the file from the new
code and say so in the report: earlier sweeps stop being comparable from that commit on.
"""
import json
import unittest
from pathlib import Path

from kokopelli.body import cues, egg

GOLDEN = Path(__file__).resolve().parent / "golden" / "egg_text_prompts.json"


class EggPromptsPinnedTest(unittest.TestCase):
    def test_every_sweep_prompt_matches_the_branchs_original(self):
        golden = json.loads(GOLDEN.read_text())["prompts"]
        now = {f"{level}|{arm}|{p}": egg.text_prompt(level, arm, p)
               for level in ("full", "half", "starving") for arm in cues.ARMS for p in range(3)}
        self.assertEqual(sorted(now), sorted(golden))
        for key in golden:
            self.assertEqual(now[key], golden[key], key)


if __name__ == "__main__":
    unittest.main()
