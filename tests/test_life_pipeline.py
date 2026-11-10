"""The Pipeline view's data layer, on made-up folders shaped like the real ones. No model is involved, and nothing is signalled."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from kokopelli.life.pipeline import collect, signals, video_path
from kokopelli.settings import PIPELINE_PATHS, ROOT

PYTHON = "/usr/bin/python"
GPU = "/x/ops/gpu.py run --name n --priority 10 --"
MOCK = {"sim": "mock", "wm": "mock", "agent": "mock", "context": "mock", "ticks": 60, "cond_frames": 5, "tick_seconds": 30}
REAL = {"sim": "simworld", "wm": "cosmos_server", "agent": "qwen", "context": "life", "ticks": 60, "cond_frames": 1, "tick_seconds": 30}


def rows(*items):
    return "".join(json.dumps(item) + "\n" for item in items)


def tick_rows(ticks, frames=(24, 24)):
    found = []
    for tick in range(1, ticks + 1):
        found += [{"kind": "wm_chunk", "tick": tick, "data": {"chunk": i, "frames": count}} for i, count in enumerate(frames)]
        found.append({"kind": "tick_end", "tick": tick})
    return found


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {name: self.root / name for name in ("ops", "mind", "benchmarks_out", "agent_loop", "evals")}
        self.out = self.root / "homeostatic"

    def collect(self, listing=""):
        return collect(self.paths, listing, self.out)

    def ticket(self, name, pid, running=False, priority=10, queued_at=1000.0, command=()):
        folder = self.paths["ops"] / "queue"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.json").write_text(json.dumps({"id": name, "name": name, "priority": priority, "pid": pid, "queued_at": queued_at, "running": running, "command": list(command)}))

    def ledger(self, *events):
        self.paths["ops"].mkdir(parents=True, exist_ok=True)
        (self.paths["ops"] / "gpu_ledger.jsonl").write_text(rows(*events))

    def run_folder(self, config, events=(), end=False, name="one", base=None):
        folder = (base or self.paths["agent_loop"] / "runs") / name
        folder.mkdir(parents=True)
        if config is not None:
            (folder / "config.json").write_text(json.dumps(config))
        all_events = list(events) + ([{"kind": "run_end", "data": {"seconds": {"total": 5.0}, "fallbacks": 0}}] if end else [])
        (folder / "events.jsonl").write_text(rows(*all_events))
        return folder

    def test_every_folder_missing_is_empty_and_says_so(self):
        taken = self.collect()
        self.assertFalse(taken["gpu"]["available"])
        self.assertFalse(taken["tests"]["available"])
        self.assertFalse(taken["agent"]["available"])
        self.assertFalse(taken["benchmarks"]["available"])
        self.assertFalse(taken["training"]["available"])
        self.assertEqual(taken["gpu"]["tickets"], [])

    def test_with_every_worktree_gone_the_goal_is_unknown_not_passed(self):
        goal = self.collect()["goal"]
        states = {row["name"]: row["state"] for row in goal["gates"]}
        self.assertEqual(states["Real Cosmos in the loop"], "unknown")
        self.assertEqual(states["A machine that can run it"], "unknown")
        self.assertEqual(goal["verdict"], "unknown")
        self.assertEqual(goal["line"], "Real 30-minute run: unknown.")

    def test_half_written_lines_are_skipped(self):
        self.ledger()
        (self.paths["ops"] / "gpu_ledger.jsonl").write_text('{"id": "a", "name": "a", "event": "queued"}\nnot json\n[1]\n{"id": "b", "name"')
        self.assertEqual(self.collect()["gpu"]["events"], 1)
        (self.paths["ops"] / "tests_latest.json").write_text('{"life": {"ok"')
        self.assertFalse(self.collect()["tests"]["available"])

    def test_a_ticket_whose_process_is_dead_is_stale(self):
        self.ticket("dead", 111)
        self.ticket("alive", 222)
        gpu = self.collect(f"222 1 {PYTHON} {GPU} true\n")["gpu"]
        self.assertEqual([ticket["name"] for ticket in gpu["tickets"]], ["alive"])
        self.assertEqual([ticket["name"] for ticket in gpu["stale"]], ["dead"])

    def test_a_reused_pid_doesnt_keep_a_ticket_alive(self):
        self.ticket("reused", 222)
        gpu = self.collect("222 1 /bin/zsh\n")["gpu"]
        self.assertEqual(gpu["tickets"], [])
        self.assertEqual(len(gpu["stale"]), 1)

    def test_tickets_sort_by_priority_then_arrival(self):
        self.ticket("late", 1, priority=50)
        self.ticket("first", 2, priority=10, queued_at=5.0)
        self.ticket("second", 3, priority=10, queued_at=6.0)
        listing = "".join(f"{pid} 0 {PYTHON} {GPU} true\n" for pid in (1, 2, 3))
        self.assertEqual([ticket["name"] for ticket in self.collect(listing)["gpu"]["waiting"]], ["first", "second", "late"])

    def test_a_job_outside_the_queue_counts_as_using_the_gpu(self):
        gpu = self.collect(f"300 1 {PYTHON} -u out/x/collect.py\n301 300 {PYTHON} txt2video.py A man's dog runs\n")["gpu"]
        self.assertTrue(gpu["busy"])
        self.assertEqual(gpu["outside"], [{"pid": 300, "name": "collect.py"}], "the child render is the same job")

    def test_a_job_started_by_its_ticket_is_not_outside(self):
        self.ticket("turn", 400, running=True)
        listing = f"400 1 {PYTHON} {GPU} python -m experiments.homeostatic.train out/a\n401 400 caffeinate -is python -m experiments.homeostatic.train out/a\n402 401 {PYTHON} -m experiments.homeostatic.train out/a\n"
        gpu = self.collect(listing)["gpu"]
        self.assertEqual(gpu["outside"], [])
        self.assertEqual([ticket["name"] for ticket in gpu["running"]], ["turn"])
        self.assertTrue(gpu["busy"])

    def test_a_waiting_tickets_command_doesnt_count_as_using_the_gpu(self):
        self.ticket("waiting", 400)
        gpu = self.collect(f"400 1 {PYTHON} {GPU} python -m experiments.homeostatic.train out/a\n")["gpu"]
        self.assertFalse(gpu["busy"])

    def test_shells_greps_and_mock_runs_are_not_model_jobs(self):
        listing = ("1 0 /bin/zsh -c python -m experiments.homeostatic.train x\n2 0 grep collect.py\n3 0 vim txt2video.py\n"
                   f"4 0 {PYTHON} -m kokopelli.loop.run --ticks 60\n5 0 {PYTHON} -m experiments.benchmarks.run --backend mock\n6 0 {PYTHON} -m kokopelli.mind.run --ticks 8\n7 0 {PYTHON} notes.py txt2video.py\n")
        self.assertEqual(self.collect(listing)["gpu"]["outside"], [])

    def test_real_runs_of_the_loop_are_model_jobs(self):
        listing = f"4 0 {PYTHON} -m kokopelli.loop.run --wm cosmos\n5 0 {PYTHON} -m experiments.benchmarks.run --backend llm_model\n6 0 {PYTHON} -m kokopelli.mind.run --agent qwen\n"
        self.assertEqual([job["name"] for job in self.collect(listing)["gpu"]["outside"]], ["kokopelli.loop.run", "experiments.benchmarks.run", "kokopelli.mind.run"])

    def test_the_ledger_becomes_one_line_per_job(self):
        self.ledger({"at": 1, "event": "queued", "id": "a", "name": "a", "priority": 10},
                    {"at": 2, "event": "started", "id": "a", "name": "a", "waited": 1.0},
                    {"at": 3, "event": "finished", "id": "a", "name": "a", "exit_code": 1, "timed_out": False, "seconds": 9.0, "peak_rss_gb": 18.2, "log": "/x/y/a.log"},
                    {"at": 4, "event": "finished", "id": "b", "name": "b", "exit_code": 75, "timed_out": False, "seconds": 9.0},
                    {"at": 5, "event": "finished", "id": "c", "name": "c", "exit_code": 124, "timed_out": True, "seconds": 9.0},
                    {"at": 6, "event": "gave_up", "id": "d", "name": "d"},
                    {"at": 7, "event": "started", "id": "e", "name": "e"})
        jobs = {job["id"]: job for job in self.collect()["gpu"]["jobs"]}
        self.assertTrue(jobs["a"]["failed"])
        self.assertEqual((jobs["a"]["log"], jobs["a"]["peak_rss_gb"], jobs["a"]["waited"]), ("a.log", 18.2, 1.0))
        self.assertFalse(jobs["b"]["failed"], "75 means it ran out of its time budget and can resume")
        self.assertEqual(jobs["b"]["meaning"], "out of time, can resume")
        self.assertTrue(jobs["c"]["failed"])
        self.assertTrue(jobs["d"]["failed"])
        self.assertEqual(jobs["e"]["state"], "lost", "started, with no finish and no live ticket")

    def test_a_failing_suite_keeps_its_tail_and_stays_failing(self):
        self.ledger()
        (self.paths["ops"] / "tests_latest.json").write_text(json.dumps({"life": {"ok": True, "summary": "5 passed", "seconds": 1.0, "at": 10.0, "tail": ""},
                                                                         "agent loop": {"ok": False, "summary": "9 ran, errors=4", "at": 10.0, "tail": "Traceback"},
                                                                         "gone": {"ok": None, "summary": "worktree missing", "at": 10.0}}))
        (self.paths["ops"] / "tests_history.jsonl").write_text(rows({"at": 1, "life": False, "agent loop": False}, {"at": 2, "life": True, "agent loop": False}))
        tests = self.collect()["tests"]
        suites = {suite["name"]: suite for suite in tests["suites"]}
        self.assertEqual(tests["failing"], ["agent loop"])
        self.assertEqual(suites["agent loop"]["tail"], "Traceback")
        self.assertEqual(suites["life"]["history"], [False, True])
        self.assertIsNone(suites["gone"]["ok"])

    def test_mock_or_real_comes_from_the_config_never_the_name(self):
        self.run_folder(MOCK, name="real_looking_name")
        self.run_folder(REAL, name="mock_looking_name")
        self.run_folder({**MOCK, "wm": "cosmos"}, name="half")
        self.run_folder(None, [{"kind": "tick_end", "tick": 1}], name="no_config")
        modes = {run["name"]: run["mode"] for run in self.collect()["agent"]["runs"]}
        self.assertEqual(modes, {"real_looking_name": "mock", "mock_looking_name": "real", "half": "mixed", "no_config": "unknown"})

    def test_a_run_reports_progress_against_its_target(self):
        self.run_folder(MOCK, tick_rows(3))
        run = self.collect()["agent"]["runs"][0]
        self.assertEqual((run["done"], run["target"], run["state"]), (3, 60, "stopped"))
        self.assertEqual(run["rendered_s"], 1.8, "two chunks of 24 frames sharing 5, at 24 fps")

    def test_only_a_live_process_with_fresh_writes_is_moving(self):
        self.run_folder(MOCK, tick_rows(1))
        self.assertEqual(self.collect()["agent"]["runs"][0]["state"], "stopped", "fresh files with no process")
        listing = f"9 1 {PYTHON} -m kokopelli.loop.run --out runs/one\n"
        self.assertEqual(self.collect(listing)["agent"]["runs"][0]["state"], "moving")
        other = f"9 1 {PYTHON} -m kokopelli.loop.run --out runs/other\n"
        self.assertEqual(self.collect(other)["agent"]["runs"][0]["state"], "stopped", "that process is writing another run")
        taken = collect(self.paths, listing, self.out, now=time.time() + 3600)
        self.assertEqual(taken["agent"]["runs"][0]["state"], "alive, quiet")
        self.assertFalse(signals(taken)["flags"]["loop.running"])

    def test_a_finished_run_doesnt_move_whatever_is_alive(self):
        self.run_folder(MOCK, tick_rows(1), end=True)
        self.assertEqual(self.collect(f"9 1 {PYTHON} -m kokopelli.loop.run --out runs/one\n")["agent"]["runs"][0]["state"], "finished")

    def test_mind_runs_add_their_feelings(self):
        folder = self.run_folder(MOCK, tick_rows(2), name="m", base=self.paths["mind"])
        (folder / "feelings.jsonl").write_text(rows({"kind": "appraisal", "feeling": "calm"}, {"kind": "appraisal", "feeling": None}, {"kind": "choice"}) + "{half")
        (folder / "mind_summary.json").write_text('{"points": {"none": 2}, "feelings": {"calm": 1}}')
        run = self.collect()["mind"]["runs"][0]
        self.assertEqual((run["mode"], run["appraisals"], run["invalid_appraisals"], run["last_feeling"], run["feelings"]), ("mock", 2, 1, "calm", 3))
        self.assertEqual(run["points"], {"none": 2})

    def test_benchmarks_say_no_real_results_until_there_are_some(self):
        results = self.paths["evals"] / "benchmarks" / "results"
        (self.paths["evals"] / "benchmarks" / "holt_laury").mkdir(parents=True)
        (self.paths["evals"] / "benchmarks" / "holt_laury" / "items.jsonl").write_text("{}\n")
        (self.paths["evals"] / "benchmarks" / "PREREG.md").write_text("STATUS: DRAFT\n")
        for name, record in (("pretend", {"real": False, "backend": "mock"}), ("noise", {"real": True, "exploratory": True, "backend": "llm_model"})):
            (results / name).mkdir(parents=True)
            (results / name / "run_record.json").write_text(json.dumps(record))
            (results / name / "results.jsonl").write_text(rows({"valid": True}, {"valid": False}))
        benchmarks = self.collect()["benchmarks"]
        self.assertEqual((benchmarks["real_results"], benchmarks["exploratory"], benchmarks["prereg"], benchmarks["instruments"]), (0, 1, "draft", ["holt_laury"]))
        (results / "true").mkdir()
        (results / "true" / "run_record.json").write_text('{"real": true, "exploratory": false, "backend": "llm_model"}')
        self.assertEqual(self.collect()["benchmarks"]["real_results"], 0, "a record with no rows isn't a result")
        (results / "true" / "results.jsonl").write_text(rows({"valid": True}))
        self.assertEqual(self.collect()["benchmarks"]["real_results"], 1)

    def test_training_that_only_matches_doing_nothing_hasnt_beaten_it(self):
        folder = self.out / "run"
        folder.mkdir(parents=True)
        (folder / "train.jsonl").write_text(rows({"iteration": 5}))
        (folder / "validation.jsonl").write_text(rows({"iteration": 5, "mean_drive": 25.2, "invalid": 0.0}))
        (self.out / "baselines-validation.json").write_text('{"base": {"mean_drive": 29.4}, "idle": {"mean_drive": 25.2}}')
        training = self.collect()["training"]
        self.assertFalse(training["beaten"])
        self.assertEqual(training["runs"][0]["done"], 5)
        (folder / "validation.jsonl").write_text(rows({"iteration": 10, "mean_drive": 9.0, "invalid": 0.0}))
        self.assertTrue(self.collect()["training"]["beaten"])

    def test_a_waiting_tickets_command_doesnt_mark_a_training_run_as_training(self):
        folder = self.out / "run"
        folder.mkdir(parents=True)
        (folder / "train.jsonl").write_text(rows({"iteration": 5}))
        taken = self.collect(f"9 1 {PYTHON} {GPU} python -m experiments.homeostatic.train {folder} --iters 75\n")
        self.assertEqual(taken["training"]["runs"][0]["state"], "stopped")

    def write_blocker_files(self, blanks):
        scripts = self.paths["agent_loop"] / "scripts" / "pace"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "env.sh").write_text("X=CHANGE_ME\n" * blanks)
        (scripts / "wmloop_run.sbatch").write_text("#!/bin/sh\n")
        (self.paths["agent_loop"] / "runtime").mkdir(exist_ok=True)
        (self.paths["agent_loop"] / "runtime" / "loop.py").write_text("")

    def test_mock_runs_alone_leave_the_goal_blocked(self):
        self.write_blocker_files(blanks=3)
        self.run_folder(MOCK, tick_rows(60), end=True)
        goal = self.collect()["goal"]
        states = {row["name"]: row for row in goal["gates"]}
        self.assertEqual(states["60 ticks, even on mocks"]["state"], "pass")
        self.assertEqual(states["Real Cosmos in the loop"]["state"], "fail")
        self.assertIn("3 CHANGE_ME", states["A machine that can run it"]["evidence"])
        self.assertEqual(goal["verdict"], "blocked")
        self.assertIn("Real SimWorld in the loop", goal["blockers"])

    def test_a_real_full_length_run_finishing_is_done(self):
        self.write_blocker_files(blanks=0)
        self.ledger()
        (self.paths["ops"] / "tests_latest.json").write_text('{"agent loop": {"ok": true, "summary": "9 passed"}}')
        self.run_folder(REAL, tick_rows(60, frames=(181, 181, 181, 181)), end=True)
        goal = self.collect()["goal"]
        self.assertEqual(goal["verdict"], "done")
        self.assertEqual(goal["blockers"], [])

    def test_a_short_real_render_doesnt_pass_full_length(self):
        self.write_blocker_files(blanks=0)
        self.run_folder(REAL, tick_rows(60, frames=(16,)), end=True)
        goal = self.collect()["goal"]
        self.assertEqual({row["name"]: row["state"] for row in goal["gates"]}["Full-length ticks"], "fail")
        self.assertNotEqual(goal["verdict"], "done")

    def test_the_goal_names_what_holds_the_queue(self):
        self.ticket("next", 400)
        goal = self.collect(f"400 1 {PYTHON} {GPU} true\n300 1 {PYTHON} collect.py\n")["goal"]
        self.assertEqual((goal["next_up"], goal["held_by"]), ("next", ["collect.py"]))

    def test_video_only_resolves_a_discovered_run(self):
        folder = self.run_folder(MOCK, name="m", base=self.paths["mind"])
        (folder / "final.mp4").write_bytes(b"x")
        self.assertEqual(video_path("mind", "m", self.paths), (folder / "final.mp4").resolve())
        for kind, run in (("mind", "../m"), ("mind", ".."), ("mind", "none"), ("nope", "m"), ("mind", str(folder))):
            with self.subTest(run), self.assertRaises(KeyError):
                video_path(kind, run, self.paths)

    def test_a_link_out_of_a_run_folder_is_refused(self):
        folder = self.run_folder(MOCK, name="m", base=self.paths["mind"])
        secret = self.root / "secret.mp4"
        secret.write_bytes(b"x")
        (folder / "final.mp4").symlink_to(secret)
        with self.assertRaises(KeyError):
            video_path("mind", "m", self.paths)

    def test_a_run_with_no_video_has_none_to_serve(self):
        self.run_folder(MOCK, name="m", base=self.paths["mind"])
        with self.assertRaises(KeyError):
            video_path("mind", "m", self.paths)

    def test_a_section_that_cant_be_read_says_so_and_the_rest_still_work(self):
        self.ledger({"at": 1, "event": "queued", "id": "a", "name": "a"})
        (self.paths["ops"] / "queue").mkdir()
        (self.paths["ops"] / "queue" / "bad.json").write_text('{"pid": 1, "queued_at": "soon", "priority": "high"}\n')
        (self.paths["ops"] / "queue" / "bad2.json").write_text('{"pid": 1, "queued_at": 1, "priority": 2}\n')
        taken = self.collect(f"1 0 {PYTHON} {GPU} true\n")
        self.assertIn("goal", taken)
        self.assertIn("error", taken["gpu"])
        self.assertEqual(taken["gpu"]["tickets"], [])


class SettingsTest(unittest.TestCase):
    def test_every_path_hangs_off_the_repo(self):
        for path in PIPELINE_PATHS.values():
            self.assertTrue(path.is_relative_to(ROOT))

    def test_the_view_never_imports_a_model_library(self):
        code = "import sys, kokopelli.life.pipeline; print([name for name in sys.modules if name.split('.')[0] in ('mlx', 'mlx_vlm', 'torch', 'numpy', 'pandas')])"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
