"""ops/gpu.py's job ownership: a job outlives the `run` that queued it, stays counted, and can be stopped. Tiny shell jobs, a private queue."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(os.environ.get("KOKOPELLI_GPU_SCRIPT", Path(__file__).resolve().parent.parent / "ops" / "gpu.py"))


def wait_until(check, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


class Queue(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.ops = self.root / "out/ops"
        self.env = {**os.environ, "KOKOPELLI_ROOT": str(self.root), "KOKOPELLI_GPU_POLL": "0.1", "KOKOPELLI_GPU_GRACE": "1", "KOKOPELLI_GPU_SAMPLE": "0.2",
                    "KOKOPELLI_SUMMARIZE": "0", "KOKOPELLI_GPU_IGNORE_OUTSIDE": "1", "KOKOPELLI_MACMON": "/nonexistent"}
        self.started = []
        self.addCleanup(self.finish)

    def finish(self):
        for process in self.started:
            if process.poll() is None:
                process.kill()
                process.wait()
        for ticket in self.tickets():
            subprocess.run([sys.executable, str(SCRIPT), "stop", "--name", ticket["name"]], env=self.env, capture_output=True)

    def queue(self, name, *command, extra=()):
        process = subprocess.Popen([sys.executable, str(SCRIPT), "run", "--name", name, "--about", "a test", "--output", "x", "--cwd", str(self.root), *extra, "--", *command],
                                   env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.started.append(process)
        return process

    def tickets(self):
        return [json.loads(path.read_text()) for path in (self.ops / "queue").glob("*.json")] if (self.ops / "queue").is_dir() else []

    def ticket(self, name):
        return next((t for t in self.tickets() if t["name"] == name), None)

    def events(self, name, event):
        path = self.ops / "gpu_ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if row.get("name") == name and row.get("event") == event]

    def test_a_job_exit_code_comes_back_and_the_ledger_says_so(self):
        self.assertEqual(self.queue("a", "sh", "-c", "exit 7").wait(20), 7)
        self.assertEqual(self.events("a", "finished")[0]["exit_code"], 7)
        self.assertFalse(self.events("a", "finished")[0]["stopped"])
        self.assertEqual(self.tickets(), [])

    def test_killing_run_leaves_the_job_running_and_counted(self):
        marker = self.root / "done"
        run = self.queue("long", "sh", "-c", f"sleep 2; touch {marker}")
        self.assertTrue(wait_until(lambda: (self.ticket("long") or {}).get("keeper")))
        keeper = self.ticket("long")["pid"]
        self.assertNotEqual(keeper, run.pid)
        run.kill()
        run.wait()
        next_job = self.queue("next", "true")
        self.assertTrue(wait_until(lambda: (self.ticket("next") or {}).get("waiting_for") == "long has the GPU"))
        self.assertIsNotNone(self.ticket("long"))     # still counted after its queue process died
        self.assertEqual(next_job.wait(30), 0)
        self.assertTrue(marker.exists())
        self.assertEqual(self.events("long", "finished")[0]["exit_code"], 0)

    def test_stop_ends_the_whole_process_group_and_is_recorded(self):
        child = self.root / "child.pid"
        run = self.queue("s", "sh", "-c", f"sleep 300 & echo $! > {child}; wait")
        self.assertTrue(wait_until(child.exists))
        self.assertTrue(wait_until(lambda: child.read_text().strip()))
        pid = int(child.read_text())
        done = subprocess.run([sys.executable, str(SCRIPT), "stop", "--name", "s"], env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        run.wait(20)
        self.assertTrue(self.events("s", "finished")[0]["stopped"])
        self.assertTrue(wait_until(lambda: subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip() in ("", "Z")))

    def test_a_job_that_ignores_sigterm_is_killed_after_the_grace(self):
        run = self.queue("stubborn", "sh", "-c", "trap '' TERM; while :; do sleep 0.1; done")
        self.assertTrue(wait_until(lambda: (self.ticket("stubborn") or {}).get("keeper")))
        subprocess.run([sys.executable, str(SCRIPT), "stop", "--name", "stubborn"], env=self.env, capture_output=True)
        run.wait(20)
        self.assertTrue(self.events("stubborn", "finished")[0]["stopped"])

    def test_the_time_limit_gives_124(self):
        self.assertEqual(self.queue("slow", "sleep", "60", extra=("--max-hours", "0.0003")).wait(30), 124)
        self.assertTrue(self.events("slow", "finished")[0]["timed_out"])

    def test_a_job_that_asks_for_too_much_memory_waits_and_says_why(self):
        run = self.queue("big", "true", extra=("--gb", "100000"))
        self.assertTrue(wait_until(lambda: "GB free" in (self.ticket("big") or {}).get("waiting_for", ""), 30))
        run.terminate()

    def test_lower_numbers_still_go_first(self):
        blocker = self.queue("first", "sleep", "1", extra=("--priority", "50"))
        self.assertTrue(wait_until(lambda: self.events("first", "started")))
        late = self.queue("late", "true", extra=("--priority", "60"))
        self.assertTrue(wait_until(lambda: self.ticket("late")))
        urgent = self.queue("urgent", "true", extra=("--priority", "5"))
        for process in (blocker, late, urgent):
            process.wait(30)
        self.assertLess(self.events("urgent", "started")[0]["at"], self.events("late", "started")[0]["at"])


class OutsideJobs(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("gpu_under_test", SCRIPT)
        self.gpu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gpu)

    def found(self, table, tickets=()):
        with mock.patch.dict(os.environ, {"KOKOPELLI_GPU_IGNORE_OUTSIDE": ""}), mock.patch.object(self.gpu, "process_table", lambda: table), \
                mock.patch.object(self.gpu, "tickets", lambda: list(tickets)):
            return [pid for pid, _ in self.gpu.outside_model_jobs()]

    def test_a_big_python_counts_whatever_it_is_called(self):
        self.assertEqual(self.found([{"pid": 5, "parent": 1, "gb": 19.0, "command": "/x/Python -m exp1.smoke"}]), [5])

    def test_a_small_python_and_a_big_app_do_not(self):
        table = [{"pid": 5, "parent": 1, "gb": 0.2, "command": "/x/Python -m life.panel"}, {"pid": 6, "parent": 1, "gb": 30.0, "command": "/Applications/Chrome"}]
        self.assertEqual(self.found(table), [])

    def test_a_job_under_a_running_ticket_is_not_outside(self):
        table = [{"pid": 4, "parent": 1, "gb": 0.1, "command": "python ops/gpu.py keep"}, {"pid": 5, "parent": 4, "gb": 0.1, "command": "caffeinate"}, {"pid": 6, "parent": 5, "gb": 19.0, "command": "/x/Python -m exp1.run"}]
        self.assertEqual(self.found(table, [{"pid": 4, "running": True}]), [])

    def test_footprint_sees_this_process(self):
        self.assertGreater(self.gpu.footprint_gb(os.getpid()), 0)
        self.assertIsNone(self.gpu.footprint_gb(99999999))

    def test_the_summary_leaves_out_what_it_never_read(self):
        self.assertEqual(self.gpu.machine_summary([{"job_gb": 1.0}, {"job_gb": 3.0}]), {"peak_job_gb": 3.0})
        summary = self.gpu.machine_summary([{"swap_gb": 1.0, "gpu_busy": 0.5, "watts": 10, "gpu_temp": 60}, {"swap_gb": 4.0, "gpu_busy": 1.0, "watts": 20, "gpu_temp": 70}])
        self.assertEqual((summary["peak_swap_gb"], summary["swap_grew_gb"], summary["gpu_busy_mean"], summary["watts_mean"], summary["gpu_temp_max"]), (4.0, 3.0, 0.75, 15.0, 70.0))


if __name__ == "__main__":
    unittest.main()
