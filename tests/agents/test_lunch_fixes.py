"""P5 lunch switches (kokopelli/agents/lunch_fixes.py, lunch_bench.py): all off by default, and each does what it says on
the toy world with the fake brains. No model runs."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tests" / "agents", ROOT / "kokopelli" / "agents"):
    sys.path.insert(0, str(_p))

import lunch_bench as lb  # noqa: E402
import lunch_fixes as fx  # noqa: E402
import lunch_wm as lw  # noqa: E402


def bench(*extra, brain="parrot"):
    tmp = Path(tempfile.mkdtemp(prefix="test_lunch_fixes_"))
    try:
        return lb.run(["--brain", brain, "--minutes", "3", "--out", str(tmp / "run"), *extra])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class HelpersTest(unittest.TestCase):
    def test_switches_are_off_by_default(self):
        a = lw.build_args([])
        self.assertEqual(a.fixes, [])
        self.assertFalse(a.decide_on_change)

    def test_view_prompts_off_by_default_and_each_person_worded_the_same(self):
        import lunch_text as lt
        a = lw.build_args([])
        self.assertEqual(lt.prompts_for(a, ["mara", "iris"]), {"mara": lt.WM_PROMPT, "iris": lt.WM_PROMPT})
        a = lw.build_args(["--view-prompts"])
        p = lt.prompts_for(a, ["mara", "iris"])
        self.assertIn(lt.LOOKS["iris"], p["mara"])
        self.assertIn(lt.LOOKS["mara"], p["iris"])
        self.assertNotIn(lt.LOOKS["mara"], p["mara"])   # her own eye camera hides her body
        self.assertIn(lt.LOOKS["ana"], p["mara"])
        self.assertIn(lt.LOOKS["ana"], p["iris"])

    def test_life_switch_adds_the_generated_past_under_the_persona(self):
        import lunch_life
        tmp = Path(tempfile.mkdtemp(prefix="test_lunch_life_"))
        try:
            db = tmp / "life.db"
            lunch_life.generate(db, mock=True)
            nav = lw.NavMap()
            off, on = lw.build_args([]), lw.build_args(["--life", str(db)])
            lw.people(off, nav)
            lw.people(on, nav)
            self.assertNotIn("Where you come from", off.first["who"])
            self.assertTrue(on.first["who"].startswith(off.first["who"]))
            self.assertIn("Where you come from", on.second["who"])
            self.assertLessEqual(len(on.first["who"]) - len(off.first["who"]), lunch_life.PAST_CHARS + 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_parse_fixes(self):
        self.assertEqual(fx.parse_fixes("all"), set(fx.FIXES))
        self.assertEqual(fx.parse_fixes("memory, loops"), {"memory", "loops"})
        with self.assertRaises(ValueError):
            fx.parse_fixes("memroy")

    def test_repeated_finds_own_lines_and_echoes(self):
        line = "Iris, I know you're buzzing, but I'm all ears: what's new with the bees?"
        self.assertEqual(fx.repeated(line.replace("I'm", "I’m"), [line], []), ("you", line))
        self.assertEqual(fx.repeated("I'll grab the bowl. Anything light, soup or salad?", [],
                                     ["I’ll grab the bowl. Anything light—soup or salad?"])[0], "other")
        self.assertIsNone(fx.repeated("Salad. Light and fresh.", ["How are the bees?"], ["Soup or salad?"]))

    def test_restates(self):
        diary = ["[12:20:30] Met Iris at The Kettle. She's buzzing with bee updates."]
        self.assertTrue(fx.restates("Met Iris at The Kettle! She's buzzing with bee updates.", diary))
        self.assertFalse(fx.restates("Iris's hive swarmed into the plum tree.", diary))

    def test_metrics_on_a_recorded_shape(self):
        ev = [{"kind": "says", "step": 1, "mind": "mara", "text": "Hi Iris, lovely to see you."},
              {"kind": "says", "step": 1, "mind": "iris", "text": "One hive swarmed into the plum tree."},
              {"kind": "says", "step": 2, "mind": "mara", "text": "So how are the bees doing?"},
              {"kind": "says", "step": 3, "mind": "mara", "text": "So how are the bees doing?"},
              {"kind": "act", "step": 4, "mind": "iris", "action": {"type": "approach", "target": "mara"}},
              {"kind": "act", "step": 5, "mind": "iris", "action": {"type": "approach", "target": "mara"}},
              {"kind": "decision", "step": 5, "mind": "iris"}]
        m = lb.metrics(ev)
        self.assertEqual((m["lines"], m["repeated_lines"], m["longest_loop"], m["reasked_answered_news"]), (4, 1, 2, 2))
        self.assertEqual(m["calls_per_sim_minute"], 1.0)


class SwitchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = bench()
        cls.on = bench("--fixes", "all")
        cls.gate = bench("--decide-on-change", brain="scripted")
        cls.gate_off = bench(brain="scripted")

    def test_parrot_repeats_and_loops_without_fixes(self):
        self.assertGreater(self.off["repeat_share"], 0.5)
        self.assertGreaterEqual(self.off["longest_loop"], 2)

    def test_fixes_stop_repeats_and_loops(self):
        self.assertEqual(self.on["repeat_share"], 0.0)
        self.assertLessEqual(self.on["longest_loop"], 1)
        self.assertGreater(self.on["lines"], 0)
        self.assertEqual(self.on["fixes"], ["loops", "memory", "repeats"])

    def test_gate_asks_qwen_less(self):
        self.assertLess(self.gate["qwen_calls"], self.gate_off["qwen_calls"])

    def test_memory_puts_the_conversation_in_the_prompt(self):
        tmp = Path(tempfile.mkdtemp(prefix="test_lunch_fixes_"))
        try:
            lb.run(["--brain", "parrot", "--minutes", "3", "--out", str(tmp / "run"), "--fixes", "memory"])
            prompts = [json.loads(x)["prompt"] for x in (tmp / "run" / "events.jsonl").read_text().splitlines()
                       if '"decision"' in x]
            self.assertTrue(any("The conversation so far" in p and "Iris: \"" in p for p in prompts))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
