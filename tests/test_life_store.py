"""Tries to break each write-once rule. No model involved."""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from kokopelli.life.seed import LifeSeed
from kokopelli.life.store import InvalidNodeError, OrderError, Store, WriteOnceError
from kokopelli.life.windows import children, life_window

BIRTH = date(1990, 3, 14)
OPENING = {"setting": "x", "exogenous": [], "pressures": [], "open_questions": []}
CLOSING = {"summary": "x", "what_happened": "x", "pressures": [], "choices": []}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "life.db")
        self.run_id = self.store.create_run(LifeSeed("test", BIRTH, place="Atlanta",
                                                     family=({"name": "Ana", "relationship": "mother"},)))
        self.life = life_window(BIRTH)
        self.store.open_node(self.run_id, self.life, 0.1, "day", OPENING)
        self.years = children(self.life, BIRTH)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_second_opening_throws(self):
        with self.assertRaises(WriteOnceError):
            self.store.open_node(self.run_id, self.life, 0.9, "sec30", OPENING)

    def test_second_closing_throws(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        with self.assertRaises(WriteOnceError):
            self.store.close_node(self.run_id, self.years[0].id, CLOSING)

    def test_a_failed_second_write_leaves_the_first_intact(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, {**CLOSING, "summary": "first"})
        with self.assertRaises(WriteOnceError):
            self.store.close_node(self.run_id, self.years[0].id, {**CLOSING, "summary": "second"})
        self.assertEqual(self.store.node(self.run_id, self.years[0].id)["closing"]["summary"], "first")

    def test_child_cannot_open_before_previous_sibling_closes(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, self.years[1], 0.1, "year", OPENING)

    def test_child_cannot_skip_a_sibling(self):
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, self.years[1], 0.1, "year", OPENING)

    def test_child_cannot_open_without_its_parent(self):
        season = children(self.years[0], BIRTH)[0]
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, season, 0.1, "day", OPENING)

    def test_child_cannot_open_under_a_closed_parent(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, children(self.years[0], BIRTH)[0], 0.1, "day", OPENING)

    def test_child_cannot_open_below_the_depth_limit(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, children(self.years[0], BIRTH)[0], 0.1, "day", OPENING)

    def test_a_window_outside_the_calendar_cannot_open(self):
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, replace(self.years[0], end=self.years[0].end.replace(day=1)),
                                 0.1, "year", OPENING)

    def test_parent_cannot_close_with_a_child_open(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        with self.assertRaises(OrderError):
            self.store.close_node(self.run_id, self.life.id, CLOSING)

    def test_parent_cannot_close_before_all_children_exist(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        with self.assertRaises(OrderError):
            self.store.close_node(self.run_id, self.life.id, CLOSING)

    def test_node_above_its_limit_cannot_close_as_a_leaf(self):
        with self.assertRaises(OrderError):
            self.store.close_node(self.run_id, self.life.id, CLOSING)

    def test_cannot_close_what_never_opened(self):
        with self.assertRaises(OrderError):
            self.store.close_node(self.run_id, self.years[0].id, CLOSING)

    def test_opening_cannot_carry_outcomes(self):
        with self.assertRaises(InvalidNodeError):
            self.store.open_node(self.run_id, self.years[0], 0.1, "year", {**OPENING, "what_happened": "spoiler"})

    def test_pressure_needs_odds(self):
        bad = {**OPENING, "pressures": [{"id": "p0", "text": "x", "odds": 1.5}]}
        with self.assertRaises(InvalidNodeError):
            self.store.open_node(self.run_id, self.years[0], 0.1, "year", bad)

    def test_closing_must_resolve_every_pressure(self):
        opening = {**OPENING, "pressures": [{"id": "p0", "text": "x", "odds": 0.5}]}
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", opening)
        with self.assertRaises(InvalidNodeError):
            self.store.close_node(self.run_id, self.years[0].id, CLOSING)

    def test_raw_sql_cannot_edit_or_delete_any_table(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        self.store.append_event(self.run_id, self.life.id, self.life.start, "moved", {"place": "Boston"})
        for table in ("runs", "openings", "closings", "events"):
            for statement in (f"UPDATE {table} SET run_id = 99", f"DELETE FROM {table}"):
                with self.subTest(statement), self.assertRaises(sqlite3.IntegrityError):
                    self.store.conn.execute(statement)

    def test_replace_cannot_overwrite_a_row(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("INSERT OR REPLACE INTO closings SELECT run_id, node_id, '{}', seq FROM closings")
        self.assertEqual(self.store.node(self.run_id, self.years[0].id)["closing"], CLOSING)

    def test_event_cannot_be_logged_on_a_closed_node(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        self.store.close_node(self.run_id, self.years[0].id, CLOSING)
        with self.assertRaises(OrderError):
            self.store.append_event(self.run_id, self.years[0].id, self.years[0].start, "moved", {"place": "Reno"})

    def test_state_is_a_replay_of_the_log(self):
        first = self.store.state(self.run_id)
        self.assertEqual(first["place"], "Atlanta")
        self.assertEqual(first["people"]["Ana"]["relationship"], "mother")
        seq = self.store.last_seq(self.run_id)
        self.store.append_event(self.run_id, self.life.id, self.life.start, "moved", {"place": "Boston"})
        self.store.append_event(self.run_id, self.life.id, self.life.start, "money_changed", {"delta": 5})
        self.assertEqual(self.store.state(self.run_id)["place"], "Boston")
        self.assertEqual(self.store.state(self.run_id)["money"], 5)
        self.assertEqual(self.store.state(self.run_id, upto_seq=seq)["place"], "Atlanta")

    def test_escalating_allows_children_without_changing_the_node(self):
        self.store.open_node(self.run_id, self.years[0], 0.1, "year", OPENING)
        season = children(self.years[0], BIRTH)[0]
        with self.assertRaises(OrderError):
            self.store.open_node(self.run_id, season, 0.1, "season", OPENING)
        self.store.escalate(self.run_id, self.years[0].id)
        self.store.open_node(self.run_id, season, 0.1, "season", OPENING)
        self.assertEqual(self.store.node(self.run_id, self.years[0].id)["depth_limit"], "year")


if __name__ == "__main__":
    unittest.main()
