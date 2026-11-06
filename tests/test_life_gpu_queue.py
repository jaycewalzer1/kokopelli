"""The GPU queue view's data layer, on made-up folders shaped like the real ones. No model is involved, and nothing is signalled."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from life.gpu_queue import group, newest_image, output_files, past_page, read_result, with_result, send, set_default, ticket_extras, timeline
from life.gpu_queue import QueueError, cancel, collect, log_tail, move, read_device, stopped
from settings import GPU_QUEUE_SCRIPT

PYTHON = "/usr/bin/python"
GPU = "/x/ops/gpu.py run --name n --priority 10 --max-hours 2 --"
IOREG = '"PerformanceStatistics" = {"Alloc system memory"=2147483648,"Tiler Utilization %"=5,"Device Utilization %"=99}'


class GpuQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ops = Path(self.temp.name) / "ops"
        (self.ops / "queue").mkdir(parents=True)
        (self.ops / "job_logs").mkdir()

    def ticket(self, name, pid, running=False, priority=10, queued_at=1000.0):
        (self.ops / "queue" / f"{name}.json").write_text(json.dumps({"id": name, "name": name, "priority": priority, "pid": pid, "queued_at": queued_at,
                                                                     "running": running, "command": ["python", "x.py"], "cwd": "/here"}))

    def ledger(self, *events):
        (self.ops / "gpu_ledger.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))

    def collect(self, listing=""):
        return collect({"ops": self.ops}, listing, IOREG, now=2000.0)

    def test_a_missing_folder_says_so(self):
        taken = collect({"ops": self.ops / "nope"}, "", "", now=2000.0)
        self.assertFalse(taken["available"])
        self.assertEqual(taken["running"], [])

    def test_a_failed_device_reading_is_unknown_not_zero(self):
        self.assertIsNone(read_device("")["busy_percent"])
        self.assertIsNone(read_device("")["memory_gb"])
        device = read_device(IOREG)
        self.assertEqual((device["busy_percent"], device["memory_gb"]), (99, 2.0))

    def test_the_holder_gets_its_start_limit_and_log(self):
        (self.ops / "job_logs" / "a.log").write_text("step 1\nstep 2\n")
        self.ticket("a", 11, running=True)
        self.ledger({"at": 1000, "event": "queued", "id": "a", "name": "a"}, {"at": 1500, "event": "started", "id": "a", "name": "a", "waited": 500, "log": "/x/job_logs/a.log"})
        holder = self.collect(f"11 1 {PYTHON} {GPU}")["running"][0]
        self.assertEqual((holder["started_at"], holder["waited"], holder["limit_seconds"]), (1500, 500, 7200.0))
        self.assertEqual((holder["log"], holder["cwd"]), ("a.log", "/here"))
        self.assertIn("step 2", holder["tail"])

    def test_a_holder_not_yet_in_the_ledger_has_no_start(self):
        self.ticket("a", 11, running=True)
        self.ledger({"at": 1000, "event": "queued", "id": "a", "name": "a"})
        holder = self.collect(f"11 1 {PYTHON} {GPU}")["running"][0]
        self.assertIsNone(holder["started_at"])
        self.assertIsNone(holder["tail"])

    def test_waiting_goes_in_priority_then_arrival_order(self):
        self.ticket("late", 11, priority=50, queued_at=10)
        self.ticket("second", 12, priority=20, queued_at=30)
        self.ticket("first", 13, priority=20, queued_at=20)
        listing = "\n".join(f"{pid} 1 {PYTHON} {GPU}" for pid in (11, 12, 13))
        self.assertEqual([ticket["name"] for ticket in self.collect(listing)["waiting"]], ["first", "second", "late"])

    def test_a_dead_ticket_is_stale_and_holds_nothing(self):
        self.ticket("gone", 99, running=True)
        taken = self.collect()
        self.assertEqual(taken["running"], [])
        self.assertEqual([ticket["name"] for ticket in taken["stale"]], ["gone"])

    def test_it_says_which_outside_jobs_the_queue_would_wait_for(self):
        listing = f"21 1 {PYTHON} -m homeostatic.train\n22 1 {PYTHON} -m mind.run --agent qwen\n23 1 {PYTHON} -m mind.run --agent mock"
        waits = {job["name"]: job["queue_waits"] for job in self.collect(listing)["outside"]}
        self.assertEqual(waits, {"homeostatic.train": True, "mind.run": False})

    def test_a_child_of_the_holder_is_not_outside(self):
        self.ticket("a", 11, running=True)
        self.assertEqual(self.collect(f"11 1 {PYTHON} {GPU}\n12 11 {PYTHON} img2video.py")["outside"], [])

    def test_past_turns_are_newest_first_and_only_failures_carry_output(self):
        (self.ops / "job_logs" / "bad.log").write_text("Traceback\n")
        (self.ops / "job_logs" / "good.log").write_text("fine\n")
        self.ledger({"at": 1, "event": "finished", "id": "good", "name": "good", "exit_code": 0, "log": "/x/good.log"},
                    {"at": 2, "event": "finished", "id": "bad", "name": "bad", "exit_code": 1, "log": "/x/bad.log"},
                    {"at": 3, "event": "moved", "id": "gone", "name": "gone", "priority": 5})
        taken = self.collect()
        self.assertEqual([job["id"] for job in taken["past"]], ["gone", "bad", "good"])
        self.assertEqual((taken["finished"], taken["failed"]), (2, 2))
        self.assertEqual(taken["past"][0]["state"], "lost", "moved, then its process died")
        self.assertIn("Traceback", taken["past"][1]["tail"])
        self.assertNotIn("tail", taken["past"][2])

    def test_the_log_reader_stays_in_its_folder_and_keeps_a_progress_bars_last_drawing(self):
        (self.ops / "secret.txt").write_text("secret")
        self.assertIsNone(log_tail(self.ops, "../secret.txt")["tail"])
        self.assertIsNone(log_tail(self.ops, "..")["tail"])
        (self.ops / "job_logs" / "bar.log").write_text("start\n10%\r50%\r100%\n")
        self.assertEqual(log_tail(self.ops, "bar.log")["tail"], "start\n100%\n")


class QueueChangeTest(unittest.TestCase):
    """Changes, on a queue in a temp folder whose tickets belong to stand-in gpu.py processes that only sleep."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ops = self.root / "out" / "ops"
        (self.ops / "queue").mkdir(parents=True)
        self.paths = {"ops": self.ops}
        self.stand_in = self.root / "bin" / "gpu.py"
        self.stand_in.parent.mkdir()
        self.stand_in.write_text("import time\ntime.sleep(60)\n")

    def waiter(self, name, running=False, priority=30):
        process = subprocess.Popen([sys.executable, str(self.stand_in), "run", "--name", name])
        self.addCleanup(lambda: (process.kill(), process.wait()))
        ticket_id = f"{name}-{process.pid}"
        (self.ops / "queue" / f"{ticket_id}.json").write_text(json.dumps({"id": ticket_id, "name": name, "priority": priority, "pid": process.pid,
                                                                          "queued_at": 1000.0, "running": running, "command": ["x"]}))
        return ticket_id, process

    def ledger(self):
        return [json.loads(line) for line in (self.ops / "gpu_ledger.jsonl").read_text().splitlines()]

    def test_cancelling_a_waiting_job_stops_it_and_says_so_in_the_ledger(self):
        ticket_id, process = self.waiter("a")
        self.assertEqual(cancel(ticket_id, self.paths), {"cancelled": "a"})
        process.wait(timeout=5)
        self.assertFalse((self.ops / "queue" / f"{ticket_id}.json").exists())
        self.assertEqual([(row["event"], row["id"]) for row in self.ledger()], [("cancelled", ticket_id)])
        self.assertEqual(collect(self.paths, "", "")["past"][0]["state"], "cancelled")

    def test_a_job_with_its_turn_is_never_stopped(self):
        ticket_id, process = self.waiter("a", running=True)
        with self.assertRaises(QueueError):
            cancel(ticket_id, self.paths)
        self.assertFalse(stopped(process.pid))
        with self.assertRaises(QueueError):
            move(ticket_id, 5, self.paths, GPU_QUEUE_SCRIPT)

    def test_an_unknown_ticket_and_a_bad_priority_are_refused(self):
        ticket_id, _ = self.waiter("a")
        with self.assertRaises(QueueError):
            cancel("nope", self.paths)
        for priority in (-1, 1000, 2.5, "5", True):
            with self.subTest(priority), self.assertRaises(QueueError):
                move(ticket_id, priority, self.paths, GPU_QUEUE_SCRIPT)

    @unittest.skipUnless(GPU_QUEUE_SCRIPT.is_file(), "the feat/ops worktree isn't here")
    def test_move_goes_through_the_real_gpu_py_and_its_ledger(self):
        ticket_id, _ = self.waiter("a")
        self.assertEqual(move(ticket_id, 7, self.paths, GPU_QUEUE_SCRIPT), {"moved": "a", "priority": 7})
        self.assertEqual(json.loads((self.ops / "queue" / f"{ticket_id}.json").read_text())["priority"], 7)
        self.assertEqual(self.ledger()[-1]["event"], "moved")

    def test_a_name_two_waiting_jobs_share_is_not_moved(self):
        ticket_id, _ = self.waiter("same")
        self.waiter("same")
        with self.assertRaises(QueueError):
            move(ticket_id, 7, self.paths, GPU_QUEUE_SCRIPT)


class PicturesAndPaceTest(unittest.TestCase):
    """The timeline, pictures and the Mac or PACE switch, on temp folders. No SSH connection is ever opened."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ops = self.root / "out" / "ops"
        (self.ops / "queue").mkdir(parents=True)

    def test_groups_follow_the_name_prefix(self):
        self.assertEqual([group(name) for name in ("wmloop_demo", "homeostatic_x", "evals_t0", "mind_qwen", "edge_filter_long")],
                         ["demo", "training", "evals", "mind", "other"])

    def test_a_ticket_from_before_pace_is_local(self):
        (self.ops / "queue" / "old.json").write_text(json.dumps({"id": "old", "name": "old"}))
        self.assertEqual(ticket_extras(self.ops, {"id": "old", "name": "old"})["where"], "local")
        (self.ops / "queue" / "new.json").write_text(json.dumps({"id": "new", "where": "pace", "pace_command": "x", "pace": {"state": "PENDING"}}))
        extras = ticket_extras(self.ops, {"id": "new", "name": "mind_x"})
        self.assertEqual((extras["where"], extras["can_pace"], extras["pace"]["state"], extras["group"]), ("pace", True, "PENDING", "mind"))

    def test_the_timeline_keeps_recent_jobs_with_where_and_how_they_ended(self):
        rows = [{"at": 100, "event": "queued", "id": "old", "name": "old"}, {"at": 200, "event": "finished", "id": "old", "name": "old", "exit_code": 0},
                {"at": 9000, "event": "queued", "id": "a", "name": "wmloop_a"}, {"at": 9100, "event": "started", "id": "a", "name": "wmloop_a", "where": "local"},
                {"at": 9500, "event": "finished", "id": "a", "name": "wmloop_a", "exit_code": 1, "where": "local"},
                {"at": 9200, "event": "queued", "id": "p", "name": "mind_p"}, {"at": 9300, "event": "started", "id": "p", "name": "mind_p", "where": "pace"},
                {"at": 9400, "event": "queued", "id": "lost", "name": "lost"}]
        tickets = [{"id": "p", "running": False, "where": "pace", "pace": {"state": "RUNNING"}}]
        drawn = {job["id"]: job for job in timeline(rows, tickets, now=10000, hours=1)["jobs"]}
        self.assertEqual(set(drawn), {"a", "p"}, "too old, and lost with no end or ticket")
        self.assertEqual((drawn["a"]["failed"], drawn["a"]["started"], drawn["a"]["ended"], drawn["a"]["group"]), (True, 9100, 9500, "demo"))
        self.assertEqual((drawn["p"]["where"], drawn["p"]["state"], drawn["p"]["ended"]), ("pace", "running", None))

    def test_the_newest_picture_comes_only_from_a_jobs_out_folder_inside_the_project(self):
        out = self.root / "out" / "run"
        (out / "ticks" / "0001").mkdir(parents=True)
        (out / "ticks" / "0001" / "a.png").write_bytes(b"a")
        newer = out / "ticks" / "0001" / "b.jpg"
        newer.write_bytes(b"b")
        os.utime(newer, (2_000_000_000, 2_000_000_000))
        self.assertEqual(newest_image(self.root, ["python", "-m", "x", "--out", "out/run"], root=self.root)[0], newer.resolve())
        self.assertIsNone(newest_image(self.root, ["python", "-m", "x"], root=self.root))
        self.assertIsNone(newest_image(self.root, ["x", "--out", "/etc"], root=self.root))
        self.assertIsNone(newest_image(self.root, ["x", "--out", "../.."], root=self.root))

    def test_declared_outputs_show_media_list_other_files_and_flag_what_is_missing(self):
        run = self.root / "out" / "run"
        (run / "frames").mkdir(parents=True)
        for name, at in (("frames/a.png", 1), ("frames/b.png", 3), ("clip.mp4", 2), ("notes.txt", 4)):
            (run / name).write_text("x")
            os.utime(run / name, (at, at))
        summary = self.root / "out" / "summary.json"
        summary.write_text("{}")
        found = output_files({"outputs": [str(run), str(summary), str(self.root / "out" / "never"), "/etc/hosts"]}, root=self.root)
        self.assertTrue(found["described"])
        kinds = [(item["kind"], item["name"]) for item in found["files"]]
        self.assertEqual(kinds[0], ("folder", "run/"))
        self.assertEqual([name for kind, name in kinds if kind in ("image", "video")], ["run/frames/b.png", "run/clip.mp4", "run/frames/a.png"])
        self.assertIn(("file", "run/notes.txt"), kinds)
        self.assertIn(("file", "summary.json"), kinds)
        self.assertIn(("missing", "never"), kinds)
        self.assertIn(("outside", "/etc/hosts"), kinds)
        self.assertTrue(all(item["path"] is None for item in found["files"] if item["kind"] in ("missing", "outside", "folder")))

    def test_an_older_job_without_outputs_falls_back_to_its_out_folder_and_says_so(self):
        (self.root / "out" / "old").mkdir(parents=True)
        (self.root / "out" / "old" / "f.png").write_text("x")
        found = output_files({"cwd": str(self.root), "command": ["x", "--out", "out/old"]}, root=self.root)
        self.assertEqual((found["described"], [item["name"] for item in found["files"]]), (False, ["f.png"]))

    def test_every_past_job_is_reachable_a_page_at_a_time_with_its_about(self):
        rows = [{"at": index, "event": "queued", "id": f"j{index}", "name": f"j{index}", "about": f"job {index}", "outputs": []} for index in range(45)]
        rows += [{"at": 100 + index, "event": "finished", "id": f"j{index}", "name": f"j{index}", "exit_code": 0} for index in range(45)]
        (self.ops / "gpu_ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        first, second = past_page(0, 30, {"ops": self.ops}), past_page(30, 30, {"ops": self.ops})
        self.assertEqual((first["total"], len(first["jobs"]), len(second["jobs"])), (45, 30, 15))
        self.assertEqual((first["jobs"][0]["name"], first["jobs"][0]["about"]), ("j44", "job 44"))
        self.assertEqual(second["jobs"][-1]["name"], "j0")

    def test_a_summary_is_found_by_job_id_only_and_a_new_job_without_one_is_still_being_summarized(self):
        (self.ops / "results").mkdir()
        (self.ops / "results" / "a.json").write_text(json.dumps({"id": "a", "summary": "Went well.", "rating": 4, "rating_label": "good", "secret": "x"}))
        (self.ops / "results" / "latest.json").write_text("{}")
        (self.root / "out" / "x.json").write_text(json.dumps({"summary": "outside"}))
        self.assertEqual(read_result(self.ops, "a")["rating"], 4)
        self.assertNotIn("secret", read_result(self.ops, "a"))
        for sneaky in ("../x", "../../out/x", "latest", "..", ""):
            self.assertIsNone(read_result(self.ops, sneaky), sneaky)
        fresh = with_result(self.ops, {"id": "b", "state": "finished", "at": 1000}, now=1100)
        old = with_result(self.ops, {"id": "c", "state": "finished", "at": 1000}, now=1000 + 7200)
        self.assertEqual((fresh["summarizing"], old["summarizing"], old["result"]), (True, False, None))

    def waiter(self, name, **fields):
        stand_in = self.root / "bin" / "gpu.py"  # the queue only counts a ticket whose process is a gpu.py
        stand_in.parent.mkdir(exist_ok=True)
        stand_in.write_text("import time\ntime.sleep(60)\n")
        process = subprocess.Popen([sys.executable, str(stand_in), "run", "--name", name])
        self.addCleanup(lambda: (process.kill(), process.wait()))
        ticket_id = f"{name}-{process.pid}"
        (self.ops / "queue" / f"{ticket_id}.json").write_text(json.dumps({"id": ticket_id, "name": name, "priority": 30, "pid": process.pid,
                                                                          "queued_at": 1000.0, "running": False, "command": ["x"], **fields}))
        return ticket_id

    def test_a_job_goes_to_pace_only_with_a_pace_command_and_pace_ready(self):
        ready, unready = {"ready": True, "missing": []}, {"ready": False, "missing": ["pace.json"]}
        mac_only = self.waiter("mac_only")
        with self.assertRaisesRegex(QueueError, "no PACE command"):
            send(mac_only, "pace", {"ops": self.ops}, GPU_QUEUE_SCRIPT, ready)
        portable = self.waiter("portable", pace_command="python -m x")
        with self.assertRaisesRegex(QueueError, "pace.json"):
            send(portable, "pace", {"ops": self.ops}, GPU_QUEUE_SCRIPT, unready)
        with self.assertRaises(QueueError):
            send(portable, "moon", {"ops": self.ops}, GPU_QUEUE_SCRIPT, ready)

    @unittest.skipUnless(GPU_QUEUE_SCRIPT.is_file(), "the feat/ops worktree isn't here")
    def test_the_switches_go_through_the_real_gpu_py(self):
        portable = self.waiter("portable", pace_command="python -m x")
        self.assertEqual(send(portable, "pace", {"ops": self.ops}, GPU_QUEUE_SCRIPT, {"ready": True, "missing": []}), {"sent": "portable", "where": "pace"})
        self.assertEqual(json.loads((self.ops / "queue" / f"{portable}.json").read_text())["where"], "pace")
        self.assertEqual(set_default("pace", {"ops": self.ops}, GPU_QUEUE_SCRIPT), {"default": "pace"})
        self.assertEqual(json.loads((self.ops / "where.json").read_text())["default"], "pace")


if __name__ == "__main__":
    unittest.main()
