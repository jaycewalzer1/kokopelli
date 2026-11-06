"""The architecture chart's data: its claims stay true, and it only moves for what was really measured. No model is involved."""
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from life.agent import LLMAgent
from life.architecture import EDGES, LANES, NODES, PLAN_SECTIONS, STATUSES, catalog, overnight_signal, snapshot, python_lines, runs_module
from settings import ROOT

IDLE_PANEL = {"running": False, "mock_running": 0, "writes": 9, "events": 5, "choices": 2, "runs": 1}
PYTHON = "/usr/bin/python"


def write_run(out, name, iterations=3, validation=None):
    folder = Path(out) / name
    folder.mkdir(parents=True)
    with open(folder / "train.jsonl", "w") as file:
        for iteration in range(1, iterations + 1):
            file.write(json.dumps({"iteration": iteration, "train_distinct_actions": 2.0, "peak_memory": 19.5}) + "\n")
    with open(folder / "rollouts.jsonl", "w") as file:
        file.write(json.dumps({"turn": 1, "replies": ["rest", "work"], "scores": [1.0, -1.0], "time": 0}) + "\n")
    if validation:
        (folder / "validation.jsonl").write_text("".join(json.dumps(row) + "\n" for row in validation))
    return folder


class CatalogTest(unittest.TestCase):
    def test_every_named_file_exists(self):
        for node in NODES:
            for path in node["files"]:
                self.assertTrue((ROOT / path).exists(), f"{node['id']} names {path}")

    def test_a_branch_file_is_only_checked_while_its_worktree_exists(self):
        for node in NODES:
            for path in node.get("branch_files", []):
                self.assertTrue(path.startswith(".claude/worktrees/"), f"{node['id']} names {path} as a branch file")
                # A worktree can be removed at any time, and that shouldn't fail these tests. While it's there, the path has to be right.
                worktree = ROOT / Path(path).parts[0] / Path(path).parts[1] / Path(path).parts[2]
                if worktree.is_dir():
                    self.assertTrue((ROOT / path).exists(), f"{node['id']} names {path}")

    def test_every_node_says_what_it_does_and_why_it_has_its_status(self):
        for node in NODES:
            self.assertIn(node["status"], STATUSES, node["id"])
            self.assertTrue(node["does"] and node["why"], node["id"])
            self.assertTrue(node["files"] or node.get("branch_files") or node.get("plan"), f"{node['id']} points at neither code nor the plan")

    def test_every_plan_reference_is_a_real_section(self):
        for node in NODES:
            for section in filter(None, node.get("plan", "").split(", ")):
                self.assertIn(section, PLAN_SECTIONS, node["id"])

    def test_planned_means_no_code_and_built_means_some(self):
        for node in NODES:
            # The swarm names AGENTS.md as the nearest thing that exists, not as an implementation.
            if node["status"] == "planned" and node["id"] != "swarm":
                self.assertEqual(node["files"] + node.get("branch_files", []), [], node["id"])
            if node["status"] != "planned":
                self.assertTrue(node["files"] or node.get("branch_files"), node["id"])

    def test_the_chart_is_well_formed(self):
        ids = [node["id"] for node in NODES]
        self.assertEqual(len(ids), len(set(ids)))
        cells = [tuple(node["at"]) for node in NODES]
        self.assertEqual(len(cells), len(set(cells)))
        rows = {row for lane in LANES for row in range(lane["rows"][0], lane["rows"][1] + 1)}
        for node in NODES:
            self.assertIn(node["at"][1], rows, node["id"])
        for edge in EDGES:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)
            self.assertTrue(edge["label"])

    def test_planned_edges_can_never_move(self):
        for edge in EDGES:
            if edge["status"] == "planned":
                self.assertNotIn("active", edge, edge["label"])
                self.assertNotIn("pulse", edge, edge["label"])

    def test_an_edge_touching_a_planned_part_is_planned(self):
        planned = {node["id"] for node in NODES if node["status"] == "planned"}
        for edge in EDGES:
            if edge["from"] in planned or edge["to"] in planned:
                self.assertEqual(edge["status"], "planned", edge["label"])

    def test_the_claims_most_likely_to_go_stale_still_hold(self):
        with self.assertRaises(NotImplementedError):
            LLMAgent().choose({})
        python_files = [*ROOT.glob("*.py"), *ROOT.glob("life/*.py"), *ROOT.glob("homeostatic/*.py")]
        python_files = [path for path in python_files if path.name != "architecture.py"]
        source = "\n".join(path.read_text() for path in python_files)
        self.assertNotIn("import simworld", source)
        self.assertNotIn("import scoring", source)
        self.assertNotIn("life.scoring", source)
        for word in ("tinker", "imprint", "vault"):
            self.assertNotIn(word, source.lower(), f"{word} now appears in code, so its planned status needs a look")


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out, self.overnight, self.world = self.root / "homeostatic", self.root / "overnight", self.root / "world"
        self.paths = {name: self.root / name for name in ("ops", "mind", "benchmarks_out", "agent_loop", "evals")}
        for folder in (self.out, self.overnight, self.world):
            folder.mkdir()

    def snap(self, listing="", panel=IDLE_PANEL):
        return snapshot(panel, listing, self.out, self.overnight, self.world, self.paths)

    def test_every_signal_an_edge_names_is_measured(self):
        taken = self.snap()
        for edge in EDGES:
            for key in edge.get("active", []):
                self.assertIn(key, taken["flags"], edge["label"])
            for key in edge.get("pulse", []):
                self.assertIn(key, taken["counts"], edge["label"])

    def test_a_mock_loop_run_lights_the_loop_and_no_model(self):
        run = self.paths["agent_loop"] / "runs" / "one"
        run.mkdir(parents=True)
        (run / "config.json").write_text(json.dumps({"sim": "mock", "wm": "mock", "agent": "mock", "context": "mock", "ticks": 60}))
        (run / "events.jsonl").write_text(json.dumps({"kind": "tick_end", "tick": 1}) + "\n")
        taken = self.snap(f"{PYTHON} -m runtime.run --out runs/one")
        self.assertTrue(taken["flags"]["loop.running"])
        self.assertFalse(taken["flags"]["loop.wm_real"] or taken["flags"]["loop.agent_real"] or taken["flags"]["loop.sim_real"])
        self.assertEqual(set(taken["active_nodes"]), {"loop", "agent"})
        self.assertEqual(taken["counts"]["loop.ticks"], 1)

    def test_a_real_world_model_run_lights_cosmos(self):
        run = self.paths["agent_loop"] / "runs" / "one"
        run.mkdir(parents=True)
        (run / "config.json").write_text(json.dumps({"sim": "mock", "wm": "cosmos", "agent": "qwen", "context": "life", "ticks": 3}))
        (run / "events.jsonl").write_text("")
        taken = self.snap(f"{PYTHON} -m runtime.run --out runs/one --wm cosmos --agent qwen")
        self.assertTrue(taken["flags"]["loop.wm_real"] and taken["flags"]["loop.agent_real"] and taken["flags"]["loop.life_real"])
        self.assertFalse(taken["flags"]["loop.sim_real"])
        self.assertIn("cosmos", taken["active_nodes"])

    def test_a_job_waiting_in_the_queue_is_not_a_trainer(self):
        folder = write_run(self.out, "waiting")
        taken = self.snap(f"{PYTHON} /x/ops/gpu.py run --name a --priority 50 -- .venv/bin/python -m homeostatic.train {folder} --iters 75")
        self.assertFalse(taken["flags"]["trainer.training"])
        self.assertEqual(taken["running"], [])

    def test_with_nothing_running_nothing_is_active(self):
        write_run(self.out, "old")
        taken = self.snap()
        self.assertFalse(any(taken["flags"].values()))
        self.assertEqual(taken["active_nodes"], [])
        self.assertEqual(taken["running"], [])

    def test_a_live_trainer_lights_only_the_training_path(self):
        folder = write_run(self.out, "alive")
        taken = self.snap(f"{PYTHON} -u -m homeostatic.train {folder} --iters 75")
        self.assertTrue(taken["flags"]["trainer.training"])
        self.assertFalse(taken["flags"]["trainer.validating"])
        self.assertFalse(taken["flags"]["overnight.running"])
        self.assertEqual(taken["counts"]["trainer.updates"], 3)
        self.assertEqual(taken["counts"]["trainer.groups"], 1)
        self.assertEqual(taken["live"]["grpo"]["short"], "update 3 of 75")
        self.assertEqual(set(taken["active_nodes"]), {"qwen", "grpo", "sim", "adapter"})

    def test_validation_moves_a_different_path_from_training(self):
        folder = write_run(self.out, "alive", validation=[{"iteration": 25, "mean_drive": 30.0, "invalid": 0.0}])
        (folder / "validating.json").write_text('{"done": 4, "total": 30}')
        taken = self.snap(f"{PYTHON} -m homeostatic.train {folder} --iters 75")
        self.assertFalse(taken["flags"]["trainer.training"])
        self.assertTrue(taken["flags"]["trainer.validating"])
        self.assertEqual(taken["counts"]["trainer.lives"], 34)

    def test_a_validating_file_left_by_a_dead_run_means_nothing(self):
        folder = write_run(self.out, "dead")
        (folder / "validating.json").write_text('{"done": 4, "total": 30}')
        self.assertFalse(self.snap()["flags"]["trainer.validating"])

    def test_a_silent_process_is_not_shown_moving(self):
        folder = write_run(self.out, "stuck")
        with unittest.mock.patch("life.architecture.STALL_SECONDS", 0):
            taken = self.snap(f"{PYTHON} -m homeostatic.train {folder}")
        self.assertFalse(taken["flags"]["trainer.training"])
        self.assertFalse(taken["flags"]["trainer.running"])
        self.assertEqual(taken["active_nodes"], [])

    def test_a_shell_mentioning_a_module_is_not_a_run(self):
        listing = ("/bin/zsh -c 'python -m life.overnight; python -m homeostatic.train out/x; txt2video.py'\n"
                   "grep life.overnight\ngrep homeostatic.train out/x\nvim collect.py\n")
        write_run(self.out, "x")
        taken = self.snap(listing)
        self.assertFalse(any(taken["flags"].values()))
        self.assertEqual(taken["running"], [])

    def test_real_process_lines_are_recognized(self):
        lines = python_lines(f"{PYTHON} -u -m life.overnight --hours 8\n/x/.venv/bin/python txt2video.py a prompt\n/Library/Python.app/Contents/MacOS/Python collect.py")
        self.assertEqual(len(lines), 3)
        self.assertTrue(runs_module(lines[0][1], "life.overnight"))
        taken = self.snap("/x/.venv/bin/python txt2video.py a prompt\n/Library/Python.app/Contents/MacOS/Python collect.py")
        self.assertEqual(taken["running"], ["collect.py, on Cosmos", "txt2video.py, on Cosmos"])

    def test_a_run_replying_nothing_is_not_counted_as_the_best(self):
        write_run(self.out, "real", validation=[{"iteration": 25, "mean_drive": 43.8, "invalid": 0.0}])
        write_run(self.out, "broken", validation=[{"iteration": 25, "mean_drive": 25.2, "invalid": 1.0}])
        (self.out / "baselines-validation.json").write_text('{"base": {"mean_drive": 29.4}}')
        taken = self.snap()
        text = " ".join(taken["live"]["grpo"]["lines"])
        self.assertIn("43.8", text)
        self.assertIn("broken scored 25.2", text)
        self.assertNotIn("now beats", text)

    def test_matching_doing_nothing_is_not_beating_it(self):
        write_run(self.out, "idle", validation=[{"iteration": 25, "mean_drive": 25.2, "invalid": 0.0}])
        (self.out / "baselines-validation.json").write_text('{"base": {"mean_drive": 29.4}, "idle": {"mean_drive": 25.2}}')
        self.assertNotIn("now beats", " ".join(self.snap()["live"]["grpo"]["lines"]))

    def test_beating_the_untrained_model_asks_for_the_status_to_be_revisited(self):
        write_run(self.out, "good", validation=[{"iteration": 25, "mean_drive": 20.0, "invalid": 0.0}])
        (self.out / "baselines-validation.json").write_text('{"base": {"mean_drive": 29.4}}')
        self.assertIn("now beats", " ".join(self.snap()["live"]["grpo"]["lines"]))

    def test_clips_and_overnight_calls_come_from_their_logs(self):
        (self.world / "batch").mkdir()
        (self.world / "batch" / "manifest.jsonl").write_text('{"ok": true}\n{"ok": false}\n{"ok": true}\n')
        (self.overnight / "run").mkdir()
        (self.overnight / "run" / "calls.jsonl").write_text('{}\n{}\n')
        (self.overnight / "run" / "state.json").write_text('{"trial": true}')
        (self.overnight / "latest").symlink_to("run")
        taken = self.snap()
        self.assertEqual(taken["counts"]["world.clips"], 2)
        self.assertEqual(taken["counts"]["overnight.calls"], 2)
        self.assertFalse(taken["flags"]["overnight.running"], "old logs alone don't mean a run is going")
        self.assertTrue(self.snap(f"{PYTHON} -m life.overnight --hours 1")["flags"]["overnight.running"])

    def test_a_panel_mock_run_moves_the_life_path_only(self):
        taken = self.snap(panel={**IDLE_PANEL, "running": True, "mock_running": 1})
        self.assertTrue(taken["flags"]["panel.running"])
        self.assertNotIn("recall", taken["active_nodes"], "mock writing doesn't use memory")
        self.assertNotIn("qwen", taken["active_nodes"], "mock writing doesn't use the model")


class CountingTest(unittest.TestCase):
    def test_the_link_to_the_latest_overnight_run_is_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "run").mkdir()
            (root / "run" / "state.json").write_text('{"trial": true}')
            (root / "latest").symlink_to("run")
            self.assertEqual(overnight_signal(root, "", 0)["trials"], 1)


class ImportTest(unittest.TestCase):
    def test_the_panel_side_never_imports_a_model_library(self):
        code = "import sys, life.architecture, life.panel; print([name for name in sys.modules if name.split('.')[0] in ('mlx', 'mlx_vlm', 'torch')])"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_the_catalog_is_plain_json(self):
        self.assertIn("nodes", json.loads(json.dumps(catalog())))


if __name__ == "__main__":
    unittest.main()
