"""cloud/pace.py against a fake PACE: a stand-in for the SSH connection that answers like Slurm. Nothing leaves this Mac."""
import json
import tempfile
import unittest
from pathlib import Path

from cloud.pace import batch_script, connection_state, missing, run_job, slurm_state

CONFIG = {"host": "pace", "remote_root": "~/scratch/k", "setup": ["module load x"], "sbatch": ["-A acct", "--gres=gpu:1"], "poll_seconds": 0}


class FakeRemote:
    """Answers sbatch with a job id, then sacct with each state in turn, and keeps every command it was sent."""

    def __init__(self, states, sbatch="12345\n", copy_code=0, linked=True):
        self.states, self.sbatch, self.copy_code, self.linked = list(states), sbatch, copy_code, linked
        self.scripts, self.copied = [], []

    def connected(self):
        return self.linked

    def shell(self, script):
        self.scripts.append(script)
        if "sbatch" in script:
            return (0, self.sbatch) if self.sbatch else (1, "sbatch: error: invalid account")
        if script.startswith("sacct"):
            return 0, self.states.pop(0) if self.states else ""
        if script.startswith("tail"):
            return 0, "step 3 of 3\n"
        return 0, ""

    def copy_up(self, local, remote):
        self.copied.append(("up", str(local), remote))
        return self.copy_code, "rsync: connection refused" if self.copy_code else ""

    def copy_down(self, remote, local):
        self.copied.append(("down", remote, str(local)))
        return 0, ""


class PaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "job.log"
        self.updates = []
        self.ticket = {"id": "1-2", "name": "mind_x", "cwd": str(self.root / "kokopelli"), "pace_command": "python -m mind.run --cuda", "pull": ["out/mind/x"]}

    def run_with(self, remote, config=CONFIG):
        return run_job(self.ticket, self.log, self.updates.append, config=config, remote=remote, sleep=lambda _: None)

    def test_a_placeholder_counts_as_missing(self):
        self.assertEqual(missing(None)[0][:9], "pace.json")
        self.assertEqual(missing({**CONFIG, "remote_root": "CHANGE_ME e.g. ~/scratch"}), ["remote_root"])
        self.assertEqual(missing(CONFIG), [])

    def test_the_batch_script_takes_every_site_setting_from_the_config(self):
        script = batch_script(CONFIG, "mind_x", "~/scratch/k/kokopelli", "python -m x", 1.5)
        for line in ("#SBATCH -J mind_x", "#SBATCH -t 01:30:00", "#SBATCH -A acct", "#SBATCH --gres=gpu:1", "module load x", "python -m x"):
            self.assertIn(line, script)
        self.assertLess(script.index("module load x"), script.index("python -m x"))

    def test_sacct_states_become_the_exit_codes_the_mac_would_give(self):
        for answer, expected in (("", ("PENDING", None)), ("RUNNING|0:0", ("RUNNING", None)), ("COMPLETED|0:0", ("COMPLETED", 0)),
                                 ("FAILED|3:0", ("FAILED", 3)), ("TIMEOUT|0:15", ("TIMEOUT", 124)), ("CANCELLED by 42|0:15", ("CANCELLED", 130)),
                                 ("OUT_OF_MEMORY|0:125", ("OUT_OF_MEMORY", 137))):
            with self.subTest(answer):
                self.assertEqual(slurm_state(FakeRemote([answer]), "1"), expected)

    def test_a_job_is_copied_up_submitted_followed_and_its_results_copied_back(self):
        remote = FakeRemote(["PENDING|0:0", "RUNNING|0:0", "COMPLETED|0:0"])
        self.assertEqual(self.run_with(remote), 0)
        self.assertEqual(remote.copied[0], ("up", self.ticket["cwd"], "~/scratch/k/kokopelli"))
        self.assertIn(("down", "~/scratch/k/kokopelli/out/mind/x", str(Path(self.ticket["cwd"]) / "out/mind/x")), remote.copied)
        self.assertIn("python -m mind.run --cuda", next(script for script in remote.scripts if "sbatch" in script))
        self.assertEqual([update["state"] for update in self.updates], ["COPYING", "PENDING", "PENDING", "RUNNING", "COMPLETED", "COMPLETED"])
        self.assertEqual(self.updates[-1]["job"], "12345")
        self.assertIn("Slurm job 12345", self.log.read_text())
        self.assertIn("step 3 of 3", (self.root / "job.pace_tail").read_text())

    def test_a_failed_job_reports_its_own_exit_code(self):
        self.assertEqual(self.run_with(FakeRemote(["FAILED|7:0"])), 7)

    def test_every_way_of_not_getting_started_fails_loudly(self):
        self.assertEqual(self.run_with(FakeRemote([]), config={}), 2)
        self.assertIn("isn't set up", self.log.read_text())
        self.assertEqual(self.run_with(FakeRemote([], copy_code=1)), 2)
        self.assertIn("connection refused", self.log.read_text())
        self.assertEqual(self.run_with(FakeRemote([], sbatch="")), 2)
        self.assertIn("invalid account", self.log.read_text())

    def test_the_panel_check_never_prompts_and_says_what_is_missing(self):
        self.assertEqual(connection_state({}, FakeRemote([]))["missing"], list(("host", "remote_root", "setup", "sbatch")))
        self.assertFalse(connection_state(CONFIG, FakeRemote([], linked=False))["ready"])
        self.assertTrue(connection_state(CONFIG, FakeRemote([]))["ready"])

    def test_the_example_config_is_valid_json_and_still_counts_as_not_set_up(self):
        example = json.loads((Path(__file__).resolve().parents[1] / "cloud" / "pace.example.json").read_text())
        self.assertEqual(set(missing(example)), {"remote_root", "setup", "sbatch"})


if __name__ == "__main__":
    unittest.main()
