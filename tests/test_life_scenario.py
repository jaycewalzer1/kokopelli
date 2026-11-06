"""The wellness center scenario and its night, on stand-in models. Nothing loads Qwen or Cosmos."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import time as clock
from pathlib import Path
from unittest import mock

from life import scenario, scenario_night, staged


class ScenarioRulesTest(unittest.TestCase):
    def test_every_option_is_worth_3_points_on_average(self):
        scenario.check_points()

    def test_the_front_gap_is_only_offered_by_9_08(self):
        self.assertIn("front_gap", scenario.shown_options("D2", clock(9, 8), False))
        self.assertNotIn("front_gap", scenario.shown_options("D2", clock(9, 12), False))
        self.assertIn("front_gap", scenario.shown_options("D2", clock(9, 8), True))
        self.assertIn("front_gap", scenario.shown_options("D2", clock(9, 16), False, forced_open=True))

    def test_exploration_tries_every_option_once_per_decision(self):
        for decision in ("D1", "D2", "D3"):
            tried = {scenario.exploration_choice(decision, morning) for morning in range(4)}
            self.assertEqual(tried, {option.id for option in scenario.DECISIONS[decision]})

    def test_the_schedule_is_fixed_by_the_seed(self):
        self.assertEqual(scenario.schedule("20"), scenario.schedule("20"))
        self.assertNotEqual(scenario.schedule("20"), scenario.schedule("21"))

    def test_the_rare_rate_is_near_one_in_ten(self):
        draws = scenario.schedule("x", draws=5000)["run_main"]
        self.assertAlmostEqual(draws.count("rare") / len(draws), 0.1, delta=0.02)

    def test_feel_lines_are_words_not_numbers(self):
        line = scenario.feel_line({"comfort": 0.2, "calm": 0.5, "connection": 0.9})
        self.assertNotRegex(line, r"\d")
        self.assertIn("aches", line)

    def test_needs_relax_toward_the_setpoint(self):
        state = scenario.relax({"comfort": 0.3, "calm": 1.0, "connection": 0.7})
        self.assertGreater(state["comfort"], 0.3)
        self.assertLess(state["calm"], 1.0)
        self.assertEqual(state["connection"], 0.7)

    def test_probability_words_are_caught(self):
        self.assertEqual(scenario.find_leaks("9:06. Walk the main path."), [])
        self.assertTrue(scenario.find_leaks("This usually works, a 10% chance."))


class NightTest(unittest.TestCase):
    """Two mornings, with the past written at years only, so it runs in seconds."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {**scenario_night.SCENARIO_NIGHT, "past_depth": "year", "mornings": 2, "explore_mornings": 1}
        patches = [mock.patch.dict(scenario_night.SCENARIO_NIGHT, config), mock.patch.object(scenario_night, "SCENARIO_OUT", Path(self.temp.name))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.folder = scenario_night.new_folder(mock=True)

    def test_the_night_writes_every_decision_and_its_files(self):
        scenario_night.work(self.folder)
        rows = [json.loads(line) for line in (self.folder / "trajectory.jsonl").read_text().splitlines()]
        self.assertEqual([(row["day"], row["decision"]) for row in rows], [(1, "D1"), (1, "D2"), (1, "D3"), (2, "D1"), (2, "D2"), (2, "D3")])
        self.assertEqual(rows[0]["phase"], "exploration")
        self.assertEqual(rows[3]["phase"], "consequential")
        for name in ("calibration.json", "outcome_schedule.json", "diary.md", "summary.md"):
            self.assertTrue((self.folder / name).exists(), name)
        self.assertEqual(len(list((self.folder / "clips").glob("*.mp4"))), 6)
        # Each morning's return to go at D1 is the whole morning's reward.
        self.assertAlmostEqual(rows[0]["return_to_go"], sum(row["reward"] for row in rows[:3]), places=3)

    def test_d2_happens_when_the_agent_reaches_the_lawn(self):
        scenario_night.work(self.folder)
        rows = [json.loads(line) for line in (self.folder / "trajectory.jsonl").read_text().splitlines()]
        for d1, d2 in ((rows[0], rows[1]), (rows[3], rows[4])):
            arrival = scenario.outcome_of(d1["choice"], d1["outcome"]).arrival
            self.assertEqual(d2["clock"], f"{arrival:%H:%M}")

    def test_only_the_decision_moments_reach_30_seconds(self):
        scenario_night.work(self.folder)
        from life.store import Store
        store = Store(self.folder / "life.db")
        try:
            finest = [row[0] for row in store.conn.execute("SELECT node_id FROM openings WHERE level = 'sec30' AND node_id IN "
                                                            "(SELECT node_id FROM events WHERE kind = 'scenario_decision')")]
            all_finest = store.conn.execute("SELECT COUNT(*) FROM openings WHERE level = 'sec30'").fetchone()[0]
        finally:
            store.close()
        self.assertEqual(len(finest), 6)
        self.assertEqual(all_finest, 12, "each decision's minute holds the decision and one other 30 seconds")

    def test_the_agent_never_sees_odds_or_counts(self):
        scenario_night.work(self.folder)
        calls = [json.loads(line) for line in (self.folder / "calls.jsonl").read_text().splitlines()]
        agent = [call for call in calls if call["write"] == "agent"]
        self.assertTrue(agent)
        for call in agent:
            ours = call["user"].split("RECENT MORNINGS", 1)[1]  # what this module wrote, after the world writer's gists
            self.assertEqual(scenario.find_leaks(ours), [])

    def test_a_crashed_night_resumes_where_it_stopped(self):
        def crash(folder, state):
            raise RuntimeError("crash")
        crashing = tuple((name, crash if name == "export" else phase) for name, phase in scenario_night.PHASES)
        with mock.patch.object(scenario_night, "PHASES", crashing):
            with self.assertRaises(RuntimeError):
                scenario_night.work(self.folder)
        self.assertIn("life", json.loads((self.folder / "state.json").read_text())["done"])
        scenario_night.work(self.folder)
        rows = (self.folder / "trajectory.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 6, "the resumed run neither repeats nor loses a decision")


class PoliteTest(unittest.TestCase):
    """The night gives its turn to a more important job, and its memory to anything short of room."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.queue = root / "ops" / "queue"
        self.queue.mkdir(parents=True)
        config = {**scenario_night.SCENARIO_NIGHT, "past_depth": "year", "mornings": 2, "explore_mornings": 1}
        for patch in (mock.patch.dict(scenario_night.SCENARIO_NIGHT, config), mock.patch.object(scenario_night, "SCENARIO_OUT", root / "out"),
                      mock.patch.dict(scenario_night.PIPELINE_PATHS, {"ops": root / "ops"})):
            patch.start()
            self.addCleanup(patch.stop)
        self.folder = scenario_night.new_folder(mock=True, priority=60)
        stand_in = root / "gpu.py"
        stand_in.write_text("import time\ntime.sleep(60)\n")
        self.process = subprocess.Popen([sys.executable, str(stand_in), "run"])
        self.addCleanup(lambda: (self.process.kill(), self.process.wait()))
        self.stand_in = stand_in

    def ticket(self, priority, running=False, where="local"):
        (self.queue / "t.json").write_text(json.dumps({"id": "t", "name": "simworld_mac_server", "priority": priority, "pid": self.process.pid,
                                                       "queued_at": 1.0, "running": running, "where": where}))

    def test_it_gives_way_to_a_lower_number_and_then_resumes(self):
        self.ticket(1)
        with self.assertRaises(scenario_night.YieldTurn) as caught:
            scenario_night.work(self.folder)
        self.assertIn("simworld_mac_server", str(caught.exception))
        (self.queue / "t.json").unlink()
        scenario_night.work(self.folder)
        self.assertEqual(len((self.folder / "trajectory.jsonl").read_text().splitlines()), 6)

    def test_it_doesnt_give_way_to_a_higher_number_a_running_job_or_pace(self):
        for priority, running, where in ((70, False, "local"), (1, True, "local"), (1, False, "pace")):
            with self.subTest(priority=priority, running=running, where=where):
                self.ticket(priority, running, where)
                self.assertEqual(scenario_night.more_important_waiting(60), [])

    def test_the_memory_guard_waits_for_room_and_gives_the_model_back(self):
        import ram_share
        unloaded, rooms = [], iter([5.0, 25.0, -3.0, 25.0])
        guard = ram_share.Guard("t", 20, unload=lambda: unloaded.append(1), log=lambda line: None, poll=0)
        with mock.patch.object(ram_share, "room_gb", side_effect=lambda folder: (next(rooms), [], [])):
            guard.before()  # 5 GB of room: waits, then 25: loads
            self.assertTrue(guard.loaded)
            guard.before()  # -3 + the 4 GB margin is under the floor: gives the model back, then 25: loads again
        self.assertEqual(unloaded, [1])
        self.assertTrue(guard.loaded)


class StagedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "staged"
        self.folder.mkdir()
        self.script = Path(self.temp.name) / "gpu.py"
        self.script.write_text("import time\ntime.sleep(30)\n")

    def stage(self, name="night"):
        (self.folder / f"{name}.json").write_text(json.dumps({"name": name, "priority": 25, "max_hours": 1, "cwd": "/tmp", "about": "a test",
                                                                "outputs": ["out/x"], "command": ["true"]}))

    def tearDown(self):
        for record in (self.folder / "started").glob("*.json") if (self.folder / "started").exists() else []:
            pid = json.loads(record.read_text()).get("gpu_pid")
            if pid:
                subprocess.run(["kill", str(pid)], capture_output=True)

    def test_start_launches_once_and_moves_the_job_off_the_shelf(self):
        self.stage()
        self.assertEqual([job["name"] for job in staged.listing(self.folder)], ["night"])
        started = staged.start("night", self.folder, self.script)
        self.assertTrue(started["pid"])
        self.assertEqual(staged.listing(self.folder), [])
        with self.assertRaises(staged.StageError):
            staged.start("night", self.folder, self.script)

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(staged.StageError):
            staged.start("../../etc/passwd", self.folder, self.script)

    def test_a_launch_that_dies_at_once_goes_back_on_the_shelf(self):
        self.stage()
        self.script.write_text("import sys\nprint('bad arguments')\nsys.exit(2)\n")
        with self.assertRaises(staged.StageError) as caught:
            staged.start("night", self.folder, self.script)
        self.assertIn("bad arguments", str(caught.exception))
        self.assertEqual([job["name"] for job in staged.listing(self.folder)], ["night"])


if __name__ == "__main__":
    unittest.main()
