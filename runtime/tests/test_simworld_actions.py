"""Each action maps to the right commands and behaves sensibly across steps."""
import unittest

try:
    import unrealcv  # noqa: F401
except ImportError:
    raise unittest.SkipTest("needs unrealcv; run with simworld/.venv")

import unittest

from runtime.adapters.simworld import AGENT_ACTOR, NpcSpec, SpawnSpec
from runtime.adapters import simworld_commands as c
from runtime.adapters.simworld_math import distance_2d_cm, heading_to
from runtime.physics import Vec3
from runtime.tests.test_simworld_adapter import AdapterCase

A = AGENT_ACTOR
NEAR_OBJECTS = [SpawnSpec(id="mug_0", kind="object", asset="/Game/Mug", position=(100, 0, 100)),
                SpawnSpec(id="far_mug", kind="object", asset="/Game/Mug", position=(5000, 0, 100)),
                SpawnSpec(id="bench_0", kind="seat", asset="/Game/Bench", position=(50, 50, 100)),
                SpawnSpec(id="scooter_0", kind="scooter", asset="/Game/Scooter", position=(0, 100, 100), actor="GEN_BP_Scooter_0"),
                SpawnSpec(id="car_0", kind="vehicle", asset="/Game/Car", position=(-100, 0, 100))]
STILL_NPCS = [NpcSpec(id="near", index=0, position=(500, 0, 110)), NpcSpec(id="far", index=1, position=(5000, 0, 110))]


class ActionCase(AdapterCase):
    config = dict(objects=NEAR_OBJECTS, npcs=STILL_NPCS)

    def run_action(self, **action):
        """Returns the outcome and the non-tick, non-read commands sent."""
        count = len(self.server.commands)
        result = self.sim.step(action)
        sent = [cmd for cmd in self.commands_since(count)
                if cmd != "vset /action/tick" and not cmd.startswith("vget ")
                and not any(w in cmd for w in ("SetSun", "GetSun", "GetFog", "GetAtmosphere", "GetCollisionNum"))]
        return result, sent

    def pos(self, actor=A):
        loc = self.server.actors[actor].location
        return Vec3(x=loc[0], y=loc[1], z=loc[2])


class NativeActionTest(ActionCase):
    def test_wait_sends_nothing_when_idle(self):
        result, sent = self.run_action(type="wait")
        self.assertEqual(sent, [])
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(result.outcome.mapping, "no_physics")

    def test_step_forward_maps_directions(self):
        _, sent = self.run_action(type="step_forward", duration_s=2.0)
        self.assertEqual(sent, [c.step_forward(A, 2.0, 0)])
        _, sent = self.run_action(type="step_forward", duration_s=2.0, direction="backward")
        self.assertEqual(sent, [c.step_forward(A, 2.0, 1)])

    def test_step_forward_moves_only_as_long_as_asked_in_sim_time(self):
        self.run_action(type="step_forward", duration_s=5.0)
        self.assertAlmostEqual(self.pos().x, 1000.0)  # 5s at 200 cm/s, not 30s

    def test_rotate(self):
        _, sent = self.run_action(type="rotate", angle_deg=90.0, direction="left")
        self.assertEqual(sent, [c.turn(A, 90.0, "left")])
        self.assertAlmostEqual(self.server.actors[A].rotation[1], -90.0)

    def test_stop(self):
        self.run_action(type="move_forward")
        _, sent = self.run_action(type="stop")
        self.assertEqual(sent, [c.stop_agent(A)])
        self.assertFalse(self.agent().walking)

    def test_set_speed_changes_speed_and_state(self):
        result, sent = self.run_action(type="set_speed", speed_cm_s=100.0)
        self.assertEqual(sent, [c.set_speed(A, 100.0)])
        self.assertEqual(result.final_state.agent.max_speed_cm_s, 100.0)

    def test_sit_then_stand(self):
        result, sent = self.run_action(type="sit_down")
        self.assertEqual(sent, [c.sit_down(A)])
        self.assertEqual(result.final_state.agent.posture, "sitting")
        result, sent = self.run_action(type="stand_up")
        self.assertEqual(sent, [c.stand_up(A)])
        self.assertEqual(result.final_state.agent.posture, "standing")

    def test_sitting_blocks_walking_with_a_clear_reason(self):
        self.run_action(type="sit_down")
        result, sent = self.run_action(type="move_to", position={"x": 1000, "y": 0, "z": 0})
        self.assertEqual(result.outcome.status, "failed")
        self.assertIn("stand_up", result.outcome.detail)
        self.assertEqual(sent, [])

    def test_stand_up_when_standing_fails(self):
        self.assertEqual(self.run_action(type="stand_up")[0].outcome.status, "failed")

    def test_pick_up_and_drop(self):
        result, sent = self.run_action(type="pick_up", target_id="mug_0")
        self.assertEqual(sent, [c.pick_up(A, "GEN_BP_mug_0")])
        self.assertEqual(result.final_state.agent.held_object, "mug_0")
        by_id = {o.id: o for o in result.final_state.objects}
        self.assertEqual(by_id["mug_0"].held_by, "agent")
        result, sent = self.run_action(type="drop_object")
        self.assertEqual(sent, [c.drop_object(A)])
        self.assertIsNone(result.final_state.agent.held_object)

    def test_pick_up_handles_server_refusal(self):
        self.sim.config.interact_radius_cm = 1000.0  # let the request through to the server's own reach check
        self.server.actors["GEN_BP_mug_0"].location = [900, 0, 100]
        result, _ = self.run_action(type="pick_up", target_id="mug_0")
        self.assertEqual(result.outcome.status, "failed")
        self.assertIn("Success=false", result.outcome.detail)
        self.assertIsNone(result.final_state.agent.held_object)

    def test_boolean_success_replies_are_understood(self):
        self.server.reply_as_bool = True
        result, _ = self.run_action(type="sit_down")
        self.assertEqual(result.outcome.status, "completed")

    def test_unreadable_reply_is_marked_unverified(self):
        self.server._bp_SitDown = lambda a: "ok"
        result, _ = self.run_action(type="sit_down")
        self.assertEqual(result.outcome.status, "unverified")

    def test_gesture_commands_and_replacement(self):
        for kind, expected in (("discuss", c.discuss(A, 1)), ("argue", c.argue(A, 1))):
            _, sent = self.run_action(type="gesture", kind=kind, variant=1)
            self.assertEqual(sent[-1], expected)
        for kind, expected in (("listen", c.listen(A)), ("wave", c.wave(A)), ("direct", c.direct(A))):
            _, sent = self.run_action(type="gesture", kind=kind)
            self.assertEqual(sent[-1], expected)
            self.assertEqual(sent[0], c.stop_gesture(A))  # the previous gesture is stopped first

    def test_stop_gesture(self):
        self.run_action(type="gesture", kind="wave")
        result, sent = self.run_action(type="stop_gesture")
        self.assertEqual(sent, [c.stop_gesture(A)])
        self.assertIsNone(result.final_state.agent.gesture)

    def test_vehicle(self):
        result, sent = self.run_action(type="enter_vehicle", target_id="car_0")
        self.assertEqual(sent, [c.enter_vehicle(A, "GEN_BP_car_0")])
        self.assertEqual(result.final_state.agent.posture, "in_vehicle")
        result, sent = self.run_action(type="drive", throttle=0.5)
        self.assertEqual(sent, [c.drive("GEN_BP_car_0", 0.5, 0.0, 0.0)])
        result, sent = self.run_action(type="exit_vehicle")
        self.assertEqual(sent, [c.exit_vehicle(A, "GEN_BP_car_0")])
        self.assertEqual(result.final_state.agent.posture, "standing")

    def test_scooter_on_and_off(self):
        result, sent = self.run_action(type="get_on_scooter", target_id="scooter_0")
        self.assertEqual(sent, [c.get_on_scooter(A), c.clean_garbage()])
        self.assertNotIn(A, self.server.actors)  # the humanoid is gone while riding
        self.assertEqual(result.final_state.agent.posture, "on_scooter")
        self.assertEqual(result.final_state.agent.actor, "GEN_BP_Scooter_0")

        result, sent = self.run_action(type="drive", throttle=1.0)
        self.assertEqual(sent, [c.drive("GEN_BP_Scooter_0", 1.0, 0.0, 0.0)])
        self.assertGreater(result.final_state.agent.pose.location.x, 1000)

        result, sent = self.run_action(type="get_off_scooter")
        self.assertEqual(sent[0], c.get_off_scooter("GEN_BP_Scooter_0"))
        self.assertIn(A, self.server.actors)  # renamed back, so later commands still reach it
        self.assertEqual(result.final_state.agent.posture, "standing")
        self.assertEqual(self.run_action(type="step_forward", duration_s=1.0)[0].outcome.status, "completed")

    def test_drive_on_foot_fails(self):
        self.assertEqual(self.run_action(type="drive", throttle=1.0)[0].outcome.status, "failed")


class MoveToTest(ActionCase):
    def test_near_goal_arrives_inside_the_step(self):
        result, sent = self.run_action(type="move_to", position={"x": 1000, "y": 0, "z": 100})
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(result.outcome.mapping, "composed")
        self.assertEqual(result.outcome.task.phase, "arrived")
        self.assertLessEqual(distance_2d_cm(self.pos(), Vec3(x=1000, y=0, z=0)), 150)
        self.assertFalse(self.agent().walking)
        self.assertIn(c.move_forward(A), sent)
        self.assertEqual(sent[-1], c.stop_agent(A))
        self.assertIsNone(result.final_state.agent.active_task)

    def test_turns_toward_a_goal_behind_it_and_the_shorter_way(self):
        _, sent = self.run_action(type="move_to", position={"x": 0, "y": -1000, "z": 100})
        self.assertEqual(sent[0], c.turn(A, 90.0, "left"))
        self.assertLessEqual(distance_2d_cm(self.pos(), Vec3(x=0, y=-1000, z=0)), 150)

    def test_far_goal_is_in_progress_at_the_end_of_the_step_then_continues(self):
        goal = {"x": 10000, "y": 0, "z": 100}  # 100 m is more than 60 m per step at 200 cm/s
        result, _ = self.run_action(type="move_to", position=goal)
        self.assertEqual(result.outcome.status, "in_progress")
        self.assertEqual(result.final_state.agent.active_task.type, "move_to")
        self.assertGreater(result.outcome.task.distance_remaining_cm, 3000)
        self.assertTrue(self.agent().walking)
        walked = self.pos().x
        self.assertAlmostEqual(walked, 5800, delta=300)

        result, _ = self.run_action(type="continue")
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(result.outcome.task.phase, "arrived")

    def test_a_new_action_cancels_the_walk(self):
        self.run_action(type="move_to", position={"x": 10000, "y": 0, "z": 100})
        result, sent = self.run_action(type="wait")
        self.assertEqual(sent, [c.stop_agent(A)])
        self.assertFalse(self.agent().walking)
        self.assertIsNone(result.final_state.agent.active_task)

    def test_speak_and_set_speed_do_not_cancel_the_walk(self):
        self.run_action(type="move_to", position={"x": 20000, "y": 0, "z": 100})
        for action in (dict(type="speak", text="hi"), dict(type="set_speed", speed_cm_s=150.0)):
            result, _ = self.run_action(**action)
            self.assertEqual(result.final_state.agent.active_task.type, "move_to")
            self.assertEqual(result.outcome.status, "completed")
            self.assertTrue(self.agent().walking)

    def test_blocked_agent_fails_rather_than_walking_forever(self):
        self.server.blocked.add(A)
        result, _ = self.run_action(type="move_to", position={"x": 1000, "y": 0, "z": 100})
        self.assertEqual(result.outcome.status, "failed")
        self.assertEqual(result.outcome.task.phase, "blocked")
        self.assertFalse(self.agent().walking)

    def test_chases_a_moving_target(self):
        npc = self.server.actors["GEN_BP_Pedestrian_0"]
        npc.location = [3000.0, 0.0, 110.0]
        result, _ = self.run_action(type="move_to", target_id="near", arrival_radius_cm=100.0)
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(result.outcome.task.target_id, "near")
        self.assertLessEqual(distance_2d_cm(self.pos(), self.pos("GEN_BP_Pedestrian_0")), 200)

    def test_already_there_completes_at_once(self):
        result, sent = self.run_action(type="move_to", position={"x": 10, "y": 0, "z": 100})
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(sent, [c.stop_agent(A)])

    def test_speed_change_affects_distance_covered(self):
        self.run_action(type="set_speed", speed_cm_s=100.0)
        self.run_action(type="move_forward")
        self.assertAlmostEqual(self.pos().x, 3000.0, delta=1)

    def test_continue_with_nothing_running_is_harmless(self):
        result, sent = self.run_action(type="continue")
        self.assertEqual(result.outcome.status, "completed")
        self.assertEqual(sent, [])


class LookAtTest(ActionCase):
    def expected_camera(self, target):
        camera = self.server._camera_pose(self.server.cameras[1])[0]
        return heading_to(Vec3(x=camera[0], y=camera[1], z=camera[2]), target)

    def test_turns_the_body_and_aims_the_camera_at_a_point(self):
        target = Vec3(x=0, y=1000, z=300)
        result, sent = self.run_action(type="look_at", position=target.model_dump())
        self.assertEqual(sent[0], c.turn(A, 90.0, "right"))
        self.assertEqual(result.outcome.mapping, "composed")
        rotation = result.final_state.camera.extrinsics.rotation_deg
        yaw, pitch = self.expected_camera(target)
        self.assertAlmostEqual(rotation.yaw, yaw, places=3)
        self.assertAlmostEqual(rotation.pitch, pitch, places=3)
        self.assertLess(abs(self.server.actors[A].rotation[1] - 90), 0.01)

    def test_target_id_is_tracked_as_it_moves(self):
        result, _ = self.run_action(type="look_at", target_id="near")
        npc = self.server.actors["GEN_BP_Pedestrian_0"]
        npc.location = [500.0, 500.0, 110.0]
        result, _ = self.run_action(type="continue")
        rotation = result.final_state.camera.extrinsics.rotation_deg
        self.assertAlmostEqual(rotation.yaw, 45.0, places=2)

    def test_no_body_turn_for_a_target_straight_ahead(self):
        _, sent = self.run_action(type="look_at", position={"x": 1000, "y": 0, "z": 260})
        self.assertFalse(any("TurnAround" in cmd for cmd in sent))

    def test_sitting_moves_only_the_camera(self):
        self.run_action(type="sit_down")
        _, sent = self.run_action(type="look_at", position={"x": 0, "y": 1000, "z": 0})
        self.assertFalse(any("TurnAround" in cmd for cmd in sent))
        self.assertTrue(any("/camera/1/rotation" in cmd for cmd in sent))

    def test_moving_on_returns_the_camera_to_the_body(self):
        self.run_action(type="look_at", position={"x": 0, "y": 1000, "z": 0})
        self.assertIsNotNone(self.sim.gaze)
        result, _ = self.run_action(type="wait")
        self.assertIsNone(self.sim.gaze)
        self.assertEqual(result.final_state.camera.extrinsics.rotation_deg.pitch, 0.0)

    def test_camera_stays_with_the_body_even_if_a_set_rotation_sticks(self):
        """The fake models the worst case: a camera rotation stays until set again."""
        self.run_action(type="look_at", position={"x": 0, "y": 1000, "z": 0})
        self.run_action(type="wait")
        result, _ = self.run_action(type="rotate", angle_deg=45.0, direction="right")
        self.assertAlmostEqual(result.final_state.camera.extrinsics.rotation_deg.yaw,
                               result.final_state.agent.pose.rotation.yaw, places=3)

    def test_a_camera_never_aimed_is_never_touched(self):
        self.run_action(type="rotate", angle_deg=45.0, direction="right")
        self.run_action(type="step_forward", duration_s=1.0)
        self.assertFalse(any("/camera/1/rotation " in cmd and cmd.startswith("vset") for cmd in self.server.commands))


class InteractTest(ActionCase):
    def test_object_means_pick_up(self):
        result, sent = self.run_action(type="interact", target_id="mug_0")
        self.assertEqual(sent, [c.pick_up(A, "GEN_BP_mug_0")])
        self.assertEqual(result.outcome.mapping, "composed")
        self.assertIn("pick_up", result.outcome.detail)
        self.assertEqual(result.final_state.agent.held_object, "mug_0")

    def test_seat_means_sit(self):
        result, sent = self.run_action(type="interact", target_id="bench_0")
        self.assertEqual(sent, [c.sit_down(A)])
        self.assertEqual(result.final_state.agent.posture, "sitting")

    def test_scooter_means_get_on(self):
        result, sent = self.run_action(type="interact", target_id="scooter_0")
        self.assertEqual(sent[0], c.get_on_scooter(A))
        self.assertEqual(result.final_state.agent.posture, "on_scooter")

    def test_vehicle_means_enter(self):
        result, sent = self.run_action(type="interact", target_id="car_0")
        self.assertEqual(sent, [c.enter_vehicle(A, "GEN_BP_car_0")])
        self.assertEqual(result.final_state.agent.posture, "in_vehicle")

    def test_too_far_fails_and_sends_nothing(self):
        result, sent = self.run_action(type="interact", target_id="far_mug")
        self.assertEqual(result.outcome.status, "failed")
        self.assertIn("move_to", result.outcome.detail)
        self.assertEqual(sent, [])

    def test_cannot_hold_two_things(self):
        self.server.handle("vset /object/GEN_BP_far_mug/location 150 0 100")
        self.run_action(type="interact", target_id="mug_0")
        result, _ = self.run_action(type="interact", target_id="far_mug")
        self.assertEqual(result.outcome.status, "failed")
        self.assertIn("already holding", result.outcome.detail)


class SpeakTest(ActionCase):
    def test_speech_lists_npcs_in_range_and_sends_no_commands_that_change_anything(self):
        result, sent = self.run_action(type="speak", text="hello there")
        self.assertEqual(sent, [])  # no physics, no animation
        self.assertEqual(result.outcome.mapping, "no_physics")
        event = result.speech_events[0]
        self.assertEqual(event.heard_by, ["near"])  # 5 m away, the other is 50 m
        self.assertEqual(event.text, "hello there")
        self.assertEqual(event.hearing_radius_cm, 1000.0)
        self.assertIs(event.physics_effect, False)
        self.assertIs(event.npc_reaction, False)

    def test_hearing_radius_is_configurable(self):
        sim = self.replace_sim(hearing_radius_cm=6000.0, run_id="wide")
        sim.reset()
        self.assertEqual(sim.step({"type": "speak", "text": "hi"}).speech_events[0].heard_by, ["far", "near"])

    def test_npcs_do_not_react(self):
        before = list(self.server.actors["GEN_BP_Pedestrian_0"].location)
        self.run_action(type="speak", text="hey")
        self.assertEqual(self.server.actors["GEN_BP_Pedestrian_0"].location, before)
        self.assertIsNone(self.server.actors["GEN_BP_Pedestrian_0"].gesture)


class NpcRouteTest(AdapterCase):
    config = dict(npcs=[NpcSpec(id="walker", index=0, position=(0, 1000, 110), speed_cm_s=100.0,
                                waypoints=[(1000, 1000), (0, 1000)])], objects=[])

    def test_npc_walks_its_waypoints_in_a_loop(self):
        seen = []
        for _ in range(3):
            state = self.sim.step({"type": "wait"}).final_state
            seen.append(state.npcs[0].pose.location.x)
        self.assertGreater(max(seen), 300)
        self.assertIn(self.sim.npc_waypoint["walker"], (0, 1))
        commands = " ".join(self.server.commands)
        self.assertIn("vbp GEN_BP_Pedestrian_0 MoveForward", commands)
        self.assertIn("vbp GEN_BP_Pedestrian_0 SetMaxSpeed 100.0", commands)

    def test_npc_velocity_is_reported(self):
        state = self.sim.step({"type": "wait"}).captures[0].state
        self.assertAlmostEqual(state.npcs[0].velocity.speed_cm_s, 100.0, delta=1)


if __name__ == "__main__":
    unittest.main()
