"""What the loop knows about physics: state, captures, actions and the PhysicsSim interface.

Only needs pydantic, so the loop can import it without Unreal or UnrealCV installed.
Units are Unreal's: centimetres and degrees. See kokopelli/loop/SIMWORLD.md for the terms.
"""
from __future__ import annotations

import abc
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from collections.abc import Mapping

from pydantic import (BaseModel, ConfigDict, Field, TypeAdapter, ValidationInfo,
                      field_validator, model_validator)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


###################################################
# Physical state
###################################################

class Vec3(_Model):
    x: float
    y: float
    z: float


class Rotation(_Model):
    """Degrees. Yaw turns clockwise seen from above, as in Unreal."""
    pitch: float
    yaw: float
    roll: float


class Pose(_Model):
    location: Vec3
    rotation: Rotation


class Velocity(_Model):
    """SimWorld has no velocity query, so this is always a finite difference of two poses."""
    vector_cm_s: Vec3
    speed_cm_s: float
    source: Literal["finite_difference"] = "finite_difference"
    window_s: float = Field(description="Time between the two poses. 0 means no earlier pose existed.")


class TaskStatus(_Model):
    """An action still running across steps, such as a long move_to."""
    type: str
    phase: str
    goal: Vec3 | None = None
    target_id: str | None = None
    distance_remaining_cm: float | None = None


class AgentState(_Model):
    id: str
    actor: str
    pose: Pose
    velocity: Velocity
    posture: Literal["standing", "sitting", "on_scooter", "in_vehicle"]
    held_object: str | None = None
    max_speed_cm_s: float
    gesture: str | None = None
    active_task: TaskStatus | None = None
    collisions: dict[str, int] | None = Field(
        default=None, description="Running counts since spawn. None if the server would not report them.")


class NpcState(_Model):
    id: str
    actor: str
    pose: Pose
    velocity: Velocity


class ObjectState(_Model):
    id: str
    actor: str
    kind: str
    present: bool
    pose: Pose | None = None
    held_by: str | None = None


class TimeOfDay(_Model):
    """Computed from the tick count and the sun formula, never read from the server."""
    seconds_since_midnight: float
    clock: str
    sun_elevation_deg: float
    sun_azimuth_deg: float
    sun_intensity: float


class Weather(_Model):
    """Values read back from the weather manager. available=False means it could not be reached."""
    available: bool
    sun_pitch_deg: float | None = None
    sun_yaw_deg: float | None = None
    sun_intensity: float | None = None
    fog_density: float | None = None
    fog_distance_cm: float | None = None
    fog_falloff: float | None = None
    rayleigh: float | None = None
    mie: float | None = None


class Intrinsics(_Model):
    """Pinhole camera: how 3D directions become pixels. See intrinsics_from_fov."""
    width: int
    height: int
    fov_horizontal_deg: float
    fx: float
    fy: float
    cx: float
    cy: float


class Extrinsics(_Model):
    """Where the camera is. Axes are Unreal's: x forward, y right, z up (left-handed)."""
    location_cm: Vec3
    rotation_deg: Rotation
    camera_to_world: list[list[float]] = Field(description="3x3. Columns are the camera's x, y, z axes in world space.")


class CameraState(_Model):
    camera_id: int
    intrinsics: Intrinsics
    extrinsics: Extrinsics


class PhysicalState(_Model):
    """Everything true about the world at one moment. JSON-serializable."""
    tick_count: int = Field(description="Engine ticks since reset. Sim time comes from this, never the wall clock.")
    sim_time_s: float
    agent: AgentState
    npcs: list[NpcState]
    objects: list[ObjectState]
    time_of_day: TimeOfDay
    weather: Weather
    camera: CameraState

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, text: str) -> "PhysicalState":
        return cls.model_validate_json(text)

    def to_prompt_text(self) -> str:
        """Compact description for prompts, in metres."""
        a = self.agent
        where = a.pose.location
        lines = [f"t={self.sim_time_s:.0f}s clock={self.time_of_day.clock} "
                 f"sun_elev={self.time_of_day.sun_elevation_deg:.0f}deg"]
        if self.weather.available and self.weather.fog_density:
            lines.append(f"fog_density={self.weather.fog_density:g}")
        held = f" holding={a.held_object}" if a.held_object else ""
        task = f" task={a.active_task.type}:{a.active_task.phase}" if a.active_task else ""
        lines.append(f"you at ({where.x / 100:.1f},{where.y / 100:.1f})m yaw={a.pose.rotation.yaw:.0f}deg "
                     f"speed={a.velocity.speed_cm_s / 100:.1f}m/s {a.posture}{held}{task}")
        for npc in self.npcs:
            lines.append(f"{npc.id} {_distance_cm(where, npc.pose.location) / 100:.1f}m away "
                         f"at ({npc.pose.location.x / 100:.1f},{npc.pose.location.y / 100:.1f})m "
                         f"speed={npc.velocity.speed_cm_s / 100:.1f}m/s")
        for obj in self.objects:
            if obj.held_by:
                lines.append(f"{obj.id} ({obj.kind}) held by {obj.held_by}")
            elif obj.pose:
                lines.append(f"{obj.id} ({obj.kind}) {_distance_cm(where, obj.pose.location) / 100:.1f}m away")
        return "\n".join(lines)


def _distance_cm(a: Vec3, b: Vec3) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5


###################################################
# Captures
###################################################

class RenderFile(_Model):
    """One ground-truth image on disk, exactly as the server sent it."""
    modality: Literal["rgb", "depth", "segmentation"]
    path: str
    sha256: str
    num_bytes: int
    format: Literal["png", "npy"]
    width: int
    height: int
    depth_stats: dict[str, float] | None = Field(
        default=None, description="min, median and max of the raw depth values. Units unverified, see SIMWORLD.md.")


class MaskColor(_Model):
    """Which segmentation colour belongs to which tracked actor."""
    id: str
    actor: str
    assigned_rgb: list[int] | None = None
    readback_rgb: list[int] | None = Field(default=None, description="What the server reported. None if it refused.")


class Capture(_Model):
    """State and renders at one moment. offset_s is measured from the start of the step."""
    offset_s: float
    tick_count: int
    sim_time_s: float
    state: PhysicalState
    renders: dict[str, RenderFile]
    mask_colors: list[MaskColor]


class SpeechEvent(_Model):
    """Someone spoke. Nothing physical happened, and listed NPCs do not react."""
    speaker_id: str
    text: str
    tick_count: int
    sim_time_s: float
    hearing_radius_cm: float
    heard_by: list[str]
    physics_effect: Literal[False] = False
    npc_reaction: Literal[False] = False


class StageTiming(_Model):
    """Wall-clock seconds per stage, for cost estimates."""
    action_apply_s: float = 0.0
    stepping_s: float = Field(default=0.0, description="Only the engine ticks.")
    control_s: float = Field(default=0.0, description="Waypoint control between ticks.")
    state_capture_s: float = 0.0
    render_s: dict[str, float] = Field(default_factory=dict, description="One entry per render, like '15s:rgb'.")
    total_s: float = 0.0
    commands_sent: int = 0


class ActionOutcome(_Model):
    """What happened to the action.

    completed: the server accepted it, or a timed action's duration has elapsed.
    in_progress: still running, send `continue` to keep it going.
    failed: did not happen, see detail.
    unverified: sent, but the reply could not be understood.
    """
    type: str
    mapping: Literal["native", "composed", "no_physics"]
    status: Literal["completed", "in_progress", "failed", "unverified"]
    detail: str = ""
    task: TaskStatus | None = None


class StepResult(_Model):
    step_index: int
    action: dict[str, Any]
    outcome: ActionOutcome
    tick_start: int
    tick_end: int
    ticks_advanced: int
    sim_time_s: float
    captures: list[Capture]
    speech_events: list[SpeechEvent] = Field(default_factory=list)
    timing: StageTiming

    @property
    def final_state(self) -> PhysicalState:
        return self.captures[-1].state


class SimCheckpoint(_Model):
    """Everything restore_state needs. `not_restored` says what a restore cannot bring back."""
    schema_version: int = 1
    backend: str
    tick_count: int
    step_index: int
    seeds: dict[str, int]
    physical: PhysicalState
    backend_state: dict[str, Any]
    not_restored: list[str]

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(self.model_dump_json(indent=1))
        temp.replace(path)  # a crash mid-write must not destroy the previous checkpoint
        return path

    @classmethod
    def load(cls, path: str | Path) -> "SimCheckpoint":
        return cls.model_validate_json(Path(path).read_text())


class RestoreReport(_Model):
    """How close a restore got. Read back from the server, not assumed."""
    ok: bool
    max_position_error_cm: float
    position_errors_cm: dict[str, float]
    respawned: list[str]
    not_restored: list[str]


###################################################
# Actions
###################################################

class _Action(_Model):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


def _check_target(target_id: str | None, info: ValidationInfo, kinds: set[str] | None = None) -> str | None:
    """Reject ids the world does not have. Skipped when no target list was passed."""
    targets = (info.context or {}).get("targets")
    if target_id is None or targets is None:
        return target_id
    if target_id not in targets:
        raise ValueError(f"unknown target id {target_id!r}, known ids: {sorted(targets)}")
    if kinds and targets[target_id] not in kinds:
        raise ValueError(f"target {target_id!r} is a {targets[target_id]}, expected one of {sorted(kinds)}")
    return target_id


def _exactly_one(a: Any, b: Any, names: str) -> None:
    if (a is None) == (b is None):
        raise ValueError(f"give exactly one of {names}")


class Wait(_Action):
    """Let time pass. Stops anything the agent was doing."""
    type: Literal["wait"] = "wait"


class Continue(_Action):
    """Keep the running task going. Any other action except speak and set_speed replaces it."""
    type: Literal["continue"] = "continue"


class MoveTo(_Action):
    type: Literal["move_to"] = "move_to"
    position: Vec3 | None = None
    target_id: str | None = None
    arrival_radius_cm: float = Field(default=150.0, gt=0, le=2000)

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info)

    @model_validator(mode="after")
    def _one_goal(self):
        _exactly_one(self.position, self.target_id, "position or target_id")
        return self


class LookAt(_Action):
    type: Literal["look_at"] = "look_at"
    position: Vec3 | None = None
    target_id: str | None = None

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info)

    @model_validator(mode="after")
    def _one_goal(self):
        _exactly_one(self.position, self.target_id, "position or target_id")
        return self


class Interact(_Action):
    """Use a target. What that means depends on its kind, see INTERACT_BY_KIND."""
    type: Literal["interact"] = "interact"
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info, set(INTERACT_BY_KIND))


class Speak(_Action):
    type: Literal["speak"] = "speak"
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip():
            raise ValueError("text is blank")
        return v


class MoveForward(_Action):
    """Walk with no goal until something else replaces it."""
    type: Literal["move_forward"] = "move_forward"


class StepForward(_Action):
    type: Literal["step_forward"] = "step_forward"
    duration_s: float = Field(gt=0, le=30)
    direction: Literal["forward", "backward"] = "forward"


class Rotate(_Action):
    type: Literal["rotate"] = "rotate"
    angle_deg: float = Field(gt=0, le=360)
    direction: Literal["left", "right"]


class Stop(_Action):
    type: Literal["stop"] = "stop"


class SetSpeed(_Action):
    type: Literal["set_speed"] = "set_speed"
    speed_cm_s: float = Field(gt=0, le=1000)


class SitDown(_Action):
    type: Literal["sit_down"] = "sit_down"


class StandUp(_Action):
    type: Literal["stand_up"] = "stand_up"


class PickUp(_Action):
    type: Literal["pick_up"] = "pick_up"
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info, {"object"})


class DropObject(_Action):
    type: Literal["drop_object"] = "drop_object"


class GetOnScooter(_Action):
    type: Literal["get_on_scooter"] = "get_on_scooter"
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info, {"scooter"})


class GetOffScooter(_Action):
    type: Literal["get_off_scooter"] = "get_off_scooter"


class EnterVehicle(_Action):
    type: Literal["enter_vehicle"] = "enter_vehicle"
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _known(cls, v, info):
        return _check_target(v, info, {"vehicle"})


class ExitVehicle(_Action):
    type: Literal["exit_vehicle"] = "exit_vehicle"


class Drive(_Action):
    """Throttle, brake and steering for the scooter or vehicle the agent is on."""
    type: Literal["drive"] = "drive"
    throttle: float = Field(ge=0, le=1)
    brake: float = Field(default=0.0, ge=0, le=1)
    steering: float = Field(default=0.0, ge=-1, le=1)


class Gesture(_Action):
    """Plays an animation. Variant only applies to discuss and argue."""
    type: Literal["gesture"] = "gesture"
    kind: Literal["discuss", "argue", "listen", "wave", "direct"]
    variant: Literal[0, 1] = 0


class StopGesture(_Action):
    type: Literal["stop_gesture"] = "stop_gesture"


Action = Annotated[
    Wait | Continue | MoveTo | LookAt | Interact | Speak | MoveForward | StepForward | Rotate | Stop | SetSpeed | SitDown | StandUp | PickUp | DropObject | GetOnScooter | GetOffScooter | EnterVehicle | ExitVehicle | Drive | Gesture | StopGesture,
    Field(discriminator="type"),
]
_ACTION_ADAPTER = TypeAdapter(Action)

# Which action `interact` becomes for each kind of target. NPCs are left out on purpose:
# SimWorld has no way to interact with one, so use speak or gesture.
INTERACT_BY_KIND = {"object": "pick_up", "seat": "sit_down", "scooter": "get_on_scooter", "vehicle": "enter_vehicle"}


def parse_action(raw: dict | str | BaseModel, targets: Mapping[str, str] | None = None) -> Any:
    """Validate an action. `targets` maps each known id to its kind.

    Raises pydantic.ValidationError for unknown actions, bad arguments and unknown ids.
    """
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if isinstance(raw, str):
        raw = json.loads(raw)
    return _ACTION_ADAPTER.validate_python(raw, context={"targets": targets})


def action_json_schema() -> dict:
    """JSON schema of the action union, for constraining a model's output."""
    return _ACTION_ADAPTER.json_schema()


class ActionSpec(_Model):
    """An honest record of how an action reaches the simulator."""
    mapping: Literal["native", "composed", "no_physics"]
    primitives: list[str]
    source: str
    across_steps: str


_ONE_SHOT = "Sent once at the start of the step. Replaces any running task."
_TIMED = "Duration is capped at the step length, so it ends inside the step. Replaces any running task."

# `source` is the file:line in simworld/simworld/communicator/unrealcv.py of the real command.
ACTION_CATALOG: dict[str, ActionSpec] = {
    "wait": ActionSpec(mapping="no_physics", primitives=["StopAgent if something was running"], source="unrealcv.py:643",
                       across_steps="Sends nothing unless a task was running, which it stops."),
    "continue": ActionSpec(mapping="no_physics", primitives=[], source="adapter only",
                           across_steps="Lets the running task keep going. With no task it is the same as wait."),
    "move_to": ActionSpec(mapping="composed", primitives=["TurnAround", "MoveForward", "StopAgent", "location", "rotation"],
                          source="unrealcv.py:615,632,643",
                          across_steps="At 200 cm/s a step covers at most 60 m. If not there at +30s the outcome is "
                                       "in_progress. Send continue, or the same move_to, to keep going. Fails as "
                                       "blocked if it makes no progress for stuck_window_s."),
    "look_at": ActionSpec(mapping="composed", primitives=["TurnAround", "vset camera rotation", "camera location"],
                          source="unrealcv.py:632,971,910",
                          across_steps="Turns the body once, then re-aims the camera before every capture until "
                                       "another action clears it, so it keeps tracking a moving target."),
    "interact": ActionSpec(mapping="composed", primitives=["SitDown", "PickUp", "GetOnScooter", "EnterVehicle"],
                           source="unrealcv.py:677,729,707,760",
                           across_steps="Picks the primitive by target kind and checks range first. Never walks "
                                        "there for you: an out-of-range target fails, so move_to first."),
    "speak": ActionSpec(mapping="no_physics", primitives=["NPC location reads"], source="adapter only",
                        across_steps="An instant event. Does not interrupt a running task. NPCs do not react."),
    "move_forward": ActionSpec(mapping="native", primitives=["MoveForward"], source="unrealcv.py:615",
                               across_steps="Keeps walking across steps until an action other than continue, speak "
                                            "or set_speed replaces it."),
    "step_forward": ActionSpec(mapping="native", primitives=["StepForward"], source="unrealcv.py:655", across_steps=_TIMED),
    "rotate": ActionSpec(mapping="native", primitives=["TurnAround"], source="unrealcv.py:632", across_steps=_TIMED),
    "stop": ActionSpec(mapping="native", primitives=["StopAgent"], source="unrealcv.py:643", across_steps=_ONE_SHOT),
    "set_speed": ActionSpec(mapping="native", primitives=["SetMaxSpeed"], source="unrealcv.py:667",
                            across_steps="Stays in effect. Does not interrupt a running task."),
    "sit_down": ActionSpec(mapping="native", primitives=["SitDown"], source="unrealcv.py:677", across_steps=_ONE_SHOT),
    "stand_up": ActionSpec(mapping="native", primitives=["StandUp"], source="unrealcv.py:692", across_steps=_ONE_SHOT),
    "pick_up": ActionSpec(mapping="native", primitives=["PickUp"], source="unrealcv.py:729", across_steps=_ONE_SHOT),
    "drop_object": ActionSpec(mapping="native", primitives=["DropOff"], source="unrealcv.py:744", across_steps=_ONE_SHOT),
    "get_on_scooter": ActionSpec(mapping="native", primitives=["GetOnScooter", "clean_garbage"],
                                 source="unrealcv.py:707,102", across_steps=_ONE_SHOT),
    "get_off_scooter": ActionSpec(mapping="composed", primitives=["GetOffScooter", "vget objects", "rename actor"],
                                  source="unrealcv.py:718, communicator.py:110-125", across_steps=_ONE_SHOT),
    "enter_vehicle": ActionSpec(mapping="native", primitives=["EnterVehicle"], source="unrealcv.py:760", across_steps=_ONE_SHOT),
    "exit_vehicle": ActionSpec(mapping="native", primitives=["ExitVehicle"], source="unrealcv.py:776", across_steps=_ONE_SHOT),
    "drive": ActionSpec(mapping="native", primitives=["SetState"], source="unrealcv.py:856,355",
                        across_steps="The inputs stay applied until the next drive or get-off."),
    "gesture": ActionSpec(mapping="native", primitives=["Discussion", "Arguing", "Listening", "Wave2Dog", "Directing"],
                          source="unrealcv.py:792,803,813,823,833",
                          across_steps="Assumed to loop until replaced, since StopAction exists. Unverified."),
    "stop_gesture": ActionSpec(mapping="native", primitives=["StopAction"], source="unrealcv.py:843", across_steps=_ONE_SHOT),
}


###################################################
# The interface the loop uses
###################################################

class PhysicsSim(abc.ABC):
    """A simulator that owns physical truth. Actions go here, never to the world model."""

    @abc.abstractmethod
    def reset(self, seed: int | None = None) -> Capture:
        """Build the world and return the state and renders at time zero."""

    @abc.abstractmethod
    def step(self, action: Any) -> StepResult:
        """Apply one action, then advance exactly one step of sim time."""

    @abc.abstractmethod
    def get_state(self) -> SimCheckpoint:
        """Snapshot the world so a run can resume or replay from here."""

    @abc.abstractmethod
    def restore_state(self, checkpoint: SimCheckpoint) -> RestoreReport:
        """Put the world back as close to the checkpoint as this simulator can."""

    @abc.abstractmethod
    def close(self) -> None:
        """Disconnect and release resources."""
