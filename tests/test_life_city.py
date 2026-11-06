"""The city plan's checks, on small worlds built to break one rule each."""
import unittest

from life import city


def tiny(**changes):
    data = {
        "cells": [{"id": "a", "bounds_m": [0, 0, 100, 100]}, {"id": "b", "bounds_m": [120, 0, 220, 100]}],
        "edges": [{"id": "farm", "bounds_m": [0, 110, 220, 150]}],
        "buildings": [{"id": "a_tower", "cell": "a", "footprint_m": [80, 40, 100, 60], "height_m": 20},
                      {"id": "b_tower", "cell": "b", "footprint_m": [120, 40, 140, 60], "height_m": 20}],
        "lanes": {"segments": [{"id": "gap", "rect_m": [100, 0, 120, 100]}]},
        "paths": [], "landscape": [], "places": [],
        "sky_bridges": {"elevation_m": 18, "segments": [{"id": "ab", "span_m": [[100, 50], [120, 50]]}]},
    }
    data.update(changes)
    return data


class CityChecksTest(unittest.TestCase):
    def test_a_consistent_world_has_no_checks(self):
        self.assertEqual(city.checks(tiny()), [])

    def test_a_bridge_above_its_roof_is_flagged(self):
        data = tiny()
        data["buildings"][1]["height_m"] = 10
        [found] = city.checks(data)
        self.assertEqual((found["kind"], found["ids"]), ("bridge", ["ab", "b_tower"]))

    def test_a_bridge_ending_in_the_air_is_flagged(self):
        data = tiny(sky_bridges={"elevation_m": 18, "segments": [{"id": "ab", "span_m": [[100, 50], [120, 90]]}]})
        self.assertIn("no building", city.checks(data)[0]["text"])

    def test_a_tower_on_a_roof_is_not_an_overlap(self):
        data = tiny()
        data["buildings"][1]["height_m"] = 10
        data["buildings"].append({"id": "landing", "cell": "b", "on": "b_tower", "footprint_m": [120, 46, 128, 54], "height_m": 18})
        self.assertEqual(city.checks(data), [])
        del data["buildings"][2]["on"]
        self.assertEqual([check["kind"] for check in city.checks(data)], ["overlap"])

    def test_a_place_outside_its_cell_is_flagged(self):
        data = tiny(places=[{"id": "cafe", "cell": "a", "pos_m": [150, 50]}])
        [found] = city.checks(data)
        self.assertEqual(found["ids"], ["cafe"])
        self.assertIn("in b", found["text"])

    def test_a_path_through_a_pond_is_flagged(self):
        data = tiny(paths=[{"id": "walk", "polyline_m": [[50, 110], [50, 150]]}],
                    landscape=[{"id": "pond", "type": "pond", "ellipse_m": {"center": [50, 130], "rx": 5, "ry": 10}}])
        self.assertEqual(city.checks(data)[0]["kind"], "water")

    def test_a_narrow_lane_is_flagged(self):
        data = tiny(lanes={"segments": [{"id": "gap", "rect_m": [100, 0, 104, 100]}]})
        self.assertEqual(city.checks(data)[0]["kind"], "lane")

    def test_the_real_world_loads(self):
        data = city.world()
        self.assertEqual(data["meta"]["size_m"], [600, 600])
        self.assertTrue(all({"kind", "ids", "text"} <= set(check) for check in city.checks(data)))


if __name__ == "__main__":
    unittest.main()
