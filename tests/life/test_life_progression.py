"""The progression page's plan edits, and that only the panel's own page can make them."""
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from kokopelli.life import progression
from kokopelli.life.panel import make_server


class ProgressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "plan.json"
        shutil.copy(progression.PLAN, self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_real_plan_has_unique_ids_and_known_statuses(self):
        data = progression.plan()
        ids = [t["id"] for p in data["phases"] for t in p["tasks"]] + [p["id"] for p in data["phases"]] + [d["id"] for d in data["decisions"]]
        self.assertEqual(len(ids), len(set(ids)))
        goals = {g["id"] for g in data["goals"]}
        for phase in data["phases"]:
            self.assertTrue(set(phase["feeds"]) <= goals, phase["id"])
            for task in phase["tasks"]:
                self.assertIn(task["status"], progression.STATUSES)

    def test_a_task_status_and_note_are_saved(self):
        progression.edit({"kind": "task", "id": "p0t1", "status": "doing", "note": "reading"}, self.path)
        task = progression.plan(self.path)["phases"][0]["tasks"][0]
        self.assertEqual((task["status"], task["note"]), ("doing", "reading"))

    def test_a_decision_answer_is_saved(self):
        progression.edit({"kind": "decision", "id": "d1", "answer": "Consensus"}, self.path)
        self.assertEqual(progression.plan(self.path)["decisions"][0]["answer"], "Consensus")

    def test_refuses_unknown_ids_kinds_and_statuses(self):
        before = self.path.read_text()
        for body in ({"kind": "task", "id": "nope", "status": "done"}, {"kind": "decision", "id": "nope"},
                     {"kind": "phase", "id": "p0"}, {"kind": "task", "id": "p0t1", "status": "finished"}):
            with self.assertRaises((KeyError, ValueError)):
                progression.edit(body, self.path)
        self.assertEqual(self.path.read_text(), before)


class ProgressionRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        plan = Path(self.temp.name) / "plan.json"
        shutil.copy(progression.PLAN, plan)
        self.patch = mock.patch.object(progression, "PLAN", plan)
        self.patch.start()
        self.server = make_server(str(Path(self.temp.name) / "life.db"), 0)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.temp.cleanup()

    def _post(self, headers):
        request = urllib.request.Request(f"{self.base}/api/progression/edit", method="POST", headers=headers,
                                         data=json.dumps({"kind": "task", "id": "p0t1", "status": "done"}).encode())
        return urllib.request.urlopen(request)

    def test_the_page_and_plan_are_served(self):
        self.assertIn(b"progression.js", urllib.request.urlopen(f"{self.base}/progression").read())
        self.assertIn("phases", json.loads(urllib.request.urlopen(f"{self.base}/api/progression").read()))

    def test_only_this_panels_page_can_edit(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post({"Content-Type": "application/json", "Origin": "http://evil.example"})
        self.assertEqual(caught.exception.code, 403)
        body = json.loads(self._post({"Content-Type": "application/json", "Origin": self.base}).read())
        self.assertEqual(body["phases"][0]["tasks"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
