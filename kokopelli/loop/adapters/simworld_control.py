"""Waypoint controller: walks an actor to a point using only turn, walk and stop.

This does the job of local_planner.py:navigate_rule_based, whose logic it mirrors (stop, turn
until within 5 degrees, walk, stop inside the radius). We cannot call that function because it
blocks until arrival (local_planner.py:146) and only sleeps inside the loop. Nothing would ever
tick a paused game, so it would wait forever. Here the stepping loop calls update() instead.
"""
from dataclasses import asdict, dataclass
from collections.abc import Callable

from kokopelli.loop.adapters.simworld_math import angle_delta, distance_2d_cm, heading_to
from kokopelli.loop.physics import Pose, Vec3

ALIGN_DEGREES = 5.0  # local_planner.py:270


@dataclass
class MoverIO:
    """How a mover drives its actor. Agents and NPCs use different blueprint functions."""
    forward: Callable[[], object]   # return value ignored
    stop: Callable[[], object]
    turn: Callable[[float, str], object]


@dataclass
class Mover:
    """State machine: start -> turning -> walking -> arrived, or blocked."""
    goal_x: float
    goal_y: float
    goal_z: float = 0.0
    arrival_radius_cm: float = 150.0
    turn_ticks: int = 10
    stuck_ticks: int = 80
    stuck_min_cm: float = 20.0
    phase: str = "start"
    turn_end_tick: int = 0
    progress_tick: int | None = None
    progress_x: float = 0.0
    progress_y: float = 0.0
    last_distance_cm: float | None = None
    target_id: str | None = None  # set when chasing something that can move

    @property
    def finished(self) -> bool:
        return self.phase in ("arrived", "blocked")

    @property
    def goal(self) -> Vec3:
        return Vec3(x=self.goal_x, y=self.goal_y, z=self.goal_z)

    def update(self, pose: Pose, tick: int, io: MoverIO) -> None:
        """Called every control interval. Sends at most a stop plus one other command."""
        if self.finished:
            return
        here = pose.location
        walking = self.phase == "walking"
        self.last_distance_cm = distance_2d_cm(here, self.goal)
        if self.last_distance_cm <= self.arrival_radius_cm:
            io.stop()
            self.phase = "arrived"
            return

        moved = self.progress_tick is not None and \
            distance_2d_cm(here, Vec3(x=self.progress_x, y=self.progress_y, z=0)) >= self.stuck_min_cm
        if self.progress_tick is None or moved:
            self.progress_tick, self.progress_x, self.progress_y = tick, here.x, here.y
        elif tick - self.progress_tick >= self.stuck_ticks:
            io.stop()
            self.phase = "blocked"
            return

        if self.phase == "turning" and tick < self.turn_end_tick:
            return  # a turn is still playing out in sim time

        yaw, _ = heading_to(here, self.goal)
        delta = angle_delta(yaw, pose.rotation.yaw)
        if abs(delta) > ALIGN_DEGREES:
            if walking:
                io.stop()
            io.turn(abs(delta), "right" if delta > 0 else "left")
            self.phase, self.turn_end_tick = "turning", tick + self.turn_ticks
        elif not walking:
            io.forward()
            self.phase = "walking"

    def restart(self) -> None:
        """After a restore the actor is at rest, so walking must be commanded again."""
        if not self.finished:
            self.phase, self.progress_tick = "start", None

    def to_dict(self) -> dict:
        return asdict(self)
