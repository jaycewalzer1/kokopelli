"""Checkpoint and restore, and what happens when the server misbehaves. All failures must end."""
import unittest

try:
    import unrealcv  # noqa: F401
except ImportError:
    raise unittest.SkipTest("needs unrealcv; run with simworld/.venv")

import tempfile
import time
import unittest
from pathlib import Path

from kokopelli.loop.adapters.simworld import AGENT_ACTOR, NOT_RESTORED, SimWorldConfig, SimWorldPhysics
from kokopelli.loop.adapters.simworld_wire import (CommandError, ConnectionLostError, ServerDownError, ServerNotReadyError,
                                            SimWorldError, Wire, probe_server, wait_for_server)
from kokopelli.loop.physics import SimCheckpoint
from kokopelli.loop.tests.fake_unrealcv import FakeUnrealCV
from kokopelli.loop.tests.test_simworld_adapter import FAST, AdapterCase


class CheckpointTest(AdapterCase):
    def test_checkpoint_survives_json_and_disk(self):
        self.sim.step({"type": "move_to", "position": {"x": 20000, "y": 0, "z": 0}})
        checkpoint = self.sim.get_state()
        path = checkpoint.save(self.out / "wmloop_nested" / "ck.json")
        self.assertEqual(SimCheckpoint.load(path), checkpoint)
        self.assertEqual(checkpoint.seeds, {"master": 0})
        self.assertEqual(checkpoint.not_restored, NOT_RESTORED)

    def test_later_steps_cannot_change_a_checkpoint_already_taken(self):
        """Regression: backend_state used to hold live references to the adapter's dicts."""
        checkpoint = self.sim.get_state()
        before = checkpoint.model_dump_json()
        for _ in range(3):
            self.sim.step({"type": "move_forward"})
        self.assertEqual(checkpoint.model_dump_json(), before)

    def test_checkpoint_equals_its_copy_on_disk_with_weather_set(self):
        """Regression: fog is a tuple in memory and a list after JSON, so these once differed."""
        self.sim.set_weather(fog=(10, 2000, 0.5), atmosphere=(0.3, 0.2))
        checkpoint = self.sim.get_state()
        self.assertEqual(SimCheckpoint.load(checkpoint.save(self.out / "ck.json")), checkpoint)

    def test_restore_puts_actors_back_and_rewinds_time(self):
        self.sim.step({"type": "move_forward"})
        checkpoint = self.sim.get_state()
        where = checkpoint.physical.agent.pose.location
        self.sim.step({"type": "move_forward"})
        self.assertGreater(self.server.actors[AGENT_ACTOR].location[0], where.x + 1000)

        report = self.sim.restore_state(checkpoint)
        self.assertTrue(report.ok)
        self.assertLess(report.max_position_error_cm, 0.01)
        self.assertEqual(report.respawned, [])
        self.assertAlmostEqual(self.server.actors[AGENT_ACTOR].location[0], where.x, places=3)
        self.assertEqual(self.sim.tick_count, checkpoint.tick_count)
        self.assertEqual(self.sim.step_index, checkpoint.step_index)
        self.assertEqual(self.sim.step({"type": "wait"}).tick_start, checkpoint.tick_count)

    def test_a_turn_in_flight_does_not_keep_rotating_a_restored_actor(self):
        checkpoint = self.sim.get_state()
        npc = checkpoint.physical.npcs[0]
        actor = self.server.actors[npc.actor]
        actor.turn_left, actor.turn_rate = 90.0, 90.0  # the fake's stop does not cancel a turn
        self.sim.restore_state(checkpoint)
        self.assertEqual(actor.turn_left, 0.0)
        self.assertAlmostEqual(actor.rotation[1], npc.pose.rotation.yaw, places=3)

    def test_restore_report_measures_instead_of_assuming(self):
        checkpoint = self.sim.get_state()
        self.server.restore_noise_cm = 50.0
        report = self.sim.restore_state(checkpoint)
        self.assertFalse(report.ok)
        self.assertAlmostEqual(report.max_position_error_cm, 50.0, places=3)
        self.assertIn("agent", report.position_errors_cm)

    def test_null_agent_replays_the_same_from_a_checkpoint(self):
        """The counterfactual: same start, null actions twice. On the fake this must match exactly."""
        start = self.sim.get_state()
        first = [self.sim.step({"type": "wait"}).final_state.npcs[0].pose for _ in range(2)]
        self.sim.restore_state(start)
        second = [self.sim.step({"type": "wait"}).final_state.npcs[0].pose for _ in range(2)]
        for a, b in zip(first, second):
            self.assertAlmostEqual(a.location.x, b.location.x, delta=0.01)
            self.assertAlmostEqual(a.location.y, b.location.y, delta=0.01)

    def test_counterfactual_can_diverge_from_the_same_start(self):
        start = self.sim.get_state()
        acted = self.sim.step({"type": "move_forward"}).final_state.agent.pose.location.x
        self.sim.restore_state(start)
        null = self.sim.step({"type": "wait"}).final_state.agent.pose.location.x
        self.assertGreater(acted, null + 1000)

    def test_replay_does_not_overwrite_earlier_renders(self):
        start = self.sim.get_state()
        first = self.sim.step({"type": "wait"}).captures[0].renders["rgb"]
        self.sim.restore_state(start)
        second = self.sim.step({"type": "wait"}).captures[0].renders["rgb"]
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(Path(first.path).exists())

    def test_restore_brings_back_a_running_task(self):
        self.sim.step({"type": "move_to", "position": {"x": 20000, "y": 0, "z": 100}})
        checkpoint = self.sim.get_state()
        self.sim.step({"type": "wait"})
        self.assertIsNone(self.sim.task)
        self.sim.restore_state(checkpoint)
        self.assertEqual(self.sim.task.goal_x, 20000)
        result = self.sim.step({"type": "continue"})
        self.assertGreater(result.final_state.agent.pose.location.x, checkpoint.physical.agent.pose.location.x + 4000)

    def test_restore_undoes_a_later_scooter_ride(self):
        self.server.actors["GEN_BP_Scooter_0"].location = [50.0, 0.0, 100.0]
        checkpoint = self.sim.get_state()
        self.sim.step({"type": "interact", "target_id": "scooter_0"})
        self.assertNotIn(AGENT_ACTOR, self.server.actors)
        self.sim.restore_state(checkpoint)
        self.assertIn(AGENT_ACTOR, self.server.actors)
        self.assertEqual(self.sim.posture, "standing")
        self.assertIsNone(self.sim.riding)
        self.assertEqual(self.sim.step({"type": "step_forward", "duration_s": 1}).outcome.status, "completed")

    def test_restore_undoes_a_later_pick_up_and_sit(self):
        self.server.actors["GEN_BP_mug_0"].location = [50.0, 0.0, 100.0]
        checkpoint = self.sim.get_state()
        self.sim.step({"type": "pick_up", "target_id": "mug_0"})
        self.sim.step({"type": "sit_down"})
        report = self.sim.restore_state(checkpoint)
        self.assertTrue(report.ok)
        self.assertIsNone(self.sim.held)
        self.assertEqual(self.sim.posture, "standing")
        self.assertIsNone(self.server.actors[AGENT_ACTOR].holding)
        self.assertFalse(self.server.actors[AGENT_ACTOR].sitting)

    def test_restore_brings_back_held_and_seated_state(self):
        self.server.actors["GEN_BP_mug_0"].location = [50.0, 0.0, 100.0]
        self.sim.step({"type": "pick_up", "target_id": "mug_0"})
        checkpoint = self.sim.get_state()
        self.sim.step({"type": "drop_object"})
        self.sim.restore_state(checkpoint)
        self.assertEqual(self.sim.held, "mug_0")
        self.assertEqual(self.server.actors[AGENT_ACTOR].holding, "GEN_BP_mug_0")

    def test_restore_brings_back_clock_and_weather(self):
        self.sim.set_weather(fog=(10, 2000, 0.5))
        self.sim.set_clock("12:00")
        checkpoint = self.sim.get_state()
        self.sim.set_weather(fog=(90, 100, 1.0))
        self.sim.set_clock("20:00")
        self.sim.restore_state(checkpoint)
        self.assertEqual(self.server.fog, (10.0, 2000.0, 0.5))
        self.assertAlmostEqual(self.server.sun_pitch, -70.0, places=3)

    def test_crash_resume_in_a_new_process_on_a_restarted_server(self):
        self.sim.step({"type": "move_forward"})
        path = self.sim.get_state().save(self.out / "ck.json")
        tick, where = self.sim.tick_count, self.server.actors[AGENT_ACTOR].location[0]
        self.sim.wire.close()  # the client process died
        self.server.reset_world()  # and the server restarted: empty, unpaused world

        fresh = self.replace_sim()
        report = fresh.restore_state(SimCheckpoint.load(path))
        self.assertTrue(report.ok, report)
        self.assertIn(AGENT_ACTOR, report.respawned)
        self.assertEqual(fresh.tick_count, tick)
        self.assertAlmostEqual(self.server.actors[AGENT_ACTOR].location[0], where, places=3)
        self.assertTrue(self.server.paused)
        self.assertEqual(fresh.camera_id, 1)
        self.assertEqual(fresh.step({"type": "wait"}).tick_end, tick + 60)

    def test_restore_refuses_a_different_tick_interval(self):
        checkpoint = self.sim.get_state()
        other = self.make_sim(tick_interval_s=0.25)  # refused before it ever connects
        with self.assertRaisesRegex(ValueError, "tick interval"):
            other.restore_state(checkpoint)

    def test_not_restored_list_is_specific(self):
        text = " ".join(self.sim.get_state().not_restored)
        for honest in ("velocity", "animation", "NPC controller", "traffic", "renderer"):
            self.assertIn(honest, text)


class ServerDownTest(unittest.TestCase):
    def unused_port(self):
        server = FakeUnrealCV().start()
        port = server.port
        server.stop()
        return port

    def test_server_down_is_a_clear_bounded_error(self):
        port = self.unused_port()
        sim = SimWorldPhysics(SimWorldConfig(**{**FAST, "reconnect_attempts": 2}, port=port))
        started = time.monotonic()
        with self.assertRaisesRegex(ServerDownError, r"gave up after 3 attempts.*nothing listening"):
            sim.reset()
        self.assertLess(time.monotonic() - started, 5)

    def test_server_not_ready_is_a_clear_bounded_error(self):
        with FakeUnrealCV() as server:
            server.silent_hello = True
            sim = SimWorldPhysics(SimWorldConfig(**{**FAST, "reconnect_attempts": 0, "connect_timeout_s": 0.3}, port=server.port))
            started = time.monotonic()
            with self.assertRaisesRegex(ServerNotReadyError, "still loading"):
                sim.reset()
            self.assertLess(time.monotonic() - started, 5)

    def test_probe_reports_each_state(self):
        with self.assertRaises(ServerDownError):
            probe_server("127.0.0.1", self.unused_port(), 0.5)
        with FakeUnrealCV() as server:
            self.assertTrue(probe_server("127.0.0.1", server.port, 2).startswith("connected"))
            time.sleep(0.05)
            server.silent_hello = True
            with self.assertRaisesRegex(ServerNotReadyError, "no UnrealCV hello"):
                probe_server("127.0.0.1", server.port, 0.3)

    def test_wait_for_server_times_out_and_succeeds_when_the_server_appears(self):
        port = self.unused_port()
        started = time.monotonic()
        with self.assertRaises(ServerDownError):
            wait_for_server("127.0.0.1", port, timeout=0.3, poll_s=0.1)
        self.assertLess(time.monotonic() - started, 3)
        with FakeUnrealCV() as server:
            self.assertTrue(wait_for_server("127.0.0.1", server.port, timeout=2, poll_s=0.1))

    def test_second_client_gets_a_clear_refusal(self):
        with FakeUnrealCV() as server:
            first = Wire("127.0.0.1", server.port, reconnect_attempts=0)
            first.connect()
            self.addCleanup(first.close)
            second = Wire("127.0.0.1", server.port, reconnect_attempts=0)
            with self.assertRaisesRegex(ServerNotReadyError, "busy|refused"):
                second.connect()
            self.assertGreaterEqual(server.busy_rejections, 1)


class WireTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        self.wire = Wire("127.0.0.1", self.server.port, request_timeout=0.5, reconnect_attempts=2, reconnect_backoff_s=0.01)
        self.wire.connect()
        self.addCleanup(self.wire.close)

    def test_read_is_resent_after_a_dropped_link(self):
        self.server.drop_on = "vget /objects"
        self.assertEqual(self.wire.request("vget /objects"), "")
        self.assertEqual(self.wire.reconnects, 1)

    def test_write_is_never_resent_after_a_dropped_link(self):
        self.server.drop_on = "vset /action/game/pause"
        with self.assertRaisesRegex(ConnectionLostError, "may or may not"):
            self.wire.request("vset /action/game/pause")
        self.assertEqual(self.server.commands.count("vset /action/game/pause"), 0)
        self.assertTrue(self.wire.connected)

    def test_timeout_drops_the_connection_so_a_late_reply_cannot_answer_the_next_request(self):
        self.server.hang_on = "vget /objects"
        self.server.handle("vset /objects/spawn_bp_asset /Game/Mug Marker")
        self.assertEqual(self.wire.request("vget /objects"), "Marker")
        self.assertEqual(self.wire.reconnects, 1)
        self.assertEqual(self.wire.request("vget /cameras"), "cam0")  # not the stale object list

    def test_reconnects_are_bounded_when_the_server_is_gone(self):
        self.server.stop()
        started = time.monotonic()
        with self.assertRaisesRegex(ServerDownError, "gave up after 3 attempts"):
            self.wire.request("vget /objects")
        self.assertLess(time.monotonic() - started, 3)

    def test_server_error_replies_raise_command_error(self):
        with self.assertRaisesRegex(CommandError, "does not know"):
            self.wire.request("vget /not/a/command")

    def test_advertised_commands_are_used_to_report_unsupported_ones(self):
        self.wire.request("vget /objects")
        self.wire.request("vget /cameras")
        self.assertEqual(self.wire.unsupported_seen(), ["vget /cameras"])

    def test_servers_without_a_command_list_are_fine(self):
        with FakeUnrealCV(advertise_commands=False) as old:
            wire = Wire("127.0.0.1", old.port, reconnect_attempts=0)
            wire.connect()
            self.addCleanup(wire.close)
            self.assertIsNone(wire.templates)
            self.assertEqual(wire.request("vget /objects"), "")
            self.assertEqual(wire.unsupported_seen(), [])


class MidRunFailureTest(AdapterCase):
    def test_read_during_a_step_recovers_and_the_step_finishes_exactly(self):
        self.server.drop_on = "vget /camera/1/location"
        result = self.sim.step({"type": "wait"})
        self.assertEqual(result.ticks_advanced, 60)
        self.assertEqual(self.sim.wire.reconnects, 1)
        self.assertTrue(self.server.paused)

    def test_reconnect_reapplies_sync_mode(self):
        self.server.drop_client()
        self.server.paused = False  # as if the link drop had let the game run
        self.assertEqual(self.sim.step({"type": "wait"}).ticks_advanced, 60)
        self.assertEqual(self.sim.wire.reconnects, 1)
        self.assertTrue(self.server.paused)

    def test_idle_link_drop_between_steps_costs_nothing(self):
        self.sim.step({"type": "wait"})
        self.server.drop_client()
        self.assertEqual(self.sim.step({"type": "wait"}).tick_end, 120)

    def test_lost_tick_stops_stepping_until_restore(self):
        checkpoint = self.sim.get_state()
        self.server.drop_on = "vset /action/tick"
        with self.assertRaises(ConnectionLostError):
            self.sim.step({"type": "wait"})
        with self.assertRaisesRegex(SimWorldError, "cannot step"):
            self.sim.step({"type": "wait"})
        with self.assertRaisesRegex(SimWorldError, "will not checkpoint"):
            self.sim.get_state()
        self.assertTrue(self.sim.restore_state(checkpoint).ok)
        self.assertEqual(self.sim.step({"type": "wait"}).tick_end, checkpoint.tick_count + 60)

    def test_server_restart_mid_run_is_detected_and_restore_recovers(self):
        self.sim.step({"type": "wait"})
        checkpoint = self.sim.get_state()
        self.server.drop_client()
        self.server.reset_world()
        with self.assertRaisesRegex(SimWorldError, "world is gone"):
            self.sim.step({"type": "wait"})
        report = self.sim.restore_state(checkpoint)
        self.assertTrue(report.ok, report)
        self.assertIn(AGENT_ACTOR, report.respawned)
        self.assertEqual(self.sim.step({"type": "wait"}).tick_end, checkpoint.tick_count + 60)


if __name__ == "__main__":
    unittest.main()
