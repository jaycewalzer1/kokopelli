"""The calendar that every node's window comes from."""
import unittest
from datetime import date, datetime

from life.windows import LEVELS, age_at, children, depth_limit_for, find, life_window, stage_at

BIRTH = date(1990, 3, 14)


def path_to_finest(birth):
    window = life_window(birth)
    while True:
        yield window
        kids = children(window, birth)
        if not kids:
            return
        window = kids[len(kids) // 2]


class WindowsTest(unittest.TestCase):
    def test_children_exactly_cover_their_parent_at_every_level(self):
        for birth in (BIRTH, date(1990, 10, 2), date(1992, 2, 29), date(1990, 9, 1)):
            for window in path_to_finest(birth):
                kids = children(window, birth)
                if not kids:
                    continue
                with self.subTest(birth=birth, level=window.level):
                    self.assertEqual(kids[0].start, window.start)
                    self.assertEqual(kids[-1].end, window.end)
                    self.assertTrue(all(a.end == b.start for a, b in zip(kids, kids[1:])))
                    self.assertEqual([kid.index for kid in kids], list(range(len(kids))))

    def test_path_uses_every_level_in_order(self):
        self.assertEqual([window.level for window in path_to_finest(BIRTH)], list(LEVELS))

    def test_life_runs_from_age_two_to_thirty(self):
        life = life_window(BIRTH)
        self.assertEqual(life.start, datetime(1992, 3, 14))
        self.assertEqual(life.end, datetime(2020, 3, 14))

    def test_year_sequence(self):
        labels = [year.label for year in children(life_window(BIRTH), BIRTH)]
        self.assertEqual(labels[:5], ["Age 2", "Age 3", "Age 4", "Age 5", "Kindergarten"])
        self.assertEqual(labels[5:18], [f"Grade {grade}" for grade in range(1, 13)] + ["College 1"])
        self.assertEqual(labels[21], "Postgrad 1")

    def test_kindergarten_waits_when_the_child_is_not_yet_five(self):
        birth = date(1990, 10, 2)
        kindergarten = next(y for y in children(life_window(birth), birth) if y.label == "Kindergarten")
        self.assertEqual(kindergarten.start, datetime(1996, 9, 1))

    def test_a_week_crossing_months_is_cut_at_the_boundary(self):
        # March 1993 ends on a Wednesday, so its last week and April's first are both partial.
        march = find("month:1993-03-14T00:00:00", BIRTH)
        last_week = children(march, BIRTH)[-1]
        self.assertEqual(last_week.end, datetime(1993, 4, 1))
        self.assertEqual(len(children(last_week, BIRTH)), 3)

    def test_a_school_year_has_about_365_days(self):
        life = life_window(BIRTH)
        kindergarten = next(y for y in children(life, BIRTH) if y.label == "Kindergarten")
        weeks = [week for season in children(kindergarten, BIRTH) for month in children(season, BIRTH)
                 for week in children(month, BIRTH)]
        self.assertEqual(sum(len(children(week, BIRTH)) for week in weeks), 366)

    def test_find_returns_the_same_window(self):
        for window in path_to_finest(BIRTH):
            self.assertEqual(find(window.id, BIRTH), window)

    def test_find_rejects_a_window_that_does_not_exist(self):
        for bad in ("day:1985-01-01T00:00:00", "hour:1993-05-05T00:10:00", "nope:1993-05-05T00:00:00"):
            with self.subTest(bad), self.assertRaises(KeyError):
                find(bad, BIRTH)

    def test_stage_follows_age(self):
        self.assertEqual(stage_at(age_at(BIRTH, datetime(1992, 6, 1)))["name"], "toddler")
        self.assertEqual(stage_at(age_at(BIRTH, datetime(2005, 6, 1)))["name"], "adolescent")
        self.assertEqual(stage_at(29.99)["name"], "young_adult")

    def test_depth_limit_comes_from_salience(self):
        self.assertEqual(depth_limit_for(0.0), "day")
        self.assertEqual(depth_limit_for(1.0), "sec30")


if __name__ == "__main__":
    unittest.main()
