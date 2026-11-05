"""Does the adapter send the same bytes as SimWorld's own client?

Runs the real simworld UnrealCV class against the fake server and compares every command it
sends with our builder in simworld_commands.py. If either side changes, this fails. Also
checks the traps in unrealcv.py that made us bypass it, so that reason stays true.
"""
import unittest

try:
    import unrealcv  # noqa: F401
except ImportError:
    raise unittest.SkipTest("needs unrealcv; run with simworld/.venv")

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from runtime.adapters import simworld_commands as c
from runtime.tests.fake_unrealcv import FakeUnrealCV

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simworld"))  # the worktree's copy, not whatever the venv has installed

try:
    import simworld.communicator.communicator as real_communicator
    import simworld.communicator.unrealcv as real_unrealcv
    IMPORT_ERROR = None
except Exception as e:  # simworld pulls in heavy dependencies, which only its own venv has
    real_unrealcv, real_communicator, IMPORT_ERROR = None, None, e


@unittest.skipIf(IMPORT_ERROR is not None, f"cannot import the real simworld client: {IMPORT_ERROR}")
class ContractTest(unittest.TestCase):
    def setUp(self):
        self.assertIn(str(ROOT), real_unrealcv.__file__, "tested the wrong copy of simworld")
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        # The real class sleeps on the wall clock after many commands. Those sleeps are skipped here.
        patcher = mock.patch.object(real_unrealcv.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ucv = real_unrealcv.UnrealCV(port=self.server.port, resolution=(320, 240))
        self.addCleanup(self.ucv.disconnect)
        self.ucv.get_objects()  # flushes the two setup commands, which are sent without waiting
        self.server.handle("vset /objects/spawn_bp_asset /Game/User_Agent H")
        self.server.handle("vset /objects/spawn_bp_asset /Game/Scooter S")
        self.server.handle("vset /objects/spawn_bp_asset /Game/Mug M")
        self.server.handle("vset /object/H/location 0 0 0")

    def sent_by(self, call):
        """The commands the real client sends for one call. Fake handles every one, or we fail."""
        before = len(self.server.commands)
        rejected = len(self.server.rejected)
        call()
        self.assertEqual(self.server.rejected[rejected:], [], "the fake refused a real client command")
        return self.server.commands[before:]

    def test_connect_setup_matches_ini_unrealcv(self):
        fresh = FakeUnrealCV().start()
        self.addCleanup(fresh.stop)
        client = real_unrealcv.UnrealCV(port=fresh.port, resolution=(320, 240))
        self.addCleanup(client.disconnect)
        deadline_commands = [c.set_resolution(320, 240), c.async_skinned_assets()]
        client.get_objects()  # a synchronous request, so the two async ones before it are done
        self.assertEqual(fresh.commands[1:3], deadline_commands)
        self.assertEqual(fresh.commands[0], "vget /unrealcv/commands")

    def test_every_builder_matches_the_real_client(self):
        u = self.ucv
        pairs = [
            (lambda: u.clean_garbage(), c.clean_garbage()),
            (lambda: u.get_objects(), c.list_objects()),
            (lambda: u.get_cameras(), c.list_cameras()),
            (lambda: u.spawn_bp_asset("/Game/A.A_C", "X"), c.spawn("/Game/A.A_C", "X")),
            (lambda: u.set_location((1, 2.5, 3), "X"), c.set_location("X", 1, 2.5, 3)),
            (lambda: u.set_orientation((1, 2, 3), "X"), c.set_rotation("X", 1, 2, 3)),
            (lambda: u.set_scale((1, 1, 1), "X"), c.set_scale("X", 1, 1, 1)),
            (lambda: u.set_color("X", (1, 2, 3)), c.set_mask_color("X", 1, 2, 3)),
            (lambda: u.set_collision("X", True), c.set_collision("X", True)),
            (lambda: u.set_movable("X", True), c.set_movable("X", True)),
            (lambda: u.set_tick_interval(0.1), c.set_tick_interval(0.1)),
            (lambda: u.tick(), c.tick()),
            (lambda: u.get_location("H"), c.get_location("H")),
            (lambda: u.get_orientation("H"), c.get_rotation("H")),
            (lambda: u.get_collision_num("H"), c.get_collisions("H")),
            (lambda: u.update_objects("H"), c.update_manager("H")),
            (lambda: u.set_object_name("M", "M2"), c.rename("M", "M2")),
            (lambda: u.humanoid_move_forward("H"), c.move_forward("H")),
            (lambda: u.humanoid_rotate("H", 90, "right"), c.turn("H", 90, "right")),
            (lambda: u.humanoid_rotate("H", 90, "left"), c.turn("H", 90, "left")),
            (lambda: u.humanoid_stop("H"), c.stop_agent("H")),
            (lambda: u.humanoid_step_forward("H", 2.5, 1), c.step_forward("H", 2.5, 1)),
            (lambda: u.humanoid_set_speed("H", 150), c.set_speed("H", 150)),
            (lambda: u.humanoid_sit_down("H"), c.sit_down("H")),
            (lambda: u.humanoid_stand_up("H"), c.stand_up("H")),
            (lambda: u.humanoid_pick_up_object("H", "S"), c.pick_up("H", "S")),
            (lambda: u.humanoid_drop_object("H"), c.drop_object("H")),
            (lambda: u.humanoid_enter_vehicle("H", "S"), c.enter_vehicle("H", "S")),
            (lambda: u.humanoid_exit_vehicle("H", "S"), c.exit_vehicle("H", "S")),
            (lambda: u.humanoid_discuss("H", 1), c.discuss("H", 1)),
            (lambda: u.humanoid_argue("H", 1), c.argue("H", 1)),
            (lambda: u.humanoid_listen("H"), c.listen("H")),
            (lambda: u.humanoid_wave_to_dog("H"), c.wave("H")),
            (lambda: u.humanoid_directing_path("H"), c.direct("H")),
            (lambda: u.humanoid_stop_current_action("H"), c.stop_gesture("H")),
            (lambda: u.s_set_state("S", 0.5, 0, 0.1), c.drive("S", 0.5, 0, 0.1)),
            (lambda: u.v_set_state("S", 0.5, 0, 0.1), c.drive("S", 0.5, 0, 0.1)),
            (lambda: u.p_move_forward("H"), c.npc_forward("H")),
            (lambda: u.p_stop("H"), c.npc_stop("H")),
            (lambda: u.p_set_speed("H", 120), c.npc_speed("H", 120)),
            (lambda: u.p_rotate("H", 30, "right"), c.npc_turn("H", 30, "right")),
            (lambda: u.p_rotate("H", 30, "left"), c.npc_turn("H", 30, "left")),
            (lambda: u.get_camera_location(1), c.get_camera_location(1)),
            (lambda: u.get_camera_rotation(1), c.get_camera_rotation(1)),
            (lambda: u.get_camera_fov(1), c.get_camera_fov(1)),
            (lambda: u.get_camera_resolution(1), c.get_camera_size(1)),
            (lambda: u.set_camera_rotation(1, (1, 2, 3)), c.set_camera_rotation(1, 1, 2, 3)),
            (lambda: u.set_camera_fov(1, 90), c.set_camera_fov(1, 90)),
            (lambda: u.set_camera_resolution(1, (320, 240)), c.set_camera_size(1, 320, 240)),
            (lambda: u.set_sun_direction("H", -30, 180), c.set_sun_direction("H", -30, 180)),
            (lambda: u.get_sun_direction("H"), c.get_sun_direction("H")),
            (lambda: u.set_sun_intensity("H", 5), c.set_sun_intensity("H", 5)),
            (lambda: u.get_sun_intensity("H"), c.get_sun_intensity("H")),
            (lambda: u.set_fog("H", 1, 2, 0.5), c.set_fog("H", 1, 2, 0.5)),
            (lambda: u.get_fog("H"), c.get_fog("H")),
            (lambda: u.set_atmosphere("H", 1, 2), c.set_atmosphere("H", 1, 2)),
            (lambda: u.get_atmosphere("H"), c.get_atmosphere("H")),
            (lambda: u.destroy("X"), c.destroy("X")),
        ]
        for call, expected in pairs:
            with self.subTest(expected=expected):
                self.assertEqual(self.sent_by(call), [expected])

    def test_set_mode_sends_interval_then_pause(self):
        sent = self.sent_by(lambda: self.ucv.set_mode("sync", 0.1))
        self.assertEqual(sent, [c.set_tick_interval(0.1), c.pause()])
        self.assertEqual(self.sent_by(lambda: self.ucv.set_mode("async")), [c.resume()])

    def test_scooter_commands_match(self):
        self.assertEqual(self.sent_by(lambda: self.ucv.humanoid_get_on_scooter("H")),
                         [c.get_on_scooter("H"), c.clean_garbage()])
        self.assertEqual(self.sent_by(lambda: self.ucv.humanoid_get_off_scooter("S")), [c.get_off_scooter("S")])

    def test_render_commands_match(self):
        for viewmode, builder in (("lit", c.render(1, "lit", "png")), ("object_mask", c.render(1, "object_mask", "png")),
                                  ("depth", c.render(1, "depth", "npy"))):
            with self.subTest(viewmode=viewmode):
                self.assertEqual(self.sent_by(lambda: self.ucv.get_image(1, viewmode)), [builder])


@unittest.skipIf(IMPORT_ERROR is not None, f"cannot import the real simworld client: {IMPORT_ERROR}")
class WhyWeBypassUnrealcvPyTest(unittest.TestCase):
    """Each test pins one reason the adapter does not call unrealcv.py. If one fails, re-read it."""

    def setUp(self):
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        patcher = mock.patch.object(real_unrealcv.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self.ucv = real_unrealcv.UnrealCV(port=self.server.port, resolution=(320, 240))
        self.addCleanup(self.ucv.disconnect)
        self.ucv.get_objects()  # flushes the two setup commands, which are sent without waiting
        self.server.handle("vset /objects/spawn_bp_asset /Game/User_Agent H")
        self.sleep.reset_mock()

    def test_get_image_hides_errors_behind_a_black_frame(self):
        self.server.refuse.add("vget /camera/1/lit")
        image = self.ucv.get_image(1, "lit")
        self.assertEqual(image.shape, (480, 640, 3))
        self.assertEqual(int(image.sum()), 0)

    def test_get_image_turns_depth_into_a_false_colour_picture(self):
        image = self.ucv.get_image(1, "depth")
        self.assertEqual(image.dtype, np.uint8)
        self.assertEqual(image.ndim, 3)

    def test_step_forward_and_rotate_sleep_on_the_wall_clock(self):
        self.ucv.humanoid_step_forward("H", 30, 0)
        self.sleep.assert_called_with(30)
        self.ucv.humanoid_rotate("H", 90, "right")
        self.sleep.assert_called_with(1)

    def test_get_success_helpers_lose_boolean_replies(self):
        self.server.reply_as_bool = True
        # str(True) is 'True', which matches neither 'true' nor 'false' at unrealcv.py:681-684.
        self.assertIsNone(self.ucv.humanoid_sit_down("H"))


if __name__ == "__main__":
    unittest.main()
