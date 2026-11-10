"""Formulas checked against numbers worked out by hand, not against the code's own output."""
import math
import unittest

from kokopelli.loop.adapters.simworld_math import (angle_delta, camera_to_world, format_clock, heading_to, hearing,
                                            intrinsics_from_fov, parse_clock, project_point, sun_pitch_from_elevation,
                                            time_of_day)
from kokopelli.loop.physics import Rotation, Vec3


class IntrinsicsTest(unittest.TestCase):
    def test_ninety_degree_fov_gives_fx_of_half_the_width(self):
        k = intrinsics_from_fov(320, 240, 90.0)  # tan(45 degrees) = 1, so fx = 160 / 1
        self.assertAlmostEqual(k.fx, 160.0)
        self.assertAlmostEqual(k.fy, 160.0)
        self.assertEqual((k.cx, k.cy), (160.0, 120.0))

    def test_sixty_degree_fov(self):
        k = intrinsics_from_fov(640, 480, 60.0)  # 320 / tan(30 degrees) = 320 * sqrt(3)
        self.assertAlmostEqual(k.fx, 320 * math.sqrt(3))

    def test_narrower_fov_means_longer_focal_length(self):
        self.assertGreater(intrinsics_from_fov(320, 240, 40).fx, intrinsics_from_fov(320, 240, 100).fx)

    def test_rejects_impossible_fov(self):
        for fov in (0, 180, -10):
            with self.assertRaises(ValueError):
                intrinsics_from_fov(320, 240, fov)


class ExtrinsicsTest(unittest.TestCase):
    def axes(self, **rotation):
        m = camera_to_world(Rotation(**{"pitch": 0, "yaw": 0, "roll": 0, **rotation}))
        return [[round(m[i][axis], 9) + 0.0 for i in range(3)] for axis in range(3)]

    def test_identity_rotation(self):
        self.assertEqual(self.axes(), [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def test_yaw_ninety_faces_plus_y_with_right_toward_minus_x(self):
        forward, right, up = self.axes(yaw=90)
        self.assertEqual(forward, [0, 1, 0])
        self.assertEqual(right, [-1, 0, 0])
        self.assertEqual(up, [0, 0, 1])

    def test_pitch_up_points_forward_at_the_sky(self):
        forward, _, up = self.axes(pitch=90)
        self.assertEqual(forward, [0, 0, 1])
        self.assertEqual(up, [-1, 0, 0])

    def test_projection_at_the_centre_and_off_to_the_right(self):
        k = intrinsics_from_fov(320, 240, 90)
        at, flat = Vec3(x=0, y=0, z=0), Rotation(pitch=0, yaw=0, roll=0)
        self.assertEqual(project_point(Vec3(x=100, y=0, z=0), at, flat, k), (160.0, 120.0))
        # 45 degrees right is the image edge when the horizontal fov is 90 degrees.
        u, v = project_point(Vec3(x=100, y=100, z=0), at, flat, k)
        self.assertAlmostEqual(u, 320.0)
        # Higher in the world means a smaller v, since image rows count downward.
        self.assertLess(project_point(Vec3(x=100, y=0, z=50), at, flat, k)[1], 120.0)
        self.assertIsNone(project_point(Vec3(x=-100, y=0, z=0), at, flat, k))


class HeadingTest(unittest.TestCase):
    def test_heading_to(self):
        o = Vec3(x=0, y=0, z=0)
        self.assertAlmostEqual(heading_to(o, Vec3(x=100, y=0, z=0))[0], 0)
        self.assertAlmostEqual(heading_to(o, Vec3(x=0, y=100, z=0))[0], 90)
        self.assertAlmostEqual(heading_to(o, Vec3(x=100, y=0, z=100))[1], 45)

    def test_angle_delta_takes_the_short_way_round(self):
        self.assertAlmostEqual(angle_delta(10, 350), 20)
        self.assertAlmostEqual(angle_delta(350, 10), -20)
        self.assertAlmostEqual(angle_delta(90, 0), 90)
        self.assertAlmostEqual(angle_delta(181, 0), -179)


class HearingTest(unittest.TestCase):
    speaker = Vec3(x=0, y=0, z=0)

    def test_inside_outside_and_exactly_on_the_radius(self):
        listeners = {"near": Vec3(x=999, y=0, z=0), "edge": Vec3(x=1000, y=0, z=0), "far": Vec3(x=1001, y=0, z=0)}
        self.assertEqual(hearing(self.speaker, listeners, 1000), ["edge", "near"])

    def test_distance_is_three_dimensional(self):
        listeners = {"above": Vec3(x=600, y=0, z=900)}  # flat distance is inside, true distance 1082 is not
        self.assertEqual(hearing(self.speaker, listeners, 1000), [])

    def test_nobody_in_range(self):
        self.assertEqual(hearing(self.speaker, {}, 1000), [])


class TimeOfDayTest(unittest.TestCase):
    def at(self, hour, **kwargs):
        return time_of_day(0, hour * 3600.0, **kwargs)

    def test_noon_is_the_peak(self):
        noon = self.at(12)
        self.assertAlmostEqual(noon.sun_elevation_deg, 70.0)
        self.assertAlmostEqual(noon.sun_intensity, 10.0)
        self.assertAlmostEqual(noon.sun_azimuth_deg, 180.0)

    def test_sunrise_and_sunset_sit_on_the_horizon(self):
        self.assertAlmostEqual(self.at(6).sun_elevation_deg, 0.0)
        self.assertAlmostEqual(self.at(18).sun_elevation_deg, 0.0)
        self.assertAlmostEqual(self.at(6).sun_azimuth_deg, 90.0)
        self.assertAlmostEqual(self.at(18).sun_azimuth_deg, 270.0)

    def test_nine_am_is_sin_45_degrees_of_the_peak(self):
        self.assertAlmostEqual(self.at(9).sun_elevation_deg, 70 * math.sin(math.pi / 4))

    def test_midnight_is_below_the_horizon_and_dark(self):
        midnight = self.at(0)
        self.assertAlmostEqual(midnight.sun_elevation_deg, -70.0)
        self.assertEqual(midnight.sun_intensity, 0.0)

    def test_sun_moves_continuously_with_no_jumps_over_a_day(self):
        previous = self.at(0)
        for minute in range(1, 24 * 60 + 1):
            now = time_of_day(minute * 60.0, 0.0)
            self.assertLess(abs(now.sun_elevation_deg - previous.sun_elevation_deg), 0.5)
            self.assertLess(abs(angle_delta(now.sun_azimuth_deg, previous.sun_azimuth_deg)), 0.5)
            previous = now

    def test_thirty_minutes_of_sim_time_moves_the_clock_thirty_minutes(self):
        start = parse_clock("08:00")
        self.assertEqual(time_of_day(1800.0, start).clock, "08:30:00")

    def test_clock_wraps_past_midnight(self):
        self.assertEqual(time_of_day(3600.0, parse_clock("23:30")).clock, "00:30:00")

    def test_clock_parsing(self):
        self.assertEqual(parse_clock("08:30"), 8.5 * 3600)
        self.assertEqual(parse_clock("08:30:15"), 8.5 * 3600 + 15)
        self.assertEqual(format_clock(3661), "01:01:01")
        for bad in ("25:00", "8", "08:60"):
            with self.assertRaises(ValueError):
                parse_clock(bad)

    def test_sun_pitch_sign_and_limit(self):
        self.assertEqual(sun_pitch_from_elevation(45), -45)
        self.assertEqual(sun_pitch_from_elevation(45, sign=1), 45)
        self.assertEqual(sun_pitch_from_elevation(95), -89)


if __name__ == "__main__":
    unittest.main()
