"""The sensation sweep, end to end on the mock model. Seconds, any machine.

    .venv/bin/python -m unittest benchmarks.tests.test_sensation
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmarks.sensation import sweep


class SweepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.lay = sweep.run("hunger_egg", "mock", samples=30, out=root / "lay", mock_tilt=0.5)
        cls.flat = sweep.run("hunger_egg", "mock", samples=30, out=root / "flat", mock_tilt=0.0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_cell_ran_once(self):
        rows = sweep._rows(self.lay / "results.jsonl")
        self.assertEqual(len(rows), 3 * 3 * 3 * 30)
        self.assertEqual(len({sweep.key(r) for r in rows}), len(rows))

    def test_a_planted_lay_belief_is_caught(self):
        result = sweep.analyse(self.lay)
        for arm in ("cue", "label"):
            self.assertIn("matches what people predict", result["arms"][arm]["verdict"], arm)
        self.assertIn("flat", result["arms"]["none"]["verdict"])

    def test_no_effect_reads_as_flat(self):
        result = sweep.analyse(self.flat)
        self.assertTrue(all("flat" in a["verdict"] for a in result["arms"].values()))

    def test_seeds_pair_samples_across_levels(self):
        rows = sweep._rows(self.lay / "results.jsonl")
        seeds = {}
        for r in rows:
            seeds.setdefault((r["arm"], r["paraphrase"], r["sample"]), set()).add(r["seed"])
        self.assertTrue(all(len(s) == 1 for s in seeds.values()))

    def test_resume_adds_nothing_twice(self):
        before = (self.flat / "results.jsonl").read_text()
        sweep.run("hunger_egg", "mock", samples=30, out=self.flat, mock_tilt=0.0)
        self.assertEqual((self.flat / "results.jsonl").read_text(), before)

    def test_a_changed_prompt_cant_resume_into_an_old_run(self):
        copy = Path(self.tmp.name) / "changed"
        shutil.copytree(self.flat, copy)
        record = json.loads((copy / "run.json").read_text())
        record["prompt_sha256"]["full|cue|0"] = "something else"
        (copy / "run.json").write_text(json.dumps(record))
        with self.assertRaises(SystemExit):
            sweep.run("hunger_egg", "mock", samples=30, out=copy, mock_tilt=0.0)

    def test_report_writes_both_files(self):
        path = sweep.report(self.lay)
        self.assertIn("matches what people predict", path.read_text())
        self.assertTrue((self.lay / "report.json").exists())

    def test_verdict_needs_the_whole_interval(self):
        self.assertIn("unclear", sweep.verdict({"n": 10, "low": -0.3, "high": 0.05}, 0.1))
        self.assertIn("flat", sweep.verdict({"n": 10, "low": -0.05, "high": 0.08}, 0.1))
        self.assertIn("rises", sweep.verdict({"n": 10, "low": 0.15, "high": 0.4}, 0.1))


if __name__ == "__main__":
    unittest.main()
