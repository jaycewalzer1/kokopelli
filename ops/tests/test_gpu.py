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
                    "KOKOPELLI_GPU_IGNORE_OUTSIDE": "1", "KOKOPELLI_SUMMARIZE": "0", "KOKOPELLI_GPU_POLL": "0.1"}

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, name, priority, *command, extra=(), about="A test job.", output="out/test"):
        described = (["--about", about] if about is not None else []) + (["--output", output] if output is not None else [])
        return subprocess.Popen([sys.executable, str(GPU), "run", "--name", name, "--priority", str(priority), "--cwd", str(self.root),
                                 *described, *extra, "--", *command], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    def test_a_job_without_a_description_or_an_output_is_never_queued(self):
        marker = self.root / "ran"
        for missing in ({"about": None}, {"about": "   "}, {"about": "x" * 401}, {"output": None}):
            self.assertEqual(self.start("vague", 1, "touch", str(marker), **missing).wait(timeout=20), 2, missing)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "out/ops/gpu_ledger.jsonl").exists())

    def test_the_description_and_outputs_reach_the_ledger(self):
        self.assertEqual(self.start("described", 1, "true", about="Checks  that\nthe tab can say what this is.", output="runs/x").wait(timeout=20), 0)
        queued = [e for e in self.events() if e["event"] == "queued"][0]
        self.assertEqual(queued["about"], "Checks that the tab can say what this is.")
        self.assertEqual(queued["outputs"], [str((self.root / "runs/x").resolve())])

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

    def test_status_says_idle_and_sorts_finished_jobs_by_how_they_ended(self):
        self.assertEqual(self.gpu("status").stdout, "idle\n")
        ledger = self.root / "out/ops/gpu_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        endings = [(0, False), (0, False), (1, False), (-15, False), (-15, True), (75, False)]
        ledger.write_text("".join(json.dumps({"event": "finished", "exit_code": code, "stopped": stopped}) + "\n"
                                  for code, stopped in endings) + "not json\n")
        self.assertEqual(self.gpu("status").stdout, "idle\n")
        queue = self.root / "out/ops/queue"
        queue.mkdir(parents=True, exist_ok=True)
        job = subprocess.Popen(["sleep", "2"])
        (queue / "job.json").write_text(json.dumps({"id": "job", "name": "job", "priority": 0, "pid": job.pid, "queued_at": 0, "running": True}))
        status = self.gpu("status").stdout
        job.kill()
        job.wait()
        self.assertIn("RUNNING", status)
        self.assertEqual(status.splitlines()[-1], "finished 2 ok, 2 failed, 1 stopped, 1 yielded(75)")

    def test_check_fails_a_bad_folder_or_command_in_seconds(self):
        started = time.time()
        self.assertEqual(self.gpu("check", "--cwd", str(self.root / "missing"), "--", "true").returncode, 1)
        missing = self.gpu("check", "--cwd", str(self.root), "--", "env PYTHONPATH=.", "python3", "-m", "json")  # the 127 of 2026-11-05
        self.assertEqual(missing.returncode, 1)
        self.assertIn("command not found", missing.stderr)
        self.assertLess(time.time() - started, 5)

    def test_check_looks_up_modules_and_scripts_in_the_jobs_own_python(self):
        (self.root / "job.py").write_text("print('hi')\n")
        (self.root / "broken.py").write_text("def (:\n")
        python = sys.executable
        self.assertEqual(self.gpu("check", "--cwd", str(self.root), "--", python, "-u", "job.py").stdout, "ok\n")
        self.assertEqual(self.gpu("check", "--cwd", str(self.root), "--", "env", "A=1", python, "-m", "json.tool").returncode, 0)
        self.assertIn("can't find module", self.gpu("check", "--cwd", str(self.root), "--", python, "-m", "no_such_module_here").stderr)
        self.assertIn("script not found", self.gpu("check", "--cwd", str(self.root), "--", python, "nope.py").stderr)
        self.assertIn("doesn't compile", self.gpu("check", "--cwd", str(self.root), "--", python, "broken.py").stderr)
        wrapped = self.gpu("check", "--cwd", str(self.root), "--", "python3", "ram_share.py", "hold", "--gb", "1", "--", python, "-m", "no_such_module_here")
        self.assertIn("no_such_module_here", wrapped.stderr)  # the job under the ram_share wrapper is the one checked

    def test_check_fails_an_output_that_cant_be_written_and_memory_that_isnt_there(self):
        locked = self.root / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        refused = self.gpu("check", "--cwd", str(self.root), "--output", "locked/run", "--", "true").stderr
        locked.chmod(0o700)
        self.assertIn("can't be written", refused)
        self.assertEqual(self.gpu("check", "--cwd", str(self.root), "--output", "fresh/deep/run", "--", "true").returncode, 0)
        self.assertIn("GB free", self.gpu("check", "--gb", "100000", "--", "true").stderr)

    def test_a_job_that_fails_the_check_is_never_queued(self):
        started = time.time()
        job = self.start("badpath", 1, ".venv/bin/no_such_python", "-m", "x")
        self.assertEqual(job.wait(timeout=10), 2)
        self.assertLess(time.time() - started, 5)
        self.assertFalse((self.root / "out/ops/gpu_ledger.jsonl").exists())

    def test_a_dry_run_gets_the_flag_a_time_limit_and_says_so(self):
        flag = self.root / "flag"
        self.assertEqual(self.start("dry", 1, "sh", "-c", f'echo "$KOKO_DRY_RUN" > {flag}', extra=("--dry-run",)).wait(timeout=20), 0)
        self.assertEqual(flag.read_text(), "1\n")
        queued = next(e for e in self.events() if e["event"] == "queued")
        self.assertTrue(queued["dry_run"])
        self.assertTrue(queued["about"].startswith("[dry run]"))
        self.assertTrue(next(e for e in self.events() if e["event"] == "finished")["dry_run"])
        self.assertEqual(self.start("wet", 1, "sh", "-c", f'echo "$KOKO_DRY_RUN" > {flag}').wait(timeout=20), 0)
        self.assertEqual(flag.read_text(), "\n")


if __name__ == "__main__":
    unittest.main()
