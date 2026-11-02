import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from lifeclock.clock import (
    MINUTES_PER_DAY, format_t, level_bounds, level_key, season_key, to_t,
)
from lifeclock.engine import LifeRun, tick_day
from lifeclock.store import digests
from lifeclock.world import World

WORLD = World()


def quiet(_):
    pass


class ClockTests(unittest.TestCase):
    def test_round_trip(self):
        for iso in ("1941-04-09T04:12", "1952-02-29T23:59", "2023-10-02T06:39"):
            self.assertEqual(format_t(to_t(iso)), iso)

    def test_winter_crosses_new_year(self):
        self.assertEqual(season_key(date(1941, 12, 31)), "1941-winter")
        self.assertEqual(season_key(date(1942, 1, 1)), "1941-winter")
        lo, hi = level_bounds("season", date(1942, 2, 1))
        self.assertEqual((lo, hi), (to_t("1941-12-01"), to_t("1942-03-01")))

    def test_leap_winter_length(self):
        lo, hi = level_bounds("season", date(1952, 1, 15))
        self.assertEqual((hi - lo) // MINUTES_PER_DAY, 91)

    def test_week_crosses_year(self):
        self.assertEqual(level_key("week", date(1948, 12, 31)), "1948-W53")
        lo, hi = level_bounds("week", date(1949, 1, 1))
        self.assertEqual(hi - lo, 7 * MINUTES_PER_DAY)
        self.assertLessEqual(lo, to_t("1948-12-31"))


class CanonTests(unittest.TestCase):
    def test_canon_is_consistent(self):
        self.assertEqual(WORLD.validate(), [])

    def test_infants_do_not_plan(self):
        self.assertEqual(WORLD.plans_believed_at(to_t("1942-01-01")), [])

    def test_plan_memory_is_bitemporal(self):
        def versions(iso):
            return [p["version"] for p in WORLD.plans_believed_at(to_t(iso))
                    if p["id"] == "p_find_tomas"]
        self.assertEqual(versions("1957-11-30"), [])
        self.assertEqual(versions("1960-01-01"), [1])
        self.assertEqual(versions("1970-01-01"), [2])
        self.assertEqual(versions("1990-01-01"), [3])
        self.assertEqual(versions("1997-01-01"), [])

    def test_no_statement_leaks_from_her_future(self):
        def held(iso):
            return {s["id"] for s in WORLD.statements_held_at(to_t(iso))}
        self.assertNotIn("s_mid_leg", held("1951-01-16"))
        self.assertIn("s_mid_leg", held("1953-01-01"))
        self.assertNotIn("s_mid_found", held("1996-07-23T13:17"))
        self.assertIn("s_mid_found", held("1996-07-23T13:18"))
        self.assertNotIn("s_ado_tomas", held("1996-07-23T13:18"))

    def test_held_knowledge_never_precedes_its_source_event(self):
        # Whatever a plan names as done must not be in the past of the plan's start.
        for p in WORLD.plans:
            for m in p["milestones"]:
                if m["event"]:
                    self.assertGreaterEqual(to_t(WORLD.event_by_id[m["event"]]["at"]), to_t(p["formed"]))

    def test_blocked_plan_is_still_visible_when_she_held_it(self):
        ids = [p["id"] for p in WORLD.plans_believed_at(to_t("1951-01-01"))]
        self.assertIn("p_pilot", ids)
        ids = [p["id"] for p in WORLD.plans_believed_at(to_t("1955-01-01"))]
        self.assertNotIn("p_pilot", ids)


class ExpansionTests(unittest.TestCase):
    def test_every_day_is_complete_and_clipped(self):
        total = 0
        for day_index in range(WORLD.first_day(), WORLD.last_day() + 1):
            _, strip = WORLD.day(day_index)
            self.assertEqual(len(strip), MINUTES_PER_DAY)
            total += MINUTES_PER_DAY - strip.count(0)
        self.assertEqual(total, WORLD.total_minutes)

    def test_random_access_ignores_call_order(self):
        day = to_t("1975-09-02") // MINUTES_PER_DAY
        fresh = World().day(day)
        churned = World()
        churned.day(day + 500)
        churned.day(day - 500)
        self.assertEqual(churned.day(day), fresh)

    def test_events_land_on_their_exact_minute(self):
        event_code = WORLD.code["event"]
        for e in WORLD.events:
            t = to_t(e["at"])
            _, strip = WORLD.day(t // MINUTES_PER_DAY)
            self.assertEqual(strip[t % MINUTES_PER_DAY], event_code, e["id"])

    def test_birth_and_death_minutes(self):
        self.assertEqual(WORLD.at(WORLD.birth_t)["minute"]["event"], "Born during breakup")
        with self.assertRaises(ValueError):
            WORLD.at(WORLD.birth_t - 1)
        with self.assertRaises(ValueError):
            WORLD.at(WORLD.death_t)
        self.assertEqual(WORLD.at(WORLD.death_t - 1)["minute"]["event"], "Dies at first light")

    def test_stack_agrees_at_a_known_moment(self):
        before = WORLD.at(to_t("1996-07-23T13:17"))
        self.assertIn(("p_find_tomas", 3), [(p["id"], p["version"]) for p in before["plans_believed"]])
        s = WORLD.at(to_t("1996-07-23T13:18"))
        self.assertEqual(s["segment"]["id"], "midlife")
        self.assertEqual(s["year"]["key"], "1996")
        self.assertEqual(s["season"]["key"], "1996-summer")
        self.assertEqual(s["month"]["key"], "1996-07")
        self.assertEqual(s["minute"]["event"], "Finds the Ellen Tarn")
        self.assertEqual(s["day"]["household"], ["Emeka"])
        self.assertNotIn("p_find_tomas", [p["id"] for p in s["plans_believed"]])
        self.assertIn("s_mid_found", [h["id"] for h in s["statements_held"]])

    def test_tick_matches_random_access_micro(self):
        day = to_t("1966-07-01") // MINUTES_PER_DAY
        _, strip = WORLD.day(day)
        counts, _, lived = tick_day(WORLD, day, strip)
        self.assertEqual(lived, MINUTES_PER_DAY)
        self.assertEqual(sum(counts.values()), MINUTES_PER_DAY)
        for m in range(0, MINUTES_PER_DAY, 37):
            t = day * MINUTES_PER_DAY + m
            stack = WORLD.at(t)
            code = strip[m]
            self.assertEqual(stack["minute"]["activity"], WORLD.activities[code]["id"])
            self.assertEqual(stack["minute"]["micro"],
                             WORLD.micro_lists[code][WORLD.micro_index(t, code)])


class ResumeTests(unittest.TestCase):
    STOP = to_t("1947-01-01") // MINUTES_PER_DAY
    MID = to_t("1944-03-15") // MINUTES_PER_DAY

    def test_stop_and_resume_gives_the_same_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            straight = Path(tmp) / "a.db"
            broken = Path(tmp) / "b.db"
            chain_a, _ = LifeRun(WORLD, straight).run(stop_before_day=self.STOP, log=quiet)
            LifeRun(WORLD, broken).run(stop_before_day=self.MID, log=quiet)
            chain_b, _ = LifeRun(World(), broken).run(stop_before_day=self.STOP, log=quiet)
            self.assertEqual(chain_a, chain_b)
            self.assertEqual(digests(sqlite3.connect(straight)), digests(sqlite3.connect(broken)))

    def test_paced_run_matches_unpaced_and_audits_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            fast, paced = Path(tmp) / "f.db", Path(tmp) / "p.db"
            stop = WORLD.first_day() + 60
            chain_a, _ = LifeRun(WORLD, fast).run(stop_before_day=stop, log=quiet)
            run = LifeRun(WORLD, paced)
            # Stretch the whole life so that these 60 days take about 0.3s.
            seconds = 0.3 * WORLD.total_minutes / (60 * MINUTES_PER_DAY)
            chain_b, _ = run.run(wall_seconds=seconds, stop_before_day=stop, log=quiet)
            self.assertEqual(chain_a, chain_b)
            self.assertGreater(run.audits, 0)
            self.assertEqual(run.audit_failures, 0)
            self.assertEqual(digests(sqlite3.connect(fast)), digests(sqlite3.connect(paced)))

    def test_refuses_to_resume_on_a_different_canon(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "a.db"
            LifeRun(WORLD, db).run(stop_before_day=WORLD.first_day() + 3, log=quiet)
            other = World()
            other.canon_sha256 = "different"
            with self.assertRaises(SystemExit):
                LifeRun(other, db)


if __name__ == "__main__":
    unittest.main()
