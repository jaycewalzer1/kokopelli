"""TwoBodySim (kokopelli/agents/lunch_wm.py): the SimWorld adapter plus a second humanoid with its own head camera."""
import math
from pathlib import Path
from typing import Any, cast

from kokopelli.agents import live
from kokopelli.loop.adapters import simworld_commands as c
from kokopelli.loop.adapters.simworld import AGENT_ASSET, SimWorldPhysics
from kokopelli.loop.adapters.simworld_control import MoverIO
from kokopelli.loop.adapters.simworld_math import angle_delta, distance_cm, heading_to
from kokopelli.loop.physics import Vec3

ROOT = live.ROOT

FRIEND_ACTOR = "GEN_BP_Humanoid_1"


# ================================================================ the sim: two humanoids, two head cameras

class TwoBodySim(SimWorldPhysics):
    """The adapter, plus a second humanoid ("the friend") with its own head camera, driven like the agent.

    Set `friend_action` before step(); it takes the same dicts as the agent's actions, restricted to
    continue / wait / move_to (position or target_id) / look_at (target_id or position) / interact / drop_object.
    After a step, `friend_captures` holds one {modality: RenderFile} per capture tick and `friend_result` its outcome.
    Not supported for the friend: checkpoint/restore, sitting, scooters, vehicles, gestures."""

    def __init__(self, config, friend_id="friend", friend_position=(0.0, 0.0, 200.0), friend_yaw=0.0):
        self.friend_id, self.friend_yaw = friend_id, friend_yaw
        self.friend_position = cast(tuple[float, float, float], tuple(friend_position))
        self.friend_camera_id: int | None = None
        self.friend_action: dict[str, Any] | None = None
        self.friend_task = self.friend_last = None
        self.friend_held = None
        self.friend_captures, self.friend_result = [], {}
        self._prefix = ""
        super().__init__(config)

    # --- world building
    def _index_targets(self):
        super()._index_targets()
        self.targets[self.friend_id] = "npc"   # the agent can approach / look at the friend like any person

    def _tracked(self):
        return {**super()._tracked(), self.friend_id: FRIEND_ACTOR}   # gets a mask colour, checked after spawning

    def _destroy_ours(self):
        """An earlier run's friend goes first: cameras renumber when their owner is destroyed (SPEC 3.1)."""
        if FRIEND_ACTOR.lower() in {n.lower() for n in self._objects()}:
            self.wire.request(c.destroy(FRIEND_ACTOR), resend=False)
            self.wire.request(c.clean_garbage(), resend=False)
        super()._destroy_ours()

    def _spawn_agent(self):
        super()._spawn_agent()   # agent first, so it keeps the lower camera id
        self._spawn(AGENT_ASSET, FRIEND_ACTOR, *self.friend_position, self.friend_yaw)
        self.wire.request(c.set_speed(FRIEND_ACTOR, self.config.agent_speed_cm_s), resend=False)

    def _setup_camera(self):
        super()._setup_camera()
        self.friend_camera_id = self._nearest_camera(FRIEND_ACTOR, exclude={self.camera_id})
        w, h = self.config.resolution
        self.wire.request(c.set_camera_size(self.friend_camera_id, w, h), resend=False)
        if self.config.fov_deg is not None:
            self.wire.request(c.set_camera_fov(self.friend_camera_id, self.config.fov_deg), resend=False)

    def _nearest_camera(self, actor, exclude=()):
        here = self._read_location(actor)
        names = str(self.wire.request(c.list_cameras())).split()
        best, best_d = None, math.inf
        for cam in range(1, len(names)):
            if cam in exclude:
                continue
            try:
                d = distance_cm(here, self._read_camera_location(cam))
            except Exception:
                continue
            if d < best_d:
                best, best_d = cam, d
        if best is None:
            raise RuntimeError(f"no camera found for {actor} (server lists {names})")
        if best_d > 500:
            self.warnings.append(f"nearest camera {best} is {best_d:.0f} cm from {actor}, may not be its head camera")
        self.friend_camera_distance_cm = round(best_d, 1)
        return best

    # --- rendering: both cameras, unique file per capture tick
    def render(self, modality, offset_s):
        """The adapter names files by whole seconds (t0000_rgb.png), so at video rate every frame of a second would
        overwrite the last. Rename each render as soon as it lands."""
        r = super().render(modality, offset_s)
        p = Path(r.path)
        new = p.with_name(f"{self._prefix}t{offset_s:09.4f}_{modality}.{r.format}")
        p.replace(new)
        return r.model_copy(update={"path": str(new)})

    def _capture(self, offset_s, timing):
        cap = super()._capture(offset_s, timing)
        own, self.camera_id, self._prefix = self.camera_id, self.friend_camera_id, "friend_"
        try:
            self.friend_captures.append({m: self.render(m, offset_s) for m in self.config.modalities})
        finally:
            self.camera_id, self._prefix = own, ""
        return cap

    def reset(self, seed=None):
        self.friend_captures, self.friend_task, self.friend_last, self.friend_held = [], None, None, None
        return super().reset(seed)

    def _step(self, action):
        self.friend_captures = []
        return super()._step(action)

    # --- the friend's actions
    def _friend_io(self):
        return MoverIO(forward=lambda: self.wire.request(c.move_forward(FRIEND_ACTOR), resend=False),
                       stop=lambda: self.wire.request(c.stop_agent(FRIEND_ACTOR), resend=False),
                       turn=lambda a, d: self.wire.request(c.turn(FRIEND_ACTOR, round(a, 3), d), resend=False))

    def _apply(self, action):
        outcome = super()._apply(action)
        act, self.friend_action = self.friend_action or {"type": "continue"}, None
        self.friend_last = None
        self._friend_status = self._apply_friend(act)
        self._friend_type = act["type"]
        return outcome

    def _apply_friend(self, a):
        kind = a["type"]
        if kind == "continue":
            return ("in_progress", "") if self.friend_task else ("completed", "nothing was running")
        if self.friend_task:
            self.wire.request(c.stop_agent(FRIEND_ACTOR), resend=False)
            self.friend_task = None
        if kind == "wait":
            return "completed", ""
        if kind == "move_to":
            target = a.get("target_id")
            goal = self._read_location(self._actor_for(target)) if target else Vec3(**{"z": 0.0, **a["position"]})
            self.friend_task = self._new_mover(goal.x, goal.y, goal.z, a.get("arrival_radius_cm", self.config.arrival_radius_cm), target)
            self.friend_task.update(self._read_pose(FRIEND_ACTOR), self.tick_count, self._friend_io())
            if self.friend_task.finished:
                self.friend_last, self.friend_task = self.friend_task, None
            return "in_progress", ""
        if kind == "look_at":
            pose = self._read_pose(FRIEND_ACTOR)
            point = (self._read_location(self._actor_for(a["target_id"])) if a.get("target_id")
                     else Vec3(**{"z": 0.0, **a["position"]}))
            yaw, _ = heading_to(pose.location, point)
            delta = angle_delta(yaw, pose.rotation.yaw)
            if abs(delta) > 2:
                self.wire.request(c.turn(FRIEND_ACTOR, round(abs(delta), 3), "right" if delta > 0 else "left"), resend=False)
            return "completed", f"turned {delta:.1f} degrees"
        if kind == "interact":
            target = a["target_id"]
            d = distance_cm(self._read_location(FRIEND_ACTOR), self._read_location(self._actor_for(target)))
            if d > self.config.interact_radius_cm:
                return "failed", f"{target} is {d:.0f}cm away"
            if self.friend_held:
                return "failed", f"already holding {self.friend_held}"
            return self._send_checked(c.pick_up(FRIEND_ACTOR, self._actor_for(target)),
                                      lambda: setattr(self, "friend_held", target))
        if kind == "drop_object":
            if not self.friend_held:
                return "failed", "not holding anything"
            return self._send_checked(c.drop_object(FRIEND_ACTOR), lambda: setattr(self, "friend_held", None))
        return "failed", f"the friend can't {kind}"

    def _control(self):
        super()._control()
        t = self.friend_task
        if t:
            if t.target_id:
                goal = self._read_location(self._actor_for(t.target_id))
                t.goal_x, t.goal_y, t.goal_z = goal.x, goal.y, goal.z
            t.update(self._read_pose(FRIEND_ACTOR), self.tick_count, self._friend_io())
            if t.finished:
                self.friend_last, self.friend_task = t, None

    def _finish_outcome(self, outcome):
        outcome = super()._finish_outcome(outcome)
        status, detail = self._friend_status
        mover = self.friend_last or self.friend_task
        phase = mover.phase if mover else None
        if self._friend_type in ("move_to", "continue") and mover:
            status = {"arrived": "completed", "blocked": "failed"}.get(cast(str, phase), "in_progress")  # mover is set here, so phase is too
            detail = f"move_to {phase}, {mover.last_distance_cm or 0:.0f}cm from the goal"
        self.friend_result = {"status": status, "detail": detail, "phase": phase}
        return outcome

    def friend_pose(self):
        return self._read_pose(FRIEND_ACTOR)
