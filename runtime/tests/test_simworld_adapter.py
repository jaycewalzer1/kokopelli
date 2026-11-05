"""The adapter against the fake server: lifecycle, stepping, state, renders, actions, weather, timing."""
import unittest

try:
    import unrealcv  # noqa: F401
except ImportError:
    raise unittest.SkipTest("needs unrealcv; run with simworld/.venv")

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from runtime.adapters.simworld import (AGENT_ACTOR, AGENT_ASSET, BOX_ASSET, WEATHER_ACTOR, WEATHER_ASSET,
                                       SimWorldConfig, SimWorldPhysics)
from runtime.adapters.simworld_wire import CommandError, SimWorldError
from runtime.physics import PhysicalState, PhysicsSim, StepResult
from runtime.tests.fake_unrealcv import FakeUnrealCV

FAST = dict(tick_interval_s=0.5, control_interval_s=0.5, settle_s=0, init_settle_s=0, reconnect_backoff_s=0.01,
            agent_position=(0.0, 0.0, 100.0), request_timeout_s=5.0, connect_timeout_s=5.0)


class AdapterCase(unittest.TestCase):
    """Starts a fake server and a connected adapter, with renders going to a temp folder."""
    config: dict = {}

    def setUp(self):
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        folder = tempfile.TemporaryDirectory(prefix="wmloop_")
        self.addCleanup(folder.cleanup)
        self.out = Path(folder.name)
        self.sim = self.make_sim()
        self.addCleanup(self.sim.close)
        self.first = self.sim.reset()

    def make_sim(self, **overrides) -> SimWorldPhysics:
        settings = {**FAST, "port": self.server.port, "out_dir": str(self.out), **self.config, **overrides}
        return SimWorldPhysics(SimWorldConfig(**settings))

    def replace_sim(self, **overrides) -> SimWorldPhysics:
        """UnrealCV serves one client at a time, so hang up the current one first."""
        self.sim.close()
        self.sim = self.make_sim(**overrides)
        self.addCleanup(self.sim.close)
        return self.sim

    def agent(self):
        return self.server.actors[AGENT_ACTOR]

    def commands_since(self, count):
        return self.server.commands[count:]


class LifecycleTest(AdapterCase):
    def test_implements_physics_sim(self):
        self.assertIsInstance(self.sim, PhysicsSim)

    def test_reset_spawns_everything_and_pauses(self):
        names = set(self.server.actors)
        self.assertIn(AGENT_ACTOR, names)
        self.assertIn("GEN_BP_Pedestrian_0", names)
        self.assertIn("GEN_BP_Pedestrian_1", names)
        self.assertIn("GEN_BP_mug_0", names)
        self.assertIn("GEN_BP_Scooter_0", names)
        self.assertIn(WEATHER_ACTOR, names)
        self.assertTrue(self.server.paused)
        self.assertEqual(self.server.tick_interval, 0.5)
        self.assertEqual(self.server.rejected, [])

    def test_agent_spawns_first_so_it_gets_camera_one(self):
        self.assertEqual(self.sim.camera_id, 1)
        self.assertEqual(self.server.cameras[1].owner, AGENT_ACTOR)
        spawns = [cmd for cmd in self.server.commands if "spawn_bp_asset" in cmd]
        self.assertIn(AGENT_ASSET, spawns[0])

    def test_uses_the_real_setup_commands_on_connect(self):
        self.assertIn("vrun Editor.AsyncSkinnedAssetCompilation 2", self.server.commands)
        self.assertEqual(self.server.window, (320, 240))

    def test_close_resumes_and_disconnects_and_can_repeat(self):
        self.sim.close()
        self.assertFalse(self.server.paused)
        self.assertFalse(self.sim.wire.connected)
        self.sim.close()

    def test_step_before_reset_is_a_clear_error(self):
        sim = self.make_sim()
        with self.assertRaisesRegex(SimWorldError, "reset"):
            sim.step({"type": "wait"})

    def test_second_reset_replaces_our_actors_and_restarts_time(self):
        self.sim.step({"type": "wait"})
        self.sim.reset(seed=1)
        self.assertEqual(self.sim.tick_count, 0)
        self.assertEqual(len([a for a in self.server.actors if a == AGENT_ACTOR]), 1)
        self.assertTrue(self.server.paused)

    def test_reset_unpauses_a_server_left_paused_by_a_crashed_client(self):
        self.sim.wire.close()  # the old client vanished without resuming
        self.assertTrue(self.server.paused)
        self.replace_sim()
        count = len(self.server.commands)
        self.sim.reset()
        sent = self.commands_since(count)
        first_spawn = next(i for i, cmd in enumerate(sent) if "spawn_bp_asset" in cmd)
        self.assertLess(sent.index("vset /action/game/resume"), first_spawn)

    def test_a_second_reset_does_not_overwrite_earlier_renders(self):
        first = self.first.renders["rgb"].path
        second = self.sim.reset().renders["rgb"].path
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).exists())

    def test_second_reset_leaves_level_actors_alone(self):
        self.server.handle("vset /objects/spawn_bp_asset /Game/Level/Tree Tree_1")
        self.sim.reset()
        self.assertIn("Tree_1", self.server.actors)

    def test_missing_asset_is_a_clear_error_naming_the_actor(self):
        self.server.missing_assets.add(BOX_ASSET)
        with self.assertRaisesRegex(CommandError, "GEN_BP_box_0"):
            self.replace_sim().reset()

    def test_missing_weather_manager_is_a_warning_not_a_crash(self):
        self.server.missing_assets.add(WEATHER_ASSET)
        sim = self.replace_sim()
        capture = sim.reset()
        self.assertFalse(capture.state.weather.available)
        self.assertTrue(any("WeatherManager" in w for w in sim.warnings))
        self.assertIsInstance(sim.step({"type": "wait"}), StepResult)

    def test_map_path_uses_the_level_command(self):
        self.replace_sim(map_path="/Game/Maps/demo_2").reset()
        self.assertEqual(self.server.level, "/Game/Maps/demo_2")
        self.assertIn(AGENT_ACTOR, self.server.actors)


class SteppingTest(AdapterCase):
    def test_one_step_is_exactly_thirty_sim_seconds_of_ticks(self):
        before = self.server.tick_count
        result = self.sim.step({"type": "wait"})
        self.assertEqual(self.server.tick_count - before, 60)  # 30s at 0.5s per tick
        self.assertEqual(result.ticks_advanced, 60)
        self.assertEqual(result.tick_start, 0)
        self.assertEqual(result.tick_end, 60)
        self.assertEqual(result.sim_time_s, 30.0)

    def test_tick_interval_is_configurable(self):
        for interval, ticks in ((0.1, 300), (0.25, 120)):
            sim = self.replace_sim(tick_interval_s=interval, control_interval_s=1.0, restore_flush_s=1.0)
            sim.reset()
            before = self.server.tick_count
            self.assertEqual(sim.step({"type": "wait"}).ticks_advanced, ticks)
            self.assertEqual(self.server.tick_interval, interval)
            self.assertEqual(self.server.tick_count - before, ticks)

    def test_rejects_an_interval_that_does_not_divide_the_step(self):
        with self.assertRaisesRegex(ValueError, "whole number"):
            SimWorldConfig(tick_interval_s=0.07)

    def test_rejects_a_step_that_does_not_end_on_a_capture(self):
        with self.assertRaisesRegex(ValueError, "end of the step"):
            SimWorldConfig(capture_offsets_s=(15.0,))

    def test_captures_land_at_fifteen_and_thirty(self):
        result = self.sim.step({"type": "wait"})
        self.assertEqual([c.offset_s for c in result.captures], [15.0, 30.0])
        self.assertEqual([c.tick_count for c in result.captures], [30, 60])
        self.assertEqual([c.sim_time_s for c in result.captures], [15.0, 30.0])
        self.assertEqual([c.state.tick_count for c in result.captures], [30, 60])

    def test_capture_really_happens_between_the_right_ticks(self):
        count = len(self.server.commands)
        self.sim.step({"type": "wait"})
        ticks = 0
        ticks_at_render = []
        for cmd in self.commands_since(count):
            if cmd == "vset /action/tick":
                ticks += 1
            elif cmd.endswith("/lit png"):
                ticks_at_render.append(ticks)
        self.assertEqual(ticks_at_render, [30, 60])

    def test_action_is_applied_before_the_first_tick(self):
        count = len(self.server.commands)
        self.sim.step({"type": "step_forward", "duration_s": 1})
        sent = self.commands_since(count)
        self.assertLess(sent.index(f"vbp {AGENT_ACTOR} StepForward 1.0 0"), sent.index("vset /action/tick"))

    def test_tick_count_accumulates_and_sim_time_follows_ticks(self):
        before = self.server.tick_count
        for n in range(1, 4):
            result = self.sim.step({"type": "wait"})
            self.assertEqual(result.step_index, n)
            self.assertEqual(result.tick_end, 60 * n)
            self.assertEqual(result.sim_time_s, 30.0 * n)
        self.assertEqual(self.server.tick_count - before, 180)

    def test_invalid_action_changes_nothing(self):
        count = len(self.server.commands)
        for bad in ({"type": "fly"}, {"type": "pick_up", "target_id": "ghost"}, {"type": "interact", "target_id": "npc_0"}):
            with self.assertRaises(ValidationError):
                self.sim.step(bad)
        self.assertEqual(len(self.server.commands), count)
        self.assertEqual(self.sim.tick_count, 0)

    def test_timing_fields_are_all_present_and_add_up(self):
        t = self.sim.step({"type": "wait"}).timing
        self.assertGreater(t.stepping_s, 0)
        self.assertGreater(t.state_capture_s, 0)
        self.assertGreaterEqual(t.action_apply_s, 0)
        self.assertEqual(set(t.render_s), {"15s:rgb", "15s:depth", "15s:segmentation",
                                           "30s:rgb", "30s:depth", "30s:segmentation"})
        self.assertTrue(all(v > 0 for v in t.render_s.values()))
        parts = t.action_apply_s + t.stepping_s + t.control_s + t.state_capture_s + sum(t.render_s.values())
        self.assertLessEqual(parts, t.total_s)
        self.assertGreater(t.commands_sent, 60)


class StateTest(AdapterCase):
    def test_serialization_round_trip(self):
        state = self.sim.step({"type": "move_to", "position": {"x": 5000, "y": 0, "z": 0}}).final_state
        text = state.to_json()
        json.loads(text)
        self.assertEqual(PhysicalState.from_json(text), state)

    def test_step_result_is_fully_json_serializable(self):
        result = self.sim.step({"type": "speak", "text": "hi"})
        self.assertEqual(StepResult.model_validate_json(result.model_dump_json()), result)

    def test_npcs_have_stable_ids_across_steps(self):
        ids = [n.id for n in self.first.state.npcs]
        self.assertEqual(ids, ["npc_0", "npc_1"])
        for _ in range(2):
            self.assertEqual([n.id for n in self.sim.step({"type": "wait"}).final_state.npcs], ids)

    def test_npc_pose_comes_from_the_server(self):
        state = self.sim.read_state()
        npc = self.server.actors["GEN_BP_Pedestrian_0"]
        self.assertAlmostEqual(state.npcs[0].pose.location.x, npc.location[0], places=4)

    def test_objects_have_state(self):
        by_id = {o.id: o for o in self.first.state.objects}
        self.assertEqual(by_id["mug_0"].kind, "object")
        self.assertTrue(by_id["mug_0"].present)
        self.assertIsNone(by_id["mug_0"].held_by)
        self.assertEqual(by_id["scooter_0"].kind, "scooter")

    def test_velocity_is_a_labelled_finite_difference(self):
        velocity = self.first.state.agent.velocity
        self.assertEqual(velocity.source, "finite_difference")
        self.assertEqual(velocity.window_s, 0.0)  # no earlier pose at time zero
        moving = self.sim.step({"type": "move_forward"}).final_state.agent.velocity
        self.assertEqual(moving.source, "finite_difference")
        self.assertEqual(moving.window_s, 1.0)
        self.assertAlmostEqual(moving.speed_cm_s, 200.0, places=3)  # the fake walks at the speed we set
        self.assertAlmostEqual(moving.vector_cm_s.x, 200.0, places=3)

    def test_camera_intrinsics_and_extrinsics(self):
        camera = self.first.state.camera
        self.assertEqual(camera.camera_id, 1)
        self.assertEqual((camera.intrinsics.width, camera.intrinsics.height), (320, 240))
        self.assertAlmostEqual(camera.intrinsics.fx, 160.0)  # fake's fov is 90 degrees
        self.assertAlmostEqual(camera.extrinsics.location_cm.z, 260.0)  # agent z 100 + fake's eye height 160
        self.assertEqual(camera.extrinsics.camera_to_world[0][0], 1.0)

    def test_time_of_day_uses_ticks_not_wall_clock(self):
        self.assertEqual(self.first.state.time_of_day.clock, "08:00:00")
        result = self.sim.step({"type": "wait"})
        self.assertEqual(result.captures[0].state.time_of_day.clock, "08:00:15")
        self.assertEqual(result.captures[1].state.time_of_day.clock, "08:00:30")

    def test_prompt_text_is_compact_and_informative(self):
        text = self.first.state.to_prompt_text()
        self.assertIn("clock=08:00:00", text)
        self.assertIn("npc_0", text)
        self.assertIn("mug_0", text)
        self.assertLess(len(text), 800)
        self.assertNotIn("camera_to_world", text)

    def test_seeded_npc_layout_is_repeatable_and_seed_dependent(self):
        def layout(seed):
            sim = self.replace_sim()
            sim.reset(seed=seed)
            return [n.waypoints for n in sim.npc_specs]
        self.assertEqual(layout(7), layout(7))
        self.assertNotEqual(layout(7), layout(8))


class RenderTest(AdapterCase):
    def test_all_three_modalities_saved_with_correct_hash(self):
        renders = self.first.renders
        self.assertEqual(set(renders), {"rgb", "depth", "segmentation"})
        for render in renders.values():
            data = Path(render.path).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), render.sha256)
            self.assertEqual(len(data), render.num_bytes)
            self.assertEqual((render.width, render.height), (320, 240))

    def test_depth_is_raw_values_not_a_colour_picture(self):
        render = self.first.renders["depth"]
        array = np.load(render.path)
        self.assertEqual(array.ndim, 2)
        self.assertEqual(array.dtype, np.float32)
        self.assertGreater(render.depth_stats["median"], 1000)

    def test_resolution_is_configurable(self):
        capture = self.replace_sim(resolution=(64, 48), run_id="small").reset()
        self.assertEqual(capture.renders["rgb"].width, 64)
        self.assertEqual(capture.state.camera.intrinsics.width, 64)
        self.assertAlmostEqual(capture.state.camera.intrinsics.fx, 32.0)

    def test_files_do_not_collide_across_offsets_and_steps(self):
        paths = {r.path for r in self.first.renders.values()}
        for _ in range(2):
            for capture in self.sim.step({"type": "wait"}).captures:
                paths |= {r.path for r in capture.renders.values()}
        self.assertEqual(len(paths), 3 + 2 * 2 * 3)

    def test_render_error_raises_instead_of_a_black_frame(self):
        self.server.refuse.add("vget /camera/1/lit")
        with self.assertRaises(CommandError):
            self.sim.step({"type": "wait"})

    def test_garbage_image_reply_raises(self):
        original = self.server._render_lit
        self.server._render_lit = lambda index, fmt: b"\xff\xfenot a png"
        self.addCleanup(lambda: setattr(self.server, "_render_lit", original))
        with self.assertRaisesRegex(CommandError, "not a PNG"):
            self.sim.render("rgb", 0)

    def test_mask_color_map_links_colours_to_ids(self):
        colors = {m.id: m for m in self.first.mask_colors}
        self.assertEqual(set(colors), {"agent", "npc_0", "npc_1", "mug_0", "box_0", "scooter_0"})
        self.assertEqual(colors["npc_0"].actor, "GEN_BP_Pedestrian_0")
        self.assertEqual(colors["npc_0"].assigned_rgb, colors["npc_0"].readback_rgb)
        rgb = [tuple(m.assigned_rgb) for m in colors.values()]
        self.assertEqual(len(set(rgb)), len(rgb), "two actors share a colour")

    def test_mask_map_survives_a_server_that_cannot_report_colours(self):
        self.server.refuse.add("vget /object/GEN_BP_mug_0/color")
        colors = {m.id: m for m in self.replace_sim().reset().mask_colors}
        self.assertIsNone(colors["mug_0"].readback_rgb)
        self.assertIsNotNone(colors["mug_0"].assigned_rgb)


class TimeAndWeatherTest(AdapterCase):
    def test_sun_follows_the_formula(self):
        self.assertAlmostEqual(self.server.sun_pitch, -70 * math.sin(math.pi / 6), places=3)  # 08:00 is 1/6 of the day
        self.assertAlmostEqual(self.server.sun_yaw, 120.0, places=3)

    def test_sun_is_updated_for_each_capture(self):
        count = len(self.server.commands)
        self.sim.step({"type": "wait"})
        sets = [c for c in self.commands_since(count) if "SetSunDirection" in c]
        self.assertEqual(len(sets), 2)
        self.assertNotEqual(sets[0], sets[1])

    def test_state_reports_what_the_server_has(self):
        weather = self.sim.step({"type": "wait"}).final_state.weather
        self.assertTrue(weather.available)
        self.assertEqual(weather.sun_pitch_deg, self.server.sun_pitch)
        self.assertEqual(weather.sun_intensity, self.server.sun_intensity)

    def test_set_clock_jumps_the_sun(self):
        self.sim.step({"type": "wait"})
        self.assertEqual(self.sim.set_clock("12:00").clock, "12:00:00")
        self.assertAlmostEqual(self.server.sun_pitch, -70.0, places=3)
        self.assertEqual(self.sim.tick_count, 60)  # sim time keeps counting
        self.assertEqual(self.sim.step({"type": "wait"}).final_state.time_of_day.clock, "12:00:30")

    def test_night_clock_sets_intensity_to_zero(self):
        self.sim.set_clock("23:00")
        self.assertEqual(self.server.sun_intensity, 0.0)

    def test_set_weather_round_trip(self):
        weather = self.sim.set_weather(fog=(10, 2000, 0.5), atmosphere=(0.3, 0.2))
        self.assertEqual(self.server.fog, (10.0, 2000.0, 0.5))
        self.assertEqual((weather.fog_density, weather.fog_distance_cm, weather.fog_falloff), (10.0, 2000.0, 0.5))
        self.assertEqual((weather.rayleigh, weather.mie), (0.3, 0.2))

    def test_set_weather_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            self.sim.set_weather(fog=(101, 0, 0))
        with self.assertRaises(ValueError):
            self.sim.set_weather(atmosphere=(3, 0))

    def test_max_intensity_is_configurable(self):
        self.replace_sim(max_sun_intensity=50.0).reset()
        self.assertAlmostEqual(self.server.sun_intensity, 25.0, places=3)  # 08:00 is sin(30 degrees) of the peak

    def test_rerunning_on_the_same_server_does_not_dim_the_sun(self):
        """Regression: the maximum used to be read back from the server, so it was our own last value."""
        first = self.server.sun_intensity
        for _ in range(3):
            self.replace_sim().reset()
            self.assertAlmostEqual(self.server.sun_intensity, first, places=3)

    def test_records_what_the_level_had_at_first_contact(self):
        self.assertEqual(self.sim.initial_weather.sun_pitch_deg, -26.0)  # the fake's starting value


class DeterminismTest(unittest.TestCase):
    def run_once(self):
        with FakeUnrealCV() as server, tempfile.TemporaryDirectory(prefix="wmloop_") as out:
            sim = SimWorldPhysics(SimWorldConfig(**FAST, port=server.port, out_dir=out, seed=3))
            sim.reset()
            hashes = []
            for action in ({"type": "move_to", "position": {"x": 500, "y": 300, "z": 0}}, {"type": "wait"}):
                for capture in sim.step(action).captures:
                    hashes.append({m: r.sha256 for m, r in capture.renders.items()})
                    hashes.append(capture.state.agent.pose.model_dump())
            commands = list(server.commands)
            sim.close()
            return hashes, commands

    def test_same_seed_sends_the_same_commands_and_gets_the_same_frames(self):
        first, second = self.run_once(), self.run_once()
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[0], second[0])


if __name__ == "__main__":
    unittest.main()
