"""The live agent view's routes, over HTTP, on run folders made up in a temporary directory."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from life import city_live
from life.panel import make_server

TRANSCRIPT = """# A life in the city — 2026-11-06 10:38

**Who:** You are Mara.

**Situation:** Bring the bread.

**Vision:** unreal


### 14:00:00 — step 0
![](frames/0000.png)

*I need the bread, so I'll head north.*

**→** `{"type": "go_to", "place": "fern_bakery"}`
_(arrived at Rise Bakery)_

### 14:01:15 — step 2
![](frames/0002.png)

*Tomas is right here.*

**→** `{"type": "say", "text": "Hi Tomas"}`
> **Tomas:** Your bread's ready.

---
Run folder: /somewhere
"""
EVENTS = [{"t": 0, "kind": "decision", "raw": "{}"}, {"t": 0, "kind": "outcome", "at": [10.0, 20.0]},
          {"t": 15, "kind": "outcome", "at": [10.0, 30.0]}, {"t": 30, "kind": "outcome", "at": [10.0, 40.0]}]
PNG = b"\x89PNG\r\n\x1a\nfake"


class CityLiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.saved = city_live.RUNS
        city_live.RUNS = root / "city_agents"
        old = city_live.RUNS / "20261106-103812"
        (old / "frames").mkdir(parents=True)
        (old / "transcript.md").write_text(TRANSCRIPT)
        (old / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in EVENTS) + "not json\n")
        (old / "frames" / "0000.png").write_bytes(PNG)
        new = city_live.RUNS / "20261106-120000"
        (new / "frames").mkdir(parents=True)
        (new / "transcript.md").write_text(TRANSCRIPT.split("\n### 14:01")[0])
        (new / "frames" / "live.png").write_bytes(PNG)
        self.live = {"run": new.name, "updated": datetime.now().isoformat(timespec="seconds"), "running": True, "step": 3,
                     "clock": "14:00:45", "frame": "frames/live.png", "agent": {"x_m": 1, "y_m": 2, "yaw": 90, "carrying": None, "place": None},
                     "npcs": [{"id": "tomas", "name": "Tomas", "role": "baker", "x_m": 5, "y_m": 5}], "objects": [], "route": [[1, 9]],
                     "goal": "fern_bakery", "last_thought": "Off I go.", "last_action": {"type": "go_to", "place": "fern_bakery"},
                     "last_result": "", "heard": [], "diary": []}
        (new / "live.json").write_text(json.dumps(self.live))
        (root / "secret.png").write_bytes(b"secret")
        self.server = make_server(root / "life.db", port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        city_live.RUNS = self.saved
        self.temp.cleanup()

    def get(self, path, **params):
        with urllib.request.urlopen(f"{self.base}{path}?{urllib.parse.urlencode(params)}") as response:
            return json.load(response)

    def test_page_is_in_the_sidebar(self):
        with urllib.request.urlopen(self.base + "/city-live") as response:
            page = response.read()
        self.assertIn(b'<a href="/city-live" aria-current="page">', page)
        with urllib.request.urlopen(self.base + "/moodboard") as response:
            self.assertIn(b'href="/city-live"', response.read())
        with urllib.request.urlopen(self.base + "/static/city-draw.js") as response:
            self.assertIn(b"export function drawCity", response.read())

    def test_runs_are_newest_first_and_only_a_fresh_running_one_is_live(self):
        runs = self.get("/api/city-live/runs")["runs"]
        self.assertEqual([run["run"] for run in runs], ["20261106-120000", "20261106-103812"])
        self.assertEqual([run["live"] for run in runs], [True, False])
        self.assertEqual(runs[1]["decisions"], 2)
        # One that says it's running but hasn't written for a while has stopped.
        stale = {**self.live, "updated": "2026-11-06T09:00:00"}
        (city_live.RUNS / "20261106-120000" / "live.json").write_text(json.dumps(stale))
        self.assertFalse(self.get("/api/city-live/runs")["runs"][0]["live"])

    def test_a_live_run_reports_its_live_json(self):
        body = self.get("/api/city-live/run", run="20261106-120000")
        self.assertTrue(body["live"])
        self.assertEqual(body["state"]["npcs"][0]["name"], "Tomas")
        self.assertTrue(body["state"]["has_live_frame"])
        self.assertEqual(body["state"]["who"], "You are Mara.")

    def test_an_old_run_is_worked_out_from_its_transcript_and_events(self):
        body = self.get("/api/city-live/run", run="20261106-103812")
        self.assertFalse(body["live"])
        first, second = body["decisions"]
        self.assertEqual((first["clock"], first["step"], first["frame"]), ("14:00:00", 0, "0000.png"))
        self.assertEqual(first["action"], {"type": "go_to", "place": "fern_bakery"})
        self.assertEqual(first["notes"], ["arrived at Rise Bakery"])
        self.assertTrue(first["has_frame"])
        self.assertFalse(second["has_frame"])
        self.assertEqual(second["replies"], [{"name": "Tomas", "text": "Your bread's ready."}])
        self.assertEqual(body["trail"], [[10.0, 20.0], [10.0, 30.0], [10.0, 40.0]])
        state = body["state"]
        self.assertTrue(state["derived"])
        self.assertEqual((state["agent"]["x_m"], state["agent"]["y_m"], state["agent"]["yaw"]), (10.0, 40.0, 90.0))
        self.assertEqual(state["last_thought"], "Tomas is right here.")

    def test_unknown_runs_are_refused(self):
        for run in ("nope", "../../etc", "20261106-999999", ""):
            with self.subTest(run), self.assertRaises(urllib.error.HTTPError) as caught:
                self.get("/api/city-live/run", run=run)
            self.assertEqual(caught.exception.code, 400)

    def test_frames_come_only_from_a_runs_own_frames_folder(self):
        with urllib.request.urlopen(f"{self.base}/api/city-live/frame?run=20261106-120000&name=live.png&v=1") as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(), PNG)
        for query in ("", "?run=20261106-120000", "?run=20261106-120000&name=0001.png", "?run=20261106-120000&name=../../secret.png",
                      "?run=..&name=secret.png", "?run=20261106-120000&name=%2E%2E%2Flive.json", "?run=20261106-120000&name=live.json",
                      "?run=/etc&name=passwd"):
            with self.subTest(query), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + "/api/city-live/frame" + query)
            self.assertEqual(caught.exception.code, 404)

    def test_routes_are_read_only(self):
        for path in ("/api/city-live/runs", "/api/city-live/run", "/api/city-live/frame"):
            with self.subTest(path), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(self.base + path, b"{}", {"Content-Type": "application/json"}, method="POST"))
            self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
