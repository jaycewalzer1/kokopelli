import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

GPU = Path(__file__).resolve().parents[1] / "gpu.py"
CODE = Path(os.environ.get("KOKOPELLI_CODE", Path.home() / "Desktop/kokopelli"))


class GpuQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, "KOKOPELLI_ROOT": str(self.root), "KOKOPELLI_CODE": str(CODE),
                    "KOKOPELLI_PACE_CONFIG": str(self.root / "no_pace.json"),  # never a real PACE account in a test
                    "KOKOPELLI_GPU_IGNORE_OUTSIDE": "1", "KOKOPELLI_GPU_POLL": "0.1"}

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, name, priority, *command, extra=()):
        return subprocess.Popen([sys.executable, str(GPU), "run", "--name", name, "--priority", str(priority),
                                 *extra, "--", *command], env=self.env, stdout=subprocess.DEVNULL)

    def events(self):
        return [json.loads(line) for line in (self.root / "out/ops/gpu_ledger.jsonl").read_text().splitlines()]

    def test_lower_priority_number_goes_first_and_jobs_never_overlap(self):
        holder = self.start("holder", 0, "sleep", "1")
        time.sleep(0.4)
        late = self.start("late", 50, "true")
        time.sleep(0.2)
        urgent = self.start("urgent", 10, "true")
        for job in (holder, late, urgent):
            self.assertEqual(job.wait(timeout=20), 0)
        order = [e["name"] for e in self.events() if e["event"] == "started"]
        self.assertEqual(order, ["holder", "urgent", "late"])
        running = 0
        for event in self.events():
            running += {"started": 1, "finished": -1}.get(event["event"], 0)
            self.assertLessEqual(running, 1)

    def test_job_exit_code_reaches_the_caller_and_the_ledger(self):
        self.assertEqual(self.start("bad", 1, "sh", "-c", "exit 7").wait(timeout=20), 7)
        finished = [e for e in self.events() if e["event"] == "finished"][0]
        self.assertEqual(finished["exit_code"], 7)

    def test_a_hung_job_is_stopped_and_releases_the_turn(self):
        hung = self.start("hung", 1, "sleep", "60", extra=("--max-hours", "0.0002"))
        self.assertEqual(hung.wait(timeout=30), 124)
        self.assertTrue([e for e in self.events() if e["event"] == "finished"][0]["timed_out"])
        self.assertEqual(self.start("next", 1, "true").wait(timeout=20), 0)

    def test_a_dead_ticket_does_not_block_the_queue(self):
        queue = self.root / "out/ops/queue"
        queue.mkdir(parents=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (queue / "dead.json").write_text(json.dumps({"id": "dead", "name": "dead", "priority": 0, "pid": dead.pid,
                                                     "queued_at": 0, "running": True}))
        self.assertEqual(self.start("next", 1, "true").wait(timeout=20), 0)

    def test_moving_a_waiting_job_changes_the_order(self):
        holder = self.start("holder", 0, "sleep", "2")
        time.sleep(0.4)
        first = self.start("first", 10, "true")
        second = self.start("second", 20, "true")
        time.sleep(0.4)
        subprocess.run([sys.executable, str(GPU), "move", "--name", "second", "--priority", "5"], env=self.env, check=True, stdout=subprocess.DEVNULL)
        for job in (holder, first, second):
            self.assertEqual(job.wait(timeout=20), 0)
        self.assertEqual([e["name"] for e in self.events() if e["event"] == "started"], ["holder", "second", "first"])

    def test_giving_up_is_reported(self):
        holder = self.start("holder", 0, "sleep", "2")
        time.sleep(0.4)
        waiter = self.start("waiter", 1, "true", extra=("--give-up-hours", "0.0001"))
        self.assertEqual(waiter.wait(timeout=20), 3)
        holder.wait(timeout=20)


    def gpu(self, *args):
        return subprocess.run([sys.executable, str(GPU), *args], env=self.env, capture_output=True, text=True)

    def test_a_job_without_a_pace_command_is_refused_for_pace_and_never_runs(self):
        marker = self.root / "ran"
        self.assertEqual(self.start("mac_only", 1, "touch", str(marker), extra=("--where", "pace")).wait(timeout=20), 2)
        self.assertFalse(marker.exists())

    def test_pace_that_cant_submit_fails_loudly_instead_of_running_on_the_mac(self):
        marker = self.root / "ran"
        job = self.start("cloud", 1, "touch", str(marker), extra=("--where", "pace", "--pace-command", "true"))
        self.assertEqual(job.wait(timeout=20), 2)
        self.assertFalse(marker.exists())
        finished = [e for e in self.events() if e["event"] == "finished"][0]
        self.assertEqual((finished["where"], finished["exit_code"]), ("pace", 2))
        log = Path(finished["log"]).read_text()
        self.assertIn("PACE isn't set up", log)

    def test_the_default_only_sends_jobs_that_have_a_pace_command(self):
        self.gpu("default", "--to", "pace")
        self.assertEqual(self.start("mac_only", 1, "true").wait(timeout=20), 0)
        self.assertEqual(self.start("portable", 1, "true", extra=("--pace-command", "true")).wait(timeout=20), 2)
        started = {e["name"]: e["where"] for e in self.events() if e["event"] == "started"}
        self.assertEqual(started, {"mac_only": "local", "portable": "pace"})

    def test_a_waiting_job_sent_to_pace_leaves_the_mac_line_at_once(self):
        holder = self.start("holder", 0, "sleep", "2")
        time.sleep(0.4)
        moved = self.start("moved", 10, "true", extra=("--pace-command", "true"))
        stays = self.start("stays", 20, "true")
        time.sleep(0.4)
        self.assertEqual(self.gpu("where", "--name", "stays", "--to", "pace").returncode, 1, "no PACE command, so it can't move")
        self.assertEqual(self.gpu("where", "--name", "moved", "--to", "pace").returncode, 0)
        self.assertEqual(moved.wait(timeout=5), 2, "left before the holder finished")
        self.assertTrue(holder.poll() is None)
        for job in (holder, stays):
            self.assertEqual(job.wait(timeout=20), 0)
        self.assertEqual([e["name"] for e in self.events() if e["event"] == "started" and e["where"] == "local"], ["holder", "stays"])

    def test_a_ticket_from_before_where_existed_is_local(self):
        queue = self.root / "out/ops/queue"
        queue.mkdir(parents=True)
        old = subprocess.Popen(["sleep", "1"])
        (queue / "old.json").write_text(json.dumps({"id": "old", "name": "old", "priority": 0, "pid": old.pid, "queued_at": 0, "running": True}))
        status = self.gpu("status").stdout
        self.assertIn("RUNNING", status)
        self.assertNotIn("PACE", status)
        old.wait()  # reaped, so its pid is really gone and the queue moves on
        self.assertEqual(self.start("next", 1, "true").wait(timeout=20), 0)


if __name__ == "__main__":
    unittest.main()
