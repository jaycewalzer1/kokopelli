"""Drives the dev panel's server over HTTP in mock mode."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from life.panel import divergences, ensure_run, make_server
from life.store import Store

SEED = {"prompt": "test", "birth_date": "1990-03-14", "place": "Atlanta", "rng_seed": 7,
        "family": [["Ana", "mother"]], "anchors": [["1992-03-16T10:20:45", "a storm"]], "hidden_target": "CANARY"}
ANCHOR_DAY = "day:1992-03-16T00:00:00"


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.temp.name) / "life.db", port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.run_id = self.post("/api/runs", SEED)["run_id"]

    def tearDown(self):
        self.post("/api/stop", {"run": self.run_id})
        self.wait()
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def get(self, path, **params):
        with urllib.request.urlopen(f"{self.base}{path}?{urllib.parse.urlencode(params)}") as response:
            return json.load(response)

    def post(self, path, body):
        request = urllib.request.Request(self.base + path, json.dumps(body).encode(), method="POST")
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def wait(self):
        while self.get("/api/status", run=self.run_id)["running"]:
            time.sleep(0.01)

    def test_sidebar_links_both_views(self):
        for path, current in (("/", b'<a href="/" aria-current="page">'), ("/training", b'<a href="/training" aria-current="page">')):
            with urllib.request.urlopen(self.base + path) as response:
                page = response.read()
            self.assertIn(current, page)
            self.assertIn(b'href="/training"', page)
            self.assertIn(b'href="/"', page)

    def test_training_routes_are_read_only_and_refuse_unknown_runs(self):
        self.assertIn("runs", self.get("/api/training/runs"))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/training/run", name="../../etc")
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/training/run", {"name": "x"})
        self.assertEqual(caught.exception.code, 404)

    def test_page_loads(self):
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertIn(b"Life generator", response.read())

    def test_page_scripts_are_served(self):
        for name in ("app.js", "feed.js", "inspector.js", "layout.js", "model.js", "render-svg.js", "rulers.js"):
            with urllib.request.urlopen(f"{self.base}/static/{name}") as response:
                self.assertIn("javascript", response.headers["Content-Type"])

    def test_stylesheets_are_served(self):
        for name in ("design.css", "panel.css"):
            with urllib.request.urlopen(f"{self.base}/static/{name}") as response:
                self.assertIn("text/css", response.headers["Content-Type"])

    def test_the_default_seed_makes_a_run(self):
        defaults = self.get("/api/defaults")
        self.assertIsInstance(self.post("/api/runs", defaults)["run_id"], int)

    def test_ensure_run_fills_an_empty_database_once(self):
        db = Path(self.temp.name) / "new" / "demo.db"
        ensure_run(db, writes=50)
        ensure_run(db, writes=50)
        store = Store(db)
        self.addCleanup(store.close)
        self.assertEqual(len(store.runs()), 1)
        self.assertGreater(store.last_seq(store.runs()[0]["run_id"]), 50)

    def test_static_route_cannot_leave_its_folder(self):
        for path in ("/static/../panel.py", "/static/%2e%2e/panel.py", "/static/missing.js"):
            with self.subTest(path), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(caught.exception.code, 404)

    def test_step_opens_the_life_then_a_year(self):
        self.post("/api/step", {"run": self.run_id})
        self.post("/api/step", {"run": self.run_id})
        status = self.get("/api/status", run=self.run_id)
        self.assertEqual(status["counts"]["opened"], 2)
        self.assertEqual(status["real_llm_calls"], 0)

    def test_calendar_starts_one_tier_below_each_year(self):
        calendar = self.get("/api/calendar", run=self.run_id)
        years = calendar["children"][calendar["life"]["id"]]
        self.assertEqual(years[0]["label"], "Age 2")
        for year in years:
            self.assertEqual(calendar["children"][year["id"]][0]["level"], "season")

    def test_each_year_sits_under_the_hub_for_the_age_it_starts_at(self):
        calendar = self.get("/api/calendar", run=self.run_id)
        years = {year["label"]: year for year in calendar["children"][calendar["life"]["id"]]}
        self.assertEqual(years["Age 5"]["hub"], 0)
        self.assertEqual(years["Kindergarten"]["hub"], 0)
        self.assertEqual(years["Grade 1"]["hub"], 1)
        self.assertEqual(years["Grade 7"]["hub"], 2)
        self.assertEqual(years["College 1"]["hub"], 3)
        self.assertEqual(len(calendar["hubs"]), 4)

    def test_calendar_returns_future_slots_down_to_the_minute(self):
        day = self.get("/api/calendar", run=self.run_id, nodes=ANCHOR_DAY)[ANCHOR_DAY]
        self.assertEqual(len(day), 24)
        minutes = self.get("/api/calendar", run=self.run_id, nodes="min5:1992-03-16T10:20:00")
        self.assertEqual(len(minutes["min5:1992-03-16T10:20:00"]), 5)

    def test_feed_is_every_write_in_order(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        feed = self.get("/api/feed", run=self.run_id)
        self.assertEqual([event["seq"] for event in feed], list(range(1, len(feed) + 1)))
        self.assertEqual(len(feed), self.get("/api/status", run=self.run_id)["last_seq"])
        kinds = {event["type"] for event in feed}
        self.assertLessEqual({"node_opened", "node_closed", "choice_point", "agent_action", "state_change"}, kinds)

    def test_feed_continues_from_a_sequence_number(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        feed = self.get("/api/feed", run=self.run_id)
        self.assertEqual(self.get("/api/feed", run=self.run_id, after=feed[9]["seq"]), feed[10:])

    def test_polling_during_a_run_never_skips_a_write(self):
        self.post("/api/run", {"run": self.run_id, "generator_calls": 3000})
        seqs = []
        while True:
            running = self.get("/api/status", run=self.run_id)["running"]
            events = self.get("/api/feed", run=self.run_id, after=seqs[-1] if seqs else 0)
            seqs += [event["seq"] for event in events]
            if not running and not events:
                break
        self.assertGreater(len(seqs), 3000)
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_a_choice_point_comes_right_before_its_action(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        feed = self.get("/api/feed", run=self.run_id)
        actions = [i for i, event in enumerate(feed) if event["type"] == "agent_action"]
        self.assertTrue(actions)
        for i in actions:
            self.assertEqual(feed[i - 1]["type"], "choice_point")
            self.assertIn(feed[i]["verb"], feed[i - 1]["options"])

    def test_generate_through_a_node_then_view_it(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        node = self.get("/api/node", run=self.run_id, node=ANCHOR_DAY)
        self.assertEqual(node["status"], "closed")
        self.assertIsNotNone(node["opening"])
        self.assertIsNotNone(node["closing"])
        self.assertTrue(node["events"])

    def test_a_far_target_warns_before_it_runs(self):
        answer = self.post("/api/run", {"run": self.run_id, "until": "year:2012-09-01T00:00:00"})
        self.assertIn("warn", answer)
        self.assertEqual(self.get("/api/status", run=self.run_id)["counts"]["opened"], 0)

    def test_fork_makes_a_new_run_and_leaves_the_old_one(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        before = self.get("/api/status", run=self.run_id)["counts"]
        fork = self.post("/api/fork", {"run": self.run_id, "node": ANCHOR_DAY})["run_id"]
        self.assertEqual(self.get("/api/status", run=self.run_id)["counts"], before)
        self.assertEqual(self.get("/api/node", run=fork, node=ANCHOR_DAY)["status"], "unopened")

    def test_budget_stops_a_run(self):
        self.post("/api/run", {"run": self.run_id, "generator_calls": 5})
        self.wait()
        status = self.get("/api/status", run=self.run_id)
        self.assertEqual(status["reason"], "budget")
        self.assertEqual(status["budget"]["generator_calls"], 0)

    def test_panel_never_exposes_the_hidden_target(self):
        self.post("/api/run", {"run": self.run_id, "until": ANCHOR_DAY})
        self.wait()
        seen = [self.get("/api/status", run=self.run_id), self.get("/api/runs"), self.get("/api/feed", run=self.run_id),
                self.get("/api/calendar", run=self.run_id), self.get("/api/node", run=self.run_id, node=ANCHOR_DAY)]
        self.assertNotIn("CANARY", json.dumps(seen))

    def test_an_unknown_node_is_a_clean_error(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/node", run=self.run_id, node="day:1985-01-01T00:00:00")
        self.assertEqual(caught.exception.code, 400)

    def test_divergence_marks_only_pressures_that_went_against_their_odds(self):
        opening = {"pressures": [{"id": "likely", "text": "a", "odds": 0.9}, {"id": "unlikely", "text": "b", "odds": 0.1},
                                 {"id": "expected", "text": "c", "odds": 0.8}]}
        closing = {"pressures": [{"id": "likely", "outcome": "didnt_arise"}, {"id": "unlikely", "outcome": "met"},
                                 {"id": "expected", "outcome": "avoided"}]}
        self.assertEqual([item["id"] for item in divergences(opening, closing)], ["likely", "unlikely"])


if __name__ == "__main__":
    unittest.main()
