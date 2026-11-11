"""The memory guard: admission rules, the hook's verdicts, and stopping a command that outgrows its claim."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kokopelli.ops import memguard


class Blocked(unittest.TestCase):
    def test_room_jobs_and_swap_each_hold_a_command(self):
        self.assertIsNone(memguard.blocked(room=10, need=6, running=0, swap=1))
        self.assertIn("room", memguard.blocked(room=5, need=6, running=0, swap=1))
        self.assertIn("already running", memguard.blocked(room=30, need=6, running=memguard.MAX_JOBS, swap=1))
        self.assertIn("swap", memguard.blocked(room=7, need=6, running=0, swap=memguard.SWAP_KILL_GB + 1))

    def test_swap_alone_is_not_a_shortage(self):
        # After a hibernate swap read 27 GB with 31 GB available. That must neither hold nor stop a command.
        self.assertIsNone(memguard.blocked(room=27, need=2, running=0, swap=27))
        self.assertFalse(memguard.short(available=31, swap=27))
        self.assertTrue(memguard.short(available=memguard.FLOOR_GB * 2 - 1, swap=27))
        self.assertTrue(memguard.short(available=memguard.FLOOR_GB - 1, swap=0))


class Hook(unittest.TestCase):
    def verdict(self, command, available=30, cwd="/Users/x/Desktop/kokopelli/.claude/worktrees/a"):
        with mock.patch.object(memguard, "main_root", return_value=Path("/Users/x/Desktop/kokopelli")):
            return memguard.hook_verdict(command, cwd, available)

    def test_light_commands_pass_even_when_memory_is_low(self):
        self.assertIsNone(self.verdict("git status --short", available=1))
        self.assertIsNone(self.verdict("grep -n unittest tests/test_x.py", available=1))

    def test_unguarded_tests_are_refused(self):
        for command in (".venv/bin/python -m unittest discover -s tests", "python -m pytest -q mac_server/tests", "cd x && pytest -q", "make test"):
            self.assertIn("memory guard", self.verdict(command), command)

    def test_guarded_tests_pass(self):
        self.assertIsNone(self.verdict("python3 kokopelli/ops/memguard.py run --name t --gb 2 -- .venv/bin/python -m unittest tests.test_x"))
        self.assertIsNone(self.verdict("make test-all"))

    def test_tests_outside_the_repo_are_left_alone(self):
        self.assertIsNone(self.verdict("python -m pytest -q", cwd="/Users/x/other"))

    def test_anything_heavy_is_refused_when_memory_is_low(self):
        self.assertIn("available", self.verdict("make test-all", available=memguard.HOOK_FLOOR_GB - 1))
        self.assertIn("available", self.verdict("npx @biomejs/biome check", available=2, cwd="/Users/x/other"))

    def test_selftest_phrase_is_refused(self):
        self.assertIn("live", self.verdict(f"echo {memguard.SELFTEST}"))


class Run(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patches = [mock.patch.object(memguard, "STATE", Path(self.folder.name) / "state"),
                   mock.patch.object(memguard, "claims_folder", return_value=Path(self.folder.name) / "claims"),
                   mock.patch.object(memguard, "POLL_SECONDS", 0.5)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.said = []

    def test_a_command_runs_and_its_claim_is_removed(self):
        code = memguard.run("ok", 1, [sys.executable, "-c", "import os; assert os.environ['MEMGUARD'] == '1'"], log=self.said.append)
        self.assertEqual(code, 0)
        self.assertEqual(list((Path(self.folder.name) / "claims").glob("*.json")), [])
        self.assertIn("done", self.said[-1])

    def test_a_command_that_outgrows_its_claim_is_stopped(self):
        hog = "import time; block = bytearray(900 * 2 ** 20); time.sleep(60)"
        code = memguard.run("hog", 0.1, [sys.executable, "-c", hog], log=self.said.append)
        self.assertEqual(code, memguard.GAVE_WAY)
        self.assertIn("STOPPED", self.said[-1])

    def test_a_command_is_stopped_when_the_mac_runs_low(self):
        with mock.patch.object(memguard.ram_share, "available_gb", return_value=memguard.FLOOR_GB - 1), \
                mock.patch.object(memguard.ram_share, "room_gb", return_value=(20, [], [])):
            code = memguard.run("low", 1, [sys.executable, "-c", "import time; time.sleep(60)"], log=self.said.append)
        self.assertEqual(code, memguard.GAVE_WAY)
        self.assertIn("available", self.said[-1])

    def test_a_command_that_never_gets_room_gives_way(self):
        # total_gb is pinned too: on a small machine (a 7 GB CI runner) 5 GB is more than it can ever give, and run()
        # refuses up front with 2 instead of reaching the wait this test is about.
        with mock.patch.object(memguard.ram_share, "room_gb", return_value=(0.5, [], [])), \
                mock.patch.object(memguard.ram_share, "total_gb", return_value=36):
            code = memguard.run("wait", 5, ["true"], wait_seconds=0, log=self.said.append)
        self.assertEqual(code, memguard.GAVE_WAY)

    def test_cwd_of_reads_this_process(self):
        self.assertEqual(os.path.realpath(memguard.cwd_of(os.getpid())), os.path.realpath(os.getcwd()))


if __name__ == "__main__":
    unittest.main()
