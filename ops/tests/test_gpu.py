import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

GPU = Path(__file__).resolve().parents[1] / "gpu.py"


class GpuQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, "KOKOPELLI_ROOT": str(self.root),
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

    def test_giving_up_is_reported(self):
        holder = self.start("holder", 0, "sleep", "2")
        time.sleep(0.4)
        waiter = self.start("waiter", 1, "true", extra=("--give-up-hours", "0.0001"))
        self.assertEqual(waiter.wait(timeout=20), 3)
        holder.wait(timeout=20)


if __name__ == "__main__":
    unittest.main()
