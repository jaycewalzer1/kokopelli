"""Actions for SimWorldPhysics, as a mixin: the _do_* handlers and the movers that carry them out.

Split out of simworld.py. SimWorldPhysics lists this mixin before PhysicsSim, and subclasses such as
kokopelli/agents/lunch_wm.py:TwoBodySim still override these methods by name.
"""
import json
from typing import TYPE_CHECKING, Any

from kokopelli.loop.adapters import simworld_commands as c
from kokopelli.loop.adapters.simworld_config import AGENT_ACTOR, NEW_HUMANOID_PREFIX, NpcSpec
from kokopelli.loop.adapters.simworld_control import Mover, MoverIO
from kokopelli.loop.adapters.simworld_math import angle_delta, distance_cm, hearing, heading_to
from kokopelli.loop.physics import ACTION_CATALOG, INTERACT_BY_KIND, ActionOutcome, SpeechEvent, TaskStatus

if TYPE_CHECKING:
    from kokopelli.loop.adapters.simworld_config import SimWorldConfig, SpawnSpec
    from kokopelli.loop.adapters.simworld_wire import Wire
    from kokopelli.loop.physics import Pose, Vec3

# Actions that do not interrupt whatever the agent is already doing.
NON_PREEMPTING = {"continue", "speak", "set_speed"}


class ActionsMixin:
    """Needs the wire, state fields and readers (_read_location, _read_pose, _actor_for, _objects,
    _find_agent_camera, _gaze_point, _task_status) from SimWorldPhysics."""

    if TYPE_CHECKING:   # what SimWorldPhysics provides, declared for the type checker only
        wire: Wire
        config: SimWorldConfig
        held: str | None
        vehicle: str | None
        npc_movers: dict[str, Mover]
        npc_specs: list[NpcSpec]
        npc_waypoint: dict[str, int]
        specs: dict[str, SpawnSpec]
        targets: dict[str, str]
        tick_count: int
        _speech: list[SpeechEvent]

        @property
        def sim_time_s(self) -> float: ...
        @property
        def _agent_actor(self) -> str: ...
        def _read_location(self, actor: str) -> Vec3: ...
        def _read_pose(self, actor: str) -> Pose: ...
        def _actor_for(self, target_id: str) -> str: ...
        def _objects(self) -> list[str]: ...
        def _find_agent_camera(self) -> int: ...
        def _gaze_point(self) -> Vec3: ...
        def _task_status(self) -> TaskStatus | None: ...

    ###################################################
    # Actions
    ###################################################

    def _finish_outcome(self, outcome: ActionOutcome) -> ActionOutcome:
        """Long-running actions only know how they went once the step is over."""
        update: dict[str, Any] = {"task": self._task_status()}
        last = self._last_task_result
        if last:
            update["task"] = TaskStatus(type="move_to", phase=last.phase, goal=last.goal, target_id=last.target_id,
                                        distance_remaining_cm=last.last_distance_cm)
        if outcome.type in ("move_to", "continue", "move_forward"):
            if last:
                update["status"] = "completed" if last.phase == "arrived" else "failed"
                update["detail"] = f"move_to {last.phase}, {last.last_distance_cm:.0f}cm from the goal"
            elif update["task"]:
                update["status"] = "in_progress"
        return outcome.model_copy(update=update)

    def _control(self) -> None:
        """Run the waypoint controllers. They act on tick counts, so wall-clock speed cannot change them."""
        if self.task:
            if self.task.target_id:
                goal = self._read_location(self._actor_for(self.task.target_id))
                self.task.goal_x, self.task.goal_y, self.task.goal_z = goal.x, goal.y, goal.z
            self.task.update(self._read_pose(self._agent_actor), self.tick_count, self._agent_io())
            if self.task.finished:
                self._last_task_result, self.task = self.task, None
        for npc in self.npc_specs:
            mover = self.npc_movers.get(npc.id)
            if mover is None:
                continue
            mover.update(self._read_pose(npc.actor_name), self.tick_count, self._npc_io(npc))
            if mover.finished:  # arrived or blocked, either way head for the next waypoint
                self._next_waypoint(npc)

    def _agent_io(self) -> MoverIO:
        return MoverIO(forward=lambda: self.wire.request(c.move_forward(AGENT_ACTOR), resend=False),
                       stop=lambda: self.wire.request(c.stop_agent(AGENT_ACTOR), resend=False),
                       turn=lambda a, d: self.wire.request(c.turn(AGENT_ACTOR, round(a, 3), d), resend=False))

    def _npc_io(self, npc: NpcSpec) -> MoverIO:
        return MoverIO(forward=lambda: self.wire.request(c.npc_forward(npc.actor_name), resend=False),
                       stop=lambda: self.wire.request(c.npc_stop(npc.actor_name), resend=False),
                       turn=lambda a, d: self.wire.request(c.npc_turn(npc.actor_name, round(a, 3), d), resend=False))

    def _new_mover(self, x: float, y: float, z: float, radius: float, target_id: str | None = None) -> Mover:
        cfg = self.config
        return Mover(goal_x=x, goal_y=y, goal_z=z, arrival_radius_cm=radius, target_id=target_id,
                     turn_ticks=max(1, round(1.0 / cfg.tick_interval_s)),  # TurnAround runs for 1s (unrealcv.py:632)
                     stuck_ticks=max(1, round(cfg.stuck_window_s / cfg.tick_interval_s)))

    def _start_npc_routes(self) -> None:
        for npc in self.npc_specs:
            if npc.waypoints:
                self.npc_waypoint[npc.id] = -1
                self._next_waypoint(npc)

    def _next_waypoint(self, npc: NpcSpec) -> None:
        index = (self.npc_waypoint[npc.id] + 1) % len(npc.waypoints)
        self.npc_waypoint[npc.id] = index
        x, y = npc.waypoints[index]
        self.npc_movers[npc.id] = self._new_mover(x, y, 0.0, self.config.arrival_radius_cm)

    def _apply(self, action: Any) -> ActionOutcome:
        self._last_task_result = None
        kind = action.type
        if kind not in NON_PREEMPTING:
            self._preempt(kind)
        status, detail = getattr(self, f"_do_{kind}")(action)
        return ActionOutcome(type=kind, mapping=ACTION_CATALOG[kind].mapping, status=status, detail=detail)

    def _preempt(self, kind: str) -> None:
        """A new action replaces whatever was running."""
        if (self.task or self.walking) and kind != "stop":
            self.wire.request(c.stop_agent(AGENT_ACTOR), resend=False)
        self.task = None
        self.walking = False
        if self.gesture and kind != "stop_gesture":
            self.wire.request(c.stop_gesture(AGENT_ACTOR), resend=False)
            self.gesture = None
        if self.gaze and kind != "look_at":
            self.gaze = None

    def _on_foot(self) -> str | None:
        """Why locomotion is impossible right now, or None if it is fine."""
        if self.posture != "standing":
            return f"agent is {self.posture}. Use stand_up, get_off_scooter or exit_vehicle first."
        return None

    def _out_of_range(self, target_id: str) -> str | None:
        here = self._read_location(self._agent_actor)
        there = self._read_location(self._actor_for(target_id))
        d = distance_cm(here, there)
        if d > self.config.interact_radius_cm:
            return f"{target_id} is {d:.0f}cm away, limit is {self.config.interact_radius_cm:.0f}cm. move_to it first."
        return None

    @staticmethod
    def _success(reply: Any) -> bool | None:
        """Parse {"Success": ...}. unrealcv.py:680 only handles the string form, we allow booleans too."""
        try:
            value = json.loads(str(reply))["Success"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
        text = str(value).strip().lower()
        return True if text == "true" else False if text == "false" else None

    def _send_checked(self, command: str, on_success=None) -> tuple[str, str]:
        result = self._success(self.wire.request(command, resend=False))
        if result is False:
            return "failed", "the server reported Success=false"
        if on_success:
            on_success()
        if result is None:
            return "unverified", "sent, but the reply had no readable Success field"
        return "completed", ""

    def _do_wait(self, action) -> tuple[str, str]:
        return "completed", ""

    def _do_continue(self, action) -> tuple[str, str]:
        if not self.task and not self.walking:
            return "completed", "nothing was running"
        return "in_progress", ""

    def _do_move_to(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        goal = action.position or self._read_location(self._actor_for(action.target_id))
        self.task = self._new_mover(goal.x, goal.y, goal.z, action.arrival_radius_cm, action.target_id)
        self.task.update(self._read_pose(self._agent_actor), self.tick_count, self._agent_io())
        if self.task.finished:
            self._last_task_result, self.task = self.task, None
        return "in_progress", ""

    def _do_look_at(self, action) -> tuple[str, str]:
        self.gaze = {"target_id": action.target_id,
                     "position": action.position.model_dump() if action.position else None}
        detail = ""
        if self.posture == "standing":  # sitting or riding, only the camera can move
            pose = self._read_pose(self._agent_actor)
            yaw, _ = heading_to(pose.location, self._gaze_point())
            delta = angle_delta(yaw, pose.rotation.yaw)
            if abs(delta) > 2:  # local_planner.py:260 ignores turns under 2 degrees
                self.wire.request(c.turn(AGENT_ACTOR, round(abs(delta), 3), "right" if delta > 0 else "left"), resend=False)
                detail = f"turned {delta:.1f} degrees"
        return "completed", detail

    def _do_interact(self, action) -> tuple[str, str]:
        kind = self.targets[action.target_id]
        verb = INTERACT_BY_KIND[kind]
        problem = self._out_of_range(action.target_id)
        if problem:
            return "failed", problem
        if verb == "pick_up":
            status, detail = self._pick_up(action.target_id)
        elif verb == "sit_down":
            status, detail = self._do_sit_down(action)
        elif verb == "get_on_scooter":
            status, detail = self._get_on_scooter(action.target_id)
        else:
            status, detail = self._enter_vehicle(action.target_id)
        return status, f"{verb}: {detail}".rstrip(": ")

    def _do_speak(self, action) -> tuple[str, str]:
        """No physics: this only works out who is close enough to count as hearing."""
        here = self._read_location(self._agent_actor)
        listeners = {npc.id: self._read_location(npc.actor_name) for npc in self.npc_specs}
        heard = hearing(here, listeners, self.config.hearing_radius_cm)
        self._speech.append(SpeechEvent(speaker_id="agent", text=action.text, tick_count=self.tick_count,
                                        sim_time_s=self.sim_time_s, hearing_radius_cm=self.config.hearing_radius_cm,
                                        heard_by=heard))
        return "completed", f"in hearing range: {heard}. NPCs do not react."

    def _do_move_forward(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        self.wire.request(c.move_forward(AGENT_ACTOR), resend=False)
        self.walking = True
        return "in_progress", ""

    def _do_step_forward(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        if action.duration_s > self.config.step_seconds:
            return "failed", f"duration is longer than one step ({self.config.step_seconds}s)"
        direction = 0 if action.direction == "forward" else 1  # action_space.py:120
        self.wire.request(c.step_forward(AGENT_ACTOR, action.duration_s, direction), resend=False)
        return "completed", ""

    def _do_rotate(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        self.wire.request(c.turn(AGENT_ACTOR, action.angle_deg, action.direction), resend=False)
        return "completed", ""

    def _do_stop(self, action) -> tuple[str, str]:
        self.wire.request(c.stop_agent(AGENT_ACTOR), resend=False)
        return "completed", ""

    def _do_set_speed(self, action) -> tuple[str, str]:
        self.wire.request(c.set_speed(AGENT_ACTOR, action.speed_cm_s), resend=False)
        self.agent_speed = action.speed_cm_s
        return "completed", ""

    def _do_sit_down(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        return self._send_checked(c.sit_down(AGENT_ACTOR), lambda: setattr(self, "posture", "sitting"))

    def _do_stand_up(self, action) -> tuple[str, str]:
        if self.posture != "sitting":
            return "failed", f"agent is {self.posture}, not sitting"
        return self._send_checked(c.stand_up(AGENT_ACTOR), lambda: setattr(self, "posture", "standing"))

    def _do_pick_up(self, action) -> tuple[str, str]:
        problem = self._out_of_range(action.target_id)
        if problem:
            return "failed", problem
        return self._pick_up(action.target_id)

    def _pick_up(self, target_id: str) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        if self.held:
            return "failed", f"already holding {self.held}"
        return self._send_checked(c.pick_up(AGENT_ACTOR, self._actor_for(target_id)),
                                  lambda: setattr(self, "held", target_id))

    def _do_drop_object(self, action) -> tuple[str, str]:
        if not self.held:
            return "failed", "not holding anything"
        return self._send_checked(c.drop_object(AGENT_ACTOR), lambda: setattr(self, "held", None))

    def _do_get_on_scooter(self, action) -> tuple[str, str]:
        problem = self._out_of_range(action.target_id)
        if problem:
            return "failed", problem
        return self._get_on_scooter(action.target_id)

    def _get_on_scooter(self, target_id: str) -> tuple[str, str]:
        """GetOnScooter names no scooter, so the blueprint presumably uses the nearest. Unverified."""
        problem = self._on_foot()
        if problem:
            return "failed", problem
        self.wire.request(c.get_on_scooter(AGENT_ACTOR), resend=False)
        self.wire.request(c.clean_garbage(), resend=False)  # unrealcv.py:710
        self.riding, self.posture = target_id, "on_scooter"
        self._recheck_camera()
        return "completed", ""

    def _do_get_off_scooter(self, action) -> tuple[str, str]:
        """The humanoid comes back as a new actor, so give it the old name (communicator.py:110-125)."""
        if not self.riding:
            return "failed", "not on a scooter"
        self.wire.request(c.get_off_scooter(self.specs[self.riding].actor_name), resend=False)
        objects = self._objects()
        if AGENT_ACTOR not in objects:
            fresh = [o for o in objects if NEW_HUMANOID_PREFIX in o]
            if not fresh:
                return "failed", f"no new humanoid ({NEW_HUMANOID_PREFIX}*) appeared after getting off"
            self.wire.request(c.rename(fresh[0], AGENT_ACTOR), resend=False)
        self.riding, self.posture = None, "standing"
        self.wire.request(c.set_speed(AGENT_ACTOR, self.agent_speed), resend=False)
        self._recheck_camera()
        return "completed", ""

    def _recheck_camera(self) -> None:
        """The humanoid is swapped out on and off a scooter, and its camera may not survive."""
        if self.config.camera_id is None:
            self.camera_id = self._find_agent_camera()

    def _do_enter_vehicle(self, action) -> tuple[str, str]:
        problem = self._out_of_range(action.target_id)
        if problem:
            return "failed", problem
        return self._enter_vehicle(action.target_id)

    def _enter_vehicle(self, target_id: str) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem

        def entered():
            self.vehicle, self.posture = target_id, "in_vehicle"
        return self._send_checked(c.enter_vehicle(AGENT_ACTOR, self._actor_for(target_id)), entered)

    def _do_exit_vehicle(self, action) -> tuple[str, str]:
        if not self.vehicle:
            return "failed", "not in a vehicle"

        def exited():
            self.vehicle, self.posture = None, "standing"
        return self._send_checked(c.exit_vehicle(AGENT_ACTOR, self._actor_for(self.vehicle)), exited)

    def _do_drive(self, action) -> tuple[str, str]:
        carrier = self.riding or self.vehicle
        if not carrier:
            return "failed", "not on a scooter or in a vehicle"
        self.wire.request(c.drive(self._actor_for(carrier), action.throttle, action.brake, action.steering), resend=False)
        return "completed", ""

    def _do_gesture(self, action) -> tuple[str, str]:
        problem = self._on_foot()
        if problem:
            return "failed", problem
        command = {"discuss": lambda: c.discuss(AGENT_ACTOR, action.variant), "argue": lambda: c.argue(AGENT_ACTOR, action.variant),
                   "listen": lambda: c.listen(AGENT_ACTOR), "wave": lambda: c.wave(AGENT_ACTOR),
                   "direct": lambda: c.direct(AGENT_ACTOR)}[action.kind]()
        self.wire.request(command, resend=False)
        self.gesture, self.gesture_variant = action.kind, action.variant
        return "completed", ""

    def _do_stop_gesture(self, action) -> tuple[str, str]:
        self.wire.request(c.stop_gesture(AGENT_ACTOR), resend=False)
        self.gesture = None
        return "completed", ""
