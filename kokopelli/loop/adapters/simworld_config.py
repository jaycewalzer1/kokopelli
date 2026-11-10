"""SimWorld adapter settings: blueprint names, what to spawn, and every knob of the run.

Split out of simworld.py, which re-exports every name here.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kokopelli.loop.adapters.simworld_math import parse_clock

# Real blueprint paths and names from the SimWorld source.
AGENT_ASSET = "/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C"  # config/example.yaml:116
NPC_ASSET = "/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C"  # config/example.yaml:86
SCOOTER_ASSET = "/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn.BP_Scooter_Pawn_C"  # config/example.yaml:123
UE_MANAGER_ASSET = "/Game/TrafficSystem/UE_Manager.UE_Manager_C"  # config/example.yaml:4
WEATHER_ASSET = "/Game/Weather/BP_WeatherManager.BP_WeatherManager_C"  # communicator.py:1127
MUG_ASSET = "/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C"  # examples/ue_command.ipynb cell 39
BOX_ASSET = "/Game/InteractableAsset/Box/BP_Interactable_Box.BP_Interactable_Box_C"  # examples/ue_command.ipynb cell 43
AGENT_ACTOR = "GEN_BP_Humanoid_0"  # communicator.py:162
UE_MANAGER_ACTOR = "GEN_BP_UEManager"  # communicator.py:805
WEATHER_ACTOR = "GEN_WeatherManager"  # weather_manager.py:11
NEW_HUMANOID_PREFIX = "Base_User_Agent_C_"  # communicator.py:117

VIEWMODES = {"rgb": ("lit", "png"), "depth": ("depth", "npy"), "segmentation": ("object_mask", "png")}


class SpawnSpec(BaseModel):
    """Something interactable in the world. existing=True means it is already in the level."""
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str = Field(pattern="^(object|seat|scooter|vehicle)$")
    asset: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    existing: bool = False
    actor: Optional[str] = None

    @property
    def actor_name(self) -> str:
        return self.actor or f"GEN_BP_{self.id}"


class NpcSpec(BaseModel):
    """A pedestrian. With waypoints it walks them in a loop, driven from Python so it is repeatable."""
    model_config = ConfigDict(extra="forbid")
    id: str
    position: tuple[float, float, float]
    yaw: float = 0.0
    speed_cm_s: float = 100.0
    waypoints: list[tuple[float, float]] = Field(default_factory=list)
    index: int = 0

    @property
    def actor_name(self) -> str:
        return f"GEN_BP_Pedestrian_{self.index}"  # communicator.py:367


def default_objects() -> list[SpawnSpec]:
    """Assets used by SimWorld's own example notebook. No seat: we know of no seat asset."""
    return [
        SpawnSpec(id="mug_0", kind="object", asset=MUG_ASSET, position=(290, -110, 0)),
        SpawnSpec(id="box_0", kind="object", asset=BOX_ASSET, position=(600, 300, 0)),
        SpawnSpec(id="scooter_0", kind="scooter", asset=SCOOTER_ASSET, position=(200, 200, 0), actor="GEN_BP_Scooter_0"),
    ]


class SimWorldConfig(BaseModel):
    """Every knob, with the reasoning for defaults in SIMWORLD.md under "Decisions for the owner"."""
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 9000  # docs: minimal_example.rst:10
    map_path: Optional[str] = Field(default=None, description="None keeps the map the server launched with.")

    tick_interval_s: float = Field(default=0.1, gt=0)
    step_seconds: float = Field(default=30.0, gt=0)
    capture_offsets_s: tuple[float, ...] = (15.0, 30.0)
    control_interval_s: float = Field(default=0.5, gt=0)
    velocity_window_s: float = Field(default=1.0, gt=0)
    settle_s: float = Field(default=3.0, ge=0, description="Ticks after spawn so actors fall to the ground.")

    camera_id: Optional[int] = Field(default=None, description="None finds the camera nearest the agent.")
    resolution: tuple[int, int] = (320, 240)
    fov_deg: Optional[float] = None
    modalities: tuple[str, ...] = ("rgb", "depth", "segmentation")
    out_dir: str = "out/wmloop_simworld"
    run_id: Optional[str] = None
    assign_mask_colors: bool = True

    seed: int = 0
    agent_position: tuple[float, float, float] = (0.0, 0.0, 600.0)  # communicator.py:626 spawns at z=600
    agent_yaw: float = 0.0
    agent_speed_cm_s: float = 200.0  # config/example.yaml:112
    npc_count: int = Field(default=2, ge=0, description="Random NPCs from the seed. Ignored if npcs is given.")
    npcs: Optional[list[NpcSpec]] = None
    objects: list[SpawnSpec] = Field(default_factory=default_objects)
    spawn_ue_manager: bool = True  # docs: unrealcv+.rst:64 calls it required
    spawn_weather_manager: bool = True

    hearing_radius_cm: float = Field(default=1000.0, gt=0)
    interact_radius_cm: float = Field(default=300.0, gt=0)
    stuck_window_s: float = Field(default=8.0, gt=0)
    arrival_radius_cm: float = Field(default=150.0, gt=0)  # config/example.yaml:115

    start_time: str = "08:00"
    sunrise_h: float = 6.0
    sunset_h: float = 18.0
    max_sun_elevation_deg: float = 70.0
    sunrise_azimuth_deg: float = 90.0
    max_sun_intensity: float = Field(default=10.0, gt=0, le=100, description="Noon brightness. Range from unrealcv.py:1212.")
    sun_pitch_sign: int = Field(default=-1, description="-1 if a daytime sun has negative pitch. Gate script checks it.")
    fog: Optional[tuple[float, float, float]] = None  # density, distance, falloff
    atmosphere: Optional[tuple[float, float]] = None  # rayleigh, mie

    request_timeout_s: float = 60.0  # generous: a tick can stall while Unreal compiles shaders
    render_timeout_s: float = 120.0
    connect_timeout_s: float = 30.0
    reconnect_attempts: int = Field(default=3, ge=0)
    reconnect_backoff_s: float = 2.0
    init_settle_s: float = Field(default=1.0, ge=0)  # unrealcv.py:67 sleeps 1s here
    map_load_timeout_s: float = 120.0
    restore_tolerance_cm: float = 5.0
    restore_flush_s: float = Field(default=2.0, ge=0, description="Uncounted ticks before teleporting, so turns in flight end.")

    @model_validator(mode="after")
    def _times_fit_ticks(self):
        for name, seconds in [("step_seconds", self.step_seconds), ("control_interval_s", self.control_interval_s),
                              ("velocity_window_s", self.velocity_window_s),
                              *([("settle_s", self.settle_s)] if self.settle_s else []),
                              *([("restore_flush_s", self.restore_flush_s)] if self.restore_flush_s else []),
                              *[("capture_offsets_s", s) for s in self.capture_offsets_s]]:
            self._ticks_for(seconds, name)
        if not self.capture_offsets_s or max(self.capture_offsets_s) != self.step_seconds:
            raise ValueError("the last capture must land on the end of the step")
        if min(self.capture_offsets_s) <= self.velocity_window_s:
            raise ValueError("velocity_window_s must be shorter than the first capture offset")
        if self.sun_pitch_sign not in (-1, 1):
            raise ValueError("sun_pitch_sign must be -1 or 1")
        for m in self.modalities:
            if m not in VIEWMODES:
                raise ValueError(f"unknown modality {m!r}")
        parse_clock(self.start_time)
        return self

    def _ticks_for(self, seconds: float, name: str = "time") -> int:
        """Whole ticks in `seconds`. Refuses a remainder, since exact sim time is the point."""
        ticks = round(seconds / self.tick_interval_s)
        if ticks < 1 or abs(ticks * self.tick_interval_s - seconds) > 1e-9:
            raise ValueError(f"{name}={seconds} is not a whole number of {self.tick_interval_s}s ticks")
        return ticks

    @property
    def ticks_per_step(self) -> int:
        return self._ticks_for(self.step_seconds)
