"""What the panel reads from a run's folder, and the routes that serve it. No model is involved."""
import json
import tempfile
import unittest
from pathlib import Path

from kokopelli.life.watch import baselines, collapsed, describe_run, held_out_results, list_runs, read_rows, trainers
from kokopelli.settings import ROOT


def write_run(out, name, iterations=3, finished=False):
    folder = Path(out) / name
    folder.mkdir(parents=True)
    with open(folder / "train.jsonl", "w") as file:
        for iteration in range(1, iterations + 1):
            file.write(json.dumps({"iteration": iteration, "train_reward_mean": -1.0, "train_distinct_actions": 2.0}) + "\n")
    if finished:
        (folder / "finished").touch()
    return folder


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def test_a_line_still_being_written_is_left_for_the_next_read(self):
        path = self.out / "log.jsonl"
        path.write_text('{"a": 1}\n{"a": 2}\n{"a"')
        self.assertEqual(read_rows(path), [{"a": 1}, {"a": 2}])

    def test_a_missing_log_is_empty(self):
        self.assertEqual(read_rows(self.out / "nothing.jsonl"), [])

    def test_a_run_is_training_only_while_its_process_is_alive(self):
        folder = write_run(self.out, "alive")
        write_run(self.out, "killed")
        write_run(self.out, "done", finished=True)
        states = {run["name"]: run["state"] for run in list_runs(self.out, running={folder.resolve(): 10})}
        self.assertEqual(states, {"alive": "training", "killed": "stopped", "done": "finished"})

    def test_finding_training_processes_in_a_listing(self):
        listing = ("/usr/bin/python -u -m experiments.homeostatic.train out/homeostatic/runs/a --reward maximize --iters 25\n"
                   "/usr/bin/python -m experiments.homeostatic.train /tmp/b\n"
                   "/usr/bin/python -m experiments.homeostatic.experiment\n"
                   "vim homeostatic.train\n")
        found = trainers(listing)
        self.assertEqual(found[(ROOT / "out/homeostatic/runs/a").resolve()], 25)
        self.assertIn(Path("/tmp/b").resolve(), found)
        self.assertEqual(len(found), 2)

    def test_a_job_waiting_in_the_gpu_queue_isnt_training(self):
        waiting = "/opt/python kokopelli/ops/gpu.py run --name pilot --priority 50 -- .venv/bin/python -u -m experiments.homeostatic.train out/x --iters 75\n"
        self.assertEqual(trainers(waiting), {})
        running = "caffeinate -is .venv/bin/python -u -m experiments.homeostatic.train out/x --iters 75\n"
        self.assertEqual(trainers(waiting + running), {(ROOT / "out/x").resolve(): 75})

    def test_describing_a_run_reports_progress_and_newest_groups_first(self):
        folder = write_run(self.out, "runs/one")
        with open(folder / "rollouts.jsonl", "w") as file:
            for turn in range(20):
                file.write(json.dumps({"turn": turn}) + "\n")
        run = describe_run("runs/one", self.out, running={folder.resolve(): 50})
        self.assertEqual((run["state"], run["done"], run["total"]), ("training", 3, 50))
        self.assertEqual(run["groups"][0]["turn"], 19)
        self.assertEqual(len(run["groups"]), 12)

    def test_an_unknown_run_name_is_refused_so_a_request_cant_read_other_folders(self):
        write_run(self.out, "real")
        for name in ("missing", "../../etc", "/etc"):
            with self.assertRaises(KeyError):
                describe_run(name, self.out, running={})

    def test_collapse_needs_several_updates_in_a_row(self):
        same, varied = {"train_distinct_actions": 1.0}, {"train_distinct_actions": 1.5}
        self.assertTrue(collapsed([varied, same, same, same, same, same]))
        self.assertFalse(collapsed([same, same, same, same, varied]))
        self.assertFalse(collapsed([same, same]))

    def test_results_and_baselines_appear_once_they_exist(self):
        self.assertEqual(baselines(self.out), {})
        self.assertEqual(held_out_results(self.out), {})
        (self.out / "baselines-validation.json").write_text('{"base": {"mean_drive": 3}}')
        (self.out / "results").mkdir()
        (self.out / "results" / "base-train.json").write_text('{"summary": {"mean_drive": 3}, "episodes": []}')
        self.assertEqual(baselines(self.out)["base"]["mean_drive"], 3)
        self.assertEqual(held_out_results(self.out), {"base-train": {"mean_drive": 3}})


if __name__ == "__main__":
    unittest.main()
