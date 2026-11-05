import json
import tempfile
import unittest
from pathlib import Path

from runtime import checkpoint, replay
from runtime.config import Config
from runtime.event_log import JsonlLog
from runtime.mocks.sim import MockSim
from runtime.run import run


class CrashAt(MockSim):
    def __init__(self, tick):
        self.crash_tick = tick

    def step(self, action, tick, render=True):
        if tick == self.crash_tick:
            raise RuntimeError("the simulator fell over")
        return super().step(action, tick, render)


def folder():
    return Path(tempfile.mkdtemp(prefix="wmloop_"))


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_run(self):
        a, b = folder(), folder()
        run(Config(ticks=4, seed=3), a)
        run(Config(ticks=4, seed=3), b)
        self.assertEqual(replay.trajectory(a), replay.trajectory(b))
        hashes = lambda run_dir: [[c["hash"] for c in t["chunks"]] for t in replay.summarize(run_dir)["ticks"]]
        self.assertEqual(hashes(a), hashes(b))

    def test_different_seed_different_run(self):
        a, b = folder(), folder()
        run(Config(ticks=4, seed=3), a)
        run(Config(ticks=4, seed=4), b)
        self.assertNotEqual(replay.trajectory(a), replay.trajectory(b))


class ResumeTest(unittest.TestCase):
    def test_a_crashed_run_resumes_to_the_same_place(self):
        whole, crashed = folder(), folder()
        run(Config(ticks=6), whole)
        with self.assertRaises(RuntimeError):
            run(Config(ticks=6), crashed, sim=CrashAt(4))
        self.assertEqual(checkpoint.load(crashed)["next_tick"], 4)
        run(Config(ticks=6), crashed, resume=True)
        self.assertEqual(replay.trajectory(whole), replay.trajectory(crashed))
        self.assertEqual(replay.summarize(crashed)["run"]["resumes"], 1)

    def test_events_from_an_unfinished_tick_stay_in_the_file_but_not_the_replay(self):
        crashed = folder()
        with self.assertRaises(RuntimeError):
            run(Config(ticks=6), crashed, sim=CrashAt(4))
        run(Config(ticks=6), crashed, resume=True)
        events = replay.load(crashed)
        tick_four_starts = [event for event in events if event["kind"] == "tick_start" and event["tick"] == 4]
        self.assertEqual(len(tick_four_starts), 2)
        self.assertEqual(sum(event["kind"] == "tick_start" and event["tick"] == 4 for event in replay.effective(events)), 1)

    def test_a_torn_last_line_survives(self):
        crashed = folder()
        with self.assertRaises(RuntimeError):
            run(Config(ticks=4), crashed, sim=CrashAt(3))
        path = crashed / "events.jsonl"
        before = path.read_bytes()
        with path.open("ab") as file:
            file.write(b'{"seq": 999, "half a li')
        run(Config(ticks=4), crashed, resume=True)
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))  # Append-only even across a crash.
        self.assertEqual(replay.summarize(crashed)["run"]["totals"]["ticks"], 4)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.run_dir = folder()
        run(Config(ticks=5), self.run_dir)

    def test_replay_matches_what_the_run_ended_with(self):
        saved = checkpoint.load(self.run_dir)
        ticks = replay.summarize(self.run_dir)["ticks"]
        self.assertEqual(len(ticks), 5)
        self.assertEqual(ticks[-1]["sim"]["state"], saved["sim_state"])
        self.assertEqual(ticks[-1]["decision"]["action"], saved["pending"])

    def test_every_stage_of_every_tick_is_in_the_log(self):
        for tick in replay.summarize(self.run_dir)["ticks"]:
            for stage in ("sim", "wm_prompt", "agent_input", "decision", "autonomy", "timing"):
                self.assertIn(stage, tick)
            self.assertEqual(len(tick["chunks"]), 2)
            self.assertEqual(len(tick["drift"]), 2)
            self.assertEqual(len(tick["agent_input"]["images"]), 6)

    def test_replay_needs_only_the_log(self):
        copy = folder()
        (copy / "events.jsonl").write_bytes((self.run_dir / "events.jsonl").read_bytes())
        self.assertEqual(replay.summarize(copy)["ticks"], replay.summarize(self.run_dir)["ticks"])

    def test_an_edited_line_is_caught(self):
        path = self.run_dir / "events.jsonl"
        lines = path.read_text().splitlines()
        event = json.loads(lines[3])
        event["data"]["tampered"] = True
        lines[3] = json.dumps(event)
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(replay.BrokenChain):
            replay.summarize(self.run_dir)

    def test_a_removed_line_is_caught(self):
        path = self.run_dir / "events.jsonl"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:3] + lines[4:]) + "\n")
        with self.assertRaises(replay.BrokenChain):
            replay.summarize(self.run_dir)

    def test_a_reopened_log_keeps_the_chain(self):
        log = JsonlLog(self.run_dir / "events.jsonl")
        log.append("note", None, {})
        log.close()
        replay.summarize(self.run_dir)


if __name__ == "__main__":
    unittest.main()
