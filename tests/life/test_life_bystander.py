"""The benchmarks view (armed bystander, gift card): listing runs, giving one run's decisions in full, and reading nothing a
listing didn't find."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from experiments.bystander import run, scene
from experiments.giftcard import run as giftcard_run
from experiments.giftcard import scene as giftcard_scene
from kokopelli.life import benchmarks, bystander
from kokopelli.life.panel import make_server


class BystanderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.out = root / "bystander"
        run.run(cls.out / "mock_4", seeds=4, mock=True, log=lambda line: None)
        (cls.out / "not_a_run").mkdir()
        (root / "elsewhere").mkdir()
        (root / "elsewhere" / "run.json").write_text(json.dumps({"model": "outside"}))
        giftcard_run.run(root / "giftcard" / "mock_2", seeds=2, mock=True, log=lambda line: None)
        cls.patch = mock.patch.object(bystander, "OUT", cls.out)
        cls.patch.start()
        cls.patch_benchmarks = mock.patch.object(benchmarks, "OUT", root)
        cls.patch_benchmarks.start()
        cls.server = make_server(root / "life.db", port=0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.patch.stop()
        cls.patch_benchmarks.stop()
        cls.temp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path)

    def test_the_listing_has_the_run_and_says_it_isnt_a_real_model(self):
        body = json.load(self.get("/api/bystander/runs"))
        self.assertEqual([(r["id"], r["count"], r["real"], r["model"]) for r in body["runs"]], [("mock_4", 8, False, "mock")])
        self.assertIn("ui_version", body)

    def test_a_run_gives_every_decision_in_full(self):
        body = json.load(self.get("/api/bystander/run?run=mock_4"))
        self.assertEqual(body["system"], scene.WHO)
        self.assertEqual({(d["scene"], d["seed"]) for d in body["decisions"]}, {(name, seed) for name in scene.SCENES for seed in range(4)})
        shot = next(d for d in body["decisions"] if d["scene"] == "threat" and d["seed"] == 0)
        self.assertEqual(shot["prompt"], scene.prompt("threat", 0))
        self.assertEqual((shot["raw"], shot["outcome"], shot["action"]), (scene.MOCK[0], "shot_stranger", {"type": "shoot", "target": "stranger"}))
        refused = next(d for d in body["decisions"] if d["seed"] == 3)
        self.assertEqual((refused["valid"], refused["outcome"], refused["raw"]), (False, "invalid", scene.MOCK[3]))
        self.assertTrue(refused["error"])

    def test_a_run_still_writing_is_read_up_to_its_last_whole_line(self):
        folder = self.out / "half"
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({"model": "mock", "system": "x"}))
        (folder / "results.jsonl").write_text(json.dumps({"scene": "threat", "seed": 0, "outcome": "hid"}) + '\n{"scene": "pho')
        try:
            self.assertEqual(len(bystander.run("half")["decisions"]), 1)
        finally:
            (folder / "results.jsonl").unlink()
            (folder / "run.json").unlink()
            folder.rmdir()

    def test_nothing_outside_the_listing_is_read(self):
        for name in ("../elsewhere", "not_a_run", "missing", ""):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/api/bystander/run?run={name}")
            self.assertEqual(caught.exception.code, 400, name)

    def test_the_benchmarks_list_both_with_their_runs(self):
        body = json.load(self.get("/api/benchmarks"))
        self.assertEqual([(b["id"], b["runs"]) for b in body["benches"]], [("bystander", 1), ("giftcard", 1)])

    def test_a_benchmark_run_gives_every_decision_in_full(self):
        listed = json.load(self.get("/api/benchmarks/runs?bench=giftcard"))
        self.assertEqual([(r["id"], r["count"], r["real"]) for r in listed["runs"]], [("mock_2", 2 * len(giftcard_scene.SCENES), False)])
        body = json.load(self.get("/api/benchmarks/run?bench=giftcard&run=mock_2"))
        self.assertEqual(body["system"], giftcard_scene.WHO)
        first = next(d for d in body["decisions"] if d["scene"] == "record_16" and d["seed"] == 0)
        self.assertEqual((first["prompt"], first["outcome"]), (giftcard_scene.prompt("record_16", 0), "returned_with_sam"))
        same = json.load(self.get("/api/benchmarks/run?bench=bystander&run=mock_4"))
        self.assertEqual(same["count"], 8)

    def test_nothing_outside_a_benchmark_is_read(self):
        for query in ("bench=../elsewhere&run=x", "bench=giftcard&run=../bystander/mock_4", "bench=nope&run=mock_2", "bench=giftcard&run=missing"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/api/benchmarks/run?{query}")
            self.assertEqual(caught.exception.code, 400, query)

    def test_the_page_is_in_every_sidebar(self):
        for path in ("/benchmarks", "/bystander"):   # the old address still opens it
            with self.get(path) as response:
                self.assertIn(b'<a href="/benchmarks" aria-current="page">', response.read())
        for page in ("/", "/worlds", "/city-live", "/queue", "/sensations", "/training", "/architecture", "/moodboard", "/exp1"):
            with self.get(page) as response:
                self.assertIn(b'href="/benchmarks"', response.read(), page)


if __name__ == "__main__":
    unittest.main()
