"""Runs short stretches of a life in mock mode. No model involved, and no run goes past a few months."""
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime
from pathlib import Path

from kokopelli.life.engine import Budget, Engine
from kokopelli.life.generator import MockGenerator
from kokopelli.life.resolver import Resolver
from kokopelli.life.scoring import load_target
from kokopelli.life.seed import LifeSeed
from kokopelli.life.store import Store
from kokopelli.life.windows import children, find

BIRTH = date(1990, 3, 14)
ANCHOR = {"at": "1992-03-16T10:20:45", "text": "a storm knocks out the power"}
SEED = LifeSeed("test", BIRTH, place="Atlanta", family=({"name": "Ana", "relationship": "mother"},),
                anchors=(ANCHOR,), rng_seed=7)
FIRST_MONTH = "month:1992-03-14T00:00:00"
ANCHOR_DAY = "day:1992-03-16T00:00:00"


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "life.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def dump(self, run_id):
        rows = lambda table: [tuple(row)[1:] for row in self.store.conn.execute(
            f"SELECT * FROM {table} WHERE run_id = ? ORDER BY seq", (run_id,))]
        return rows("openings"), rows("closings"), rows("events")


class EngineTest(EngineTestCase):
    def test_same_seed_gives_the_same_life(self):
        runs = [self.store.create_run(SEED) for _ in range(2)]
        for run_id in runs:
            Engine(self.store, run_id).run(until=FIRST_MONTH)
        self.assertEqual(self.dump(runs[0]), self.dump(runs[1]))

    def test_steps_stop_at_a_budget_with_nothing_half_written(self):
        run_id = self.store.create_run(SEED)
        self.assertEqual(Engine(self.store, run_id, budget=Budget(generator_calls=10)).run(), "budget")
        self.assertEqual(sum(self.store.counts(run_id)[k] for k in ("opened", "closed")), 10)

    def test_time_budget_stops_the_run(self):
        run_id = self.store.create_run(SEED)
        self.assertEqual(Engine(self.store, run_id, budget=Budget(seconds=0)).run(), "budget")

    def test_stop_ends_the_run(self):
        run_id = self.store.create_run(SEED)
        stop = threading.Event()
        stop.set()
        self.assertEqual(Engine(self.store, run_id).run(stop=stop), "stopped")

    def test_run_until_closes_everything_before_the_target(self):
        run_id = self.store.create_run(SEED)
        self.assertEqual(Engine(self.store, run_id).run(until=FIRST_MONTH), "reached")
        target = self.store.node(run_id, FIRST_MONTH)
        self.assertIsNotNone(target["closing"])
        window = find(FIRST_MONTH, BIRTH)
        for week in children(window, BIRTH):
            self.assertIsNotNone(self.store.node(run_id, week.id)["closing"])

    def test_run_until_stops_past_a_target_that_never_opens(self):
        # Asking for an hour of a quiet day: the day never opens hours, so the run stops once time passes it.
        class NeverEscalates(Resolver):
            def escalates(self, window):
                return False

        run_id = self.store.create_run(SEED)
        target = "hour:1992-03-14T08:00:00"
        engine = Engine(self.store, run_id, resolver=NeverEscalates(self.store.rng_key(run_id)))
        self.assertEqual(engine.run(until=target), "reached")
        self.assertIsNone(self.store.node(run_id, target))
        cursor = self.store.cursor(run_id)
        self.assertGreaterEqual(datetime.fromisoformat(cursor["start_t"]), find(target, BIRTH).end)

    def test_an_anchor_reaches_the_finest_level(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=ANCHOR_DAY)
        tick = self.store.node(run_id, "sec30:1992-03-16T10:20:30")
        self.assertIsNotNone(tick)
        self.assertEqual(tick["opening"]["exogenous"], [ANCHOR["text"]])

    def test_most_days_stop_at_day_level(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=FIRST_MONTH)
        Engine(self.store, run_id).run(until="month:1992-04-01T00:00:00")
        depths = self.store.depth_by_day(run_id)
        self.assertGreater(len(depths), 40)
        self.assertGreater(sum(level == "day" for level in depths.values()), len(depths) * 0.7)
        self.assertEqual(depths["1992-03-16"], "sec30")

    def test_only_leaves_have_choices_and_each_has_one(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=ANCHOR_DAY)
        for node in (self.store.node(run_id, "sec30:1992-03-16T10:20:30"), self.store.node(run_id, ANCHOR_DAY)):
            found = self.store.events(run_id, node_id=node["node_id"], kind="choice")
            self.assertEqual(len(found), 1 if node["level"] == "sec30" else 0)

    def test_every_pressure_is_resolved_at_closing(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=FIRST_MONTH)
        rows = self.store.conn.execute("SELECT node_id FROM closings WHERE run_id = ?", (run_id,)).fetchall()
        self.assertTrue(rows)
        for row in rows:
            node = self.store.node(run_id, row["node_id"])
            self.assertEqual({p["id"] for p in node["opening"]["pressures"]}, {p["id"] for p in node["closing"]["pressures"]})

    def test_escalating_mid_window_opens_finer_children(self):
        class Always:
            def __init__(self, resolver):
                self.resolver = resolver

            def __getattr__(self, name):
                return getattr(self.resolver, name)

            def escalates(self, window):
                return window.level == "day"

        run_id = self.store.create_run(LifeSeed("test", BIRTH, rng_seed=1))
        engine = Engine(self.store, run_id)
        engine.resolver = Always(engine.resolver)
        engine.run(until="day:1992-03-14T00:00:00")
        day = self.store.node(run_id, "day:1992-03-14T00:00:00")
        self.assertIsNotNone(day["closing"])
        self.assertEqual(len(self.store.child_nodes(run_id, day["node_id"])), 24)

    def test_real_mode_is_refused(self):
        run_id = self.store.create_run(SEED)
        with self.assertRaises(NotImplementedError):
            Engine(self.store, run_id, mode="real")

    def test_mock_mode_never_loads_the_llm(self):
        code = ("import sys, tempfile, pathlib, datetime;"
                "from kokopelli.life.engine import Engine; from kokopelli.life.store import Store; from kokopelli.life.seed import LifeSeed;"
                "s = Store(pathlib.Path(tempfile.mkdtemp()) / 'l.db');"
                "r = s.create_run(LifeSeed('t', datetime.date(1990, 3, 14)));"
                "[Engine(s, r).step() for _ in range(5)];"
                "assert not {'llm_model', 'kokopelli.wm.llm_model', 'mlx', 'mlx_vlm'} & set(sys.modules)")
        subprocess.run([sys.executable, "-c", code], check=True)


class ForkTest(EngineTestCase):
    def test_fork_leaves_the_original_untouched(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=FIRST_MONTH)
        before = self.dump(run_id)
        fork = self.store.fork(run_id, ANCHOR_DAY)
        Engine(self.store, fork).run(until=FIRST_MONTH)
        self.assertEqual(self.dump(run_id), before)

    def test_fork_shares_the_past_and_not_the_future(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=FIRST_MONTH)
        cut = self.store.node(run_id, ANCHOR_DAY)["seq"]
        fork = self.store.fork(run_id, ANCHOR_DAY)
        before = lambda table: [tuple(row)[1:] for row in self.store.conn.execute(
            f"SELECT * FROM {table} WHERE run_id = ? AND seq < ? ORDER BY seq", (run_id, cut))]
        self.assertEqual(self.dump(fork), (before("openings"), before("closings"), before("events")))
        Engine(self.store, fork).run(until=FIRST_MONTH)
        self.assertNotEqual(self.dump(fork), self.dump(run_id))

    def test_fork_can_write_a_different_future_for_a_node_closed_in_the_original(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=ANCHOR_DAY)
        self.assertIsNotNone(self.store.node(run_id, ANCHOR_DAY)["closing"])
        fork = self.store.fork(run_id, ANCHOR_DAY)
        self.assertIsNone(self.store.node(fork, ANCHOR_DAY))
        self.assertEqual(self.store.cursor(fork)["level"], "week")

    def test_state_matches_at_the_fork_point(self):
        run_id = self.store.create_run(SEED)
        Engine(self.store, run_id).run(until=ANCHOR_DAY)
        cut = self.store.node(run_id, ANCHOR_DAY)["seq"]
        fork = self.store.fork(run_id, ANCHOR_DAY)
        self.assertEqual(self.store.state(fork), self.store.state(run_id, upto_seq=cut))


class SpyGenerator(MockGenerator):
    def __init__(self, *args):
        super().__init__(*args)
        self.seen = [repr(vars(self))]

    def write_opening(self, context):
        self.seen.append(repr(context))
        return super().write_opening(context)

    def write_closing(self, context):
        self.seen.append(repr(context))
        return super().write_closing(context)


class FirewallTest(unittest.TestCase):
    CANARY = "CANARY-a-real-persons-biography"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "life.db")
        self.seed = LifeSeed("test", BIRTH, anchors=(ANCHOR,), rng_seed=7, hidden_target=self.CANARY)
        self.run_id = self.store.create_run(self.seed)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_generator_never_sees_the_target(self):
        spy = SpyGenerator(self.store.public_seed(self.run_id), self.store.rng_key(self.run_id))
        Engine(self.store, self.run_id, generator=spy).run(until=ANCHOR_DAY)
        self.assertGreater(len(spy.seen), 20)
        self.assertNotIn(self.CANARY, "".join(spy.seen))

    def test_only_the_target_table_holds_the_target(self):
        Engine(self.store, self.run_id).run(until=ANCHOR_DAY)
        for table in ("runs", "openings", "closings", "events"):
            rows = self.store.conn.execute(f"SELECT * FROM {table}").fetchall()
            self.assertNotIn(self.CANARY, "".join(repr(tuple(row)) for row in rows), table)

    def test_public_seed_has_no_target(self):
        self.assertFalse(hasattr(self.store.public_seed(self.run_id), "hidden_target"))
        self.assertNotIn(self.CANARY, repr(self.seed))

    def test_scoring_can_read_the_target_even_after_a_fork(self):
        Engine(self.store, self.run_id).run(until=ANCHOR_DAY)
        self.assertEqual(load_target(self.store, self.run_id), self.CANARY)
        fork = self.store.fork(self.run_id, ANCHOR_DAY)
        self.assertEqual(load_target(self.store, fork), self.CANARY)

    def test_generation_code_does_not_import_scoring(self):
        root = Path(__file__).resolve().parents[2] / "kokopelli" / "life"
        for name in ("generator", "engine", "agent", "resolver", "store", "panel"):
            self.assertNotIn("scoring", (root / f"{name}.py").read_text(), name)


if __name__ == "__main__":
    unittest.main()
