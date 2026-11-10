"""SimWorld behind the PhysicsSim interface: the Unreal server owns physical truth.

Terms: a *step* is one loop turn of 30 sim-seconds. An *engine tick* is one Unreal frame of
tick_interval_s. Sim time is always engine ticks times tick_interval_s, never the wall clock.
Read kokopelli/loop/SIMWORLD.md for what has and has not been proven against a real server.
"""
import json
import math
import random
import struct
import time
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from kokopelli.loop.adapters import simworld_commands as c
from kokopelli.loop.adapters.simworld_actions import NON_PREEMPTING, ActionsMixin  # noqa: F401
# Re-exported: callers import the config names from here.
from kokopelli.loop.adapters.simworld_config import (AGENT_ACTOR, AGENT_ASSET, BOX_ASSET, MUG_ASSET,  # noqa: F401
                                              NEW_HUMANOID_PREFIX, NPC_ASSET, SCOOTER_ASSET, UE_MANAGER_ACTOR,
                                              UE_MANAGER_ASSET, VIEWMODES, WEATHER_ACTOR, WEATHER_ASSET, NpcSpec,
                                              SimWorldConfig, SpawnSpec, default_objects)
from kokopelli.loop.adapters.simworld_control import Mover
from kokopelli.loop.adapters.simworld_math import (angle_delta, camera_to_world, distance_cm, heading_to,
                                            intrinsics_from_fov, parse_clock)
from kokopelli.loop.adapters.simworld_weather import WeatherMixin
from kokopelli.loop.adapters.simworld_wire import NUMBER, CommandError, SimWorldError, Wire, parse_numbers
from kokopelli.loop.physics import (AgentState, CameraState, Capture, Extrinsics, Gesture, MaskColor, NpcState, ObjectState,
                             PhysicalState, PhysicsSim, Pose, RenderFile, RestoreReport, Rotation, SimCheckpoint,
                             SpeechEvent, StageTiming, StepResult, TaskStatus, Vec3, Velocity, Weather, parse_action)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NPY_SIGNATURE = b"\x93NUMPY"

NOT_RESTORED = [
    "velocity and momentum: actors restart at rest, so the first moments after a restore differ",
    "animation pose and blend state",
    "NPC controller internals: routes restart toward the saved waypoint, from rest",
    "character movement state, such as being mid-air",
    "physics solver state of objects: sleep state, contacts, angular velocity",
    "anything this adapter did not spawn: level actors, or traffic if you start it yourself",
    "traffic signal timers and vehicles (this adapter does not run them)",
    "the collision counters, which are cumulative inside Unreal and have no reset command",
    "renderer history: temporal anti-aliasing, auto-exposure and Lumen caches, so pixels may differ after a restore",
    "Unreal's own frame counter and world time (ours comes from the saved tick count)",
]


class SimWorldPhysics(WeatherMixin, ActionsMixin, PhysicsSim):
    """Drives a SimWorld server. One instance, one world, one client connection."""

    def __init__(self, config: SimWorldConfig | None = None):
        self.config = config or SimWorldConfig()
        cfg = self.config
        self.wire = Wire(cfg.host, cfg.port, cfg.request_timeout_s, cfg.connect_timeout_s, cfg.reconnect_attempts,
                         cfg.reconnect_backoff_s, on_reconnect=self._after_reconnect)
        self.warnings: list[str] = []
        self.seed = cfg.seed
        self.tick_count = 0
        self.step_index = 0
        self.branch = 0
        self.camera_id: int | None = cfg.camera_id
        self.weather_available = False
        self.start_s = parse_clock(cfg.start_time)
        self.sun_max = cfg.max_sun_intensity
        self.initial_weather: Weather | None = None  # what the level had, on a server we have not touched
        self.fog = cfg.fog
        self.atmosphere = cfg.atmosphere
        self.npc_specs: list[NpcSpec] = []
        self.specs = {s.id: s for s in cfg.objects}
        self.targets: dict[str, str] = {}
        self._sync_mode = False
        self._ready = False
        self._broken: str | None = None
        self._new_world()

    def _new_world(self) -> None:
        self.agent_speed = self.config.agent_speed_cm_s
        self.posture: Literal["standing", "sitting", "on_scooter", "in_vehicle"] = "standing"
        self.held: str | None = None
        self.riding: str | None = None
        self.vehicle: str | None = None
        self.walking = False
        self.gesture: str | None = None
        self.gesture_variant = 0
        self.gaze: dict | None = None
        self._last_task_result: Mover | None = None
        self._speech: list[SpeechEvent] = []
        self._camera_overridden = False  # true once we have ever set the camera's rotation ourselves
        self._camera_base_pitch = 0.0
        self._camera_yaw_offset = 0.0
        self.task: Mover | None = None
        self.npc_movers: dict[str, Mover] = {}
        self.npc_waypoint: dict[str, int] = {}
        self.mask_colors: list[MaskColor] = []
        self._snapshots: dict[str, tuple[int, Vec3]] = {}

    ###################################################
    # Lifecycle
    ###################################################

    def connect(self) -> None:
        """Connect and send the same setup as UnrealCV.ini_unrealcv (unrealcv.py:62-67)."""
        if self.wire.connected:
            return
        self.wire.connect()
        self._init_server()

    def _init_server(self) -> None:
        w, h = self.config.resolution
        self.wire.send_no_reply(c.set_resolution(w, h))
        self.wire.send_no_reply(c.async_skinned_assets())
        time.sleep(self.config.init_settle_s)

    def close(self) -> None:
        """Leave the server running and unpaused, then disconnect. Safe to call twice."""
        if self.wire.connected and self._sync_mode:
            try:
                self.wire.request(c.resume(), resend=False)
            except SimWorldError as e:
                self.warnings.append(f"could not resume the game on close: {e}")
        self._sync_mode = False
        self._ready = False
        self.wire.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def load_map(self, map_path: str) -> None:
        """Switch level using the unrealcv library's command. Launching with the map is safer."""
        self.wire.request(c.set_level(map_path), timeout=self.config.map_load_timeout_s, resend=False)
        deadline = time.monotonic() + self.config.map_load_timeout_s
        while True:  # the level is ready once the server answers object queries again
            try:
                self._objects()
                return
            except SimWorldError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1.0)

    def reset(self, seed: int | None = None) -> Capture:
        """Build the world, pause it, and return state and renders at time zero."""
        self.connect()
        cfg = self.config
        self.seed = cfg.seed if seed is None else seed
        self._ready = False
        self._broken = None
        # Spawn while running, as every SimWorld example does. Sent even if we never paused,
        # since a client that crashed earlier may have left this server paused.
        self.wire.request(c.resume(), resend=False)
        self._sync_mode = False
        if cfg.map_path:
            self.load_map(cfg.map_path)
        self._destroy_ours()
        self._new_world()
        self.tick_count = self.step_index = 0
        self.start_s = parse_clock(cfg.start_time)
        self.branch = self._unused_branch(0)  # a re-run must not overwrite the renders of an earlier one

        self.npc_specs = cfg.npcs if cfg.npcs is not None else self._random_npcs(random.Random(self.seed))
        self._index_targets()
        self._spawn_agent()  # first, because camera ids follow spawn order (agent_system.rst:71)
        for npc in self.npc_specs:
            self._spawn_npc(npc)
        for spec in cfg.objects:
            if not spec.existing:
                self._spawn_object(spec)
        if cfg.spawn_ue_manager:
            self._spawn_manager()
        self._spawn_weather()
        self._check_spawned()

        self._enter_sync()
        for _ in range(cfg._ticks_for(cfg.settle_s, "settle_s") if cfg.settle_s else 0):
            self.wire.request(c.tick(), resend=False)
        self._setup_camera()
        self._remember_camera_mount()
        self._setup_mask_colors()
        self._apply_weather_settings()
        self._start_npc_routes()
        self._apply_sun(0.0)
        self.wire.request(c.tick(), resend=False)  # uncounted, so the sun reaches the first frame
        self._ready = True
        return self._capture(0.0, StageTiming())

    def _random_npcs(self, rng: random.Random) -> list[NpcSpec]:
        """Seeded NPC layout: a ring around the agent, each walking between two seeded points."""
        ax, ay, _ = self.config.agent_position
        npcs = []
        for i in range(self.config.npc_count):
            points = []
            angle = rng.uniform(0, 2 * math.pi)
            for _ in range(3):
                angle += rng.uniform(2.0, 4.0)  # roughly across the ring, so legs are not tiny hops
                radius = rng.uniform(400, 1500)
                points.append((round(ax + radius * math.cos(angle), 1), round(ay + radius * math.sin(angle), 1)))
            npcs.append(NpcSpec(id=f"npc_{i}", index=i, position=(points[0][0], points[0][1], 110.0),  # communicator.py:715
                                yaw=round(rng.uniform(0, 360), 1), speed_cm_s=round(rng.uniform(100, 200), 1),
                                waypoints=points[1:]))
        return npcs

    def _index_targets(self) -> None:
        self.targets = {npc.id: "npc" for npc in self.npc_specs}
        self.targets.update({s.id: s.kind for s in self.config.objects})

    def _spawn(self, asset: str, name: str, x: float, y: float, z: float, yaw: float, movable: bool = True) -> None:
        """Same order as communicator.py:620-645."""
        for command in (c.spawn(asset, name), c.set_location(name, x, y, z), c.set_rotation(name, 0, yaw, 0),
                        c.set_scale(name, 1, 1, 1), c.set_collision(name, True), c.set_movable(name, movable)):
            self.wire.request(command, resend=False)

    def _spawn_agent(self) -> None:
        cfg = self.config
        self._spawn(AGENT_ASSET, AGENT_ACTOR, *cfg.agent_position, cfg.agent_yaw)
        self.wire.request(c.set_speed(AGENT_ACTOR, self.agent_speed), resend=False)

    def _spawn_npc(self, npc: NpcSpec) -> None:
        self._spawn(NPC_ASSET, npc.actor_name, *npc.position, npc.yaw)
        self.wire.request(c.npc_speed(npc.actor_name, npc.speed_cm_s), resend=False)

    def _spawn_object(self, spec: SpawnSpec) -> None:
        self._spawn(spec.asset, spec.actor_name, *spec.position, spec.yaw)

    def _spawn_manager(self) -> None:
        self.wire.request(c.spawn(UE_MANAGER_ASSET, UE_MANAGER_ACTOR), resend=False)  # communicator.py:806
        self.wire.request(c.update_manager(UE_MANAGER_ACTOR), resend=False)  # communicator.py:810

    def _spawn_weather(self) -> None:
        if self.config.spawn_weather_manager:
            self.wire.request(c.spawn(WEATHER_ASSET, WEATHER_ACTOR), resend=False)

    def _tracked(self) -> dict[str, str]:
        tracked = {"agent": AGENT_ACTOR}
        tracked.update({npc.id: npc.actor_name for npc in self.npc_specs})
        tracked.update({s.id: s.actor_name for s in self.config.objects})
        return tracked

    def _objects(self) -> list[str]:
        return str(self.wire.request(c.list_objects())).split()

    def _check_spawned(self) -> None:
        present = {name.lower() for name in self._objects()}  # clear_env compares lowercased too (communicator.py:889)
        missing = [name for name in self._tracked().values() if name.lower() not in present]
        if missing:
            raise CommandError(f"these actors did not appear after spawning: {missing}. "
                               "The asset path may not exist in this SimWorld package.")
        self.weather_available = self.config.spawn_weather_manager and WEATHER_ACTOR.lower() in present
        if self.config.spawn_weather_manager and not self.weather_available:
            self.warnings.append(f"{WEATHER_ACTOR} did not spawn, so sun, fog and atmosphere are unavailable. "
                                 "unrealcv.py:1180 says weather is 'currently not in use for production'.")

    def _destroy_ours(self) -> None:
        """Remove what an earlier run of ours left. Never touches level actors."""
        present = {name.lower() for name in self._objects()}
        names = ["GEN_BP_Humanoid_0", UE_MANAGER_ACTOR, WEATHER_ACTOR]
        names += [f"GEN_BP_Pedestrian_{i}" for i in range(max(self.config.npc_count, len(self.config.npcs or [])))]
        names += [s.actor_name for s in self.config.objects if not s.existing]
        removed = False
        for name in names:
            if name.lower() in present:
                self.wire.request(c.destroy(name), resend=False)
                removed = True
        if removed:
            self.wire.request(c.clean_garbage(), resend=False)

    def _enter_sync(self) -> None:
        """Same order as UnrealCV.set_mode: set the interval, then pause (unrealcv.py:213-216)."""
        self.wire.request(c.set_tick_interval(self.config.tick_interval_s), resend=False)
        self.wire.request(c.pause(), resend=False)
        self._sync_mode = True

    def _after_reconnect(self) -> None:
        """Runs on every automatic reconnect. A restarted server has an empty, unpaused world."""
        self._init_server()
        if self._sync_mode:
            self.wire.request(c.set_tick_interval(self.config.tick_interval_s), resend=False)
            self.wire.request(c.pause(), resend=False)
        if self._ready and AGENT_ACTOR.lower() not in {n.lower() for n in self._objects()} and not self.riding:
            self._broken = "the server restarted and the world is gone. Call restore_state or reset."

    ###################################################
    # Camera, colours and weather setup
    ###################################################

    def _setup_camera(self) -> None:
        cfg = self.config
        if cfg.camera_id is None:
            self.camera_id = self._find_agent_camera()
        w, h = cfg.resolution
        self.wire.request(c.set_camera_size(self.camera_id, w, h), resend=False)
        if cfg.fov_deg is not None:
            self.wire.request(c.set_camera_fov(self.camera_id, cfg.fov_deg), resend=False)

    def _remember_camera_mount(self) -> None:
        """How the camera sits on the body before we touch it, so we can put it back."""
        pitch, yaw, _ = parse_numbers(self.wire.request(c.get_camera_rotation(self.camera_id)), 3, "camera rotation")
        self._camera_base_pitch = pitch
        self._camera_yaw_offset = angle_delta(yaw, self._read_pose(self._agent_actor).rotation.yaw)

    def _find_agent_camera(self) -> int:
        """Pick the camera closest to the agent. Ids depend on spawn order, so we check, not assume."""
        here = self._read_pose(self._agent_actor).location
        try:
            names = str(self.wire.request(c.list_cameras())).split()
        except CommandError as e:
            self.warnings.append(f"could not list cameras, assuming camera 1: {e}")
            return 1
        best, best_distance = None, math.inf
        for cam in range(1, len(names)):  # camera 0 is the level's spectator (agent_system.rst:71)
            try:
                d = distance_cm(here, self._read_camera_location(cam))
            except SimWorldError:
                continue
            if d < best_distance:
                best, best_distance = cam, d
        if best is None:
            self.warnings.append(f"no camera found near the agent (server lists {names}), assuming camera 1")
            return 1
        if best_distance > 500:
            self.warnings.append(f"nearest camera {best} is {best_distance:.0f}cm from the agent, may not be its camera")
        return best

    def _setup_mask_colors(self) -> None:
        """Give each tracked actor its own mask colour, then ask the server what it actually uses.

        SimWorld assigns mask colours the same way in generate_world (communicator.py:864).
        """
        colors = []
        for i, (actor_id, actor) in enumerate(sorted(self._tracked().items())):
            assigned = None
            if self.config.assign_mask_colors:
                assigned = [(40 + 53 * i) % 256, (200 - 37 * i) % 256, (90 + 101 * i) % 256]
                try:
                    self.wire.request(c.set_mask_color(actor, *assigned), resend=False)
                except CommandError as e:
                    self.warnings.append(f"could not set mask colour on {actor}: {e}")
                    assigned = None
            readback = None
            try:  # reply looks like (R=255,G=128,B=64), and maybe a fourth value, per unrealcv/api.py:1487,748
                numbers = NUMBER.findall(str(self.wire.request(c.get_mask_color(actor))))
                readback = [int(float(n)) for n in numbers[:3]] if len(numbers) >= 3 else None
            except CommandError:
                pass  # the server does not report colours, so only `assigned` is known
            colors.append(MaskColor(id=actor_id, actor=actor, assigned_rgb=assigned, readback_rgb=readback))
        self.mask_colors = colors

    ###################################################
    # Reading the world
    ###################################################

    @property
    def sim_time_s(self) -> float:
        return round(self.tick_count * self.config.tick_interval_s, 6)

    @property
    def _agent_actor(self) -> str:
        return self.specs[self.riding].actor_name if self.riding else AGENT_ACTOR  # the humanoid is gone while riding

    def _read_location(self, actor: str) -> Vec3:
        x, y, z = parse_numbers(self.wire.request(c.get_location(actor)), 3, f"location of {actor}")
        return Vec3(x=x, y=y, z=z)

    def _read_pose(self, actor: str) -> Pose:
        pitch, yaw, roll = parse_numbers(self.wire.request(c.get_rotation(actor)), 3, f"rotation of {actor}")
        return Pose(location=self._read_location(actor), rotation=Rotation(pitch=pitch, yaw=yaw, roll=roll))

    def _read_camera_location(self, cam: int) -> Vec3:
        x, y, z = parse_numbers(self.wire.request(c.get_camera_location(cam)), 3, "camera location")
        return Vec3(x=x, y=y, z=z)

    def _read_camera(self) -> CameraState:
        cam = self.camera_id
        assert cam is not None  # set by reset() before any read
        location = self._read_camera_location(cam)
        # The docstring at unrealcv.py:921 says yaw first, but :969, ue_detail.rst:69 and the
        # library's own decoder say pitch first. The gate script checks this on a real server.
        pitch, yaw, roll = parse_numbers(self.wire.request(c.get_camera_rotation(cam)), 3, "camera rotation")
        rotation = Rotation(pitch=pitch, yaw=yaw, roll=roll)
        fov = parse_numbers(self.wire.request(c.get_camera_fov(cam)), 1, "camera fov")[0]
        width, height = parse_numbers(self.wire.request(c.get_camera_size(cam)), 2, "camera size")
        return CameraState(camera_id=cam, intrinsics=intrinsics_from_fov(int(width), int(height), fov),
                           extrinsics=Extrinsics(location_cm=location, rotation_deg=rotation,
                                                 camera_to_world=camera_to_world(rotation)))

    def _velocity(self, actor: str, location: Vec3) -> Velocity:
        """Finite difference against the pose saved velocity_window_s before this capture."""
        saved = self._snapshots.get(actor)
        if saved is None or saved[0] >= self.tick_count:
            return Velocity(vector_cm_s=Vec3(x=0, y=0, z=0), speed_cm_s=0.0, window_s=0.0)
        window = (self.tick_count - saved[0]) * self.config.tick_interval_s
        v = Vec3(x=(location.x - saved[1].x) / window, y=(location.y - saved[1].y) / window,
                 z=(location.z - saved[1].z) / window)
        return Velocity(vector_cm_s=v, speed_cm_s=math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2), window_s=window)

    def _snapshot_for_velocity(self) -> None:
        self._snapshots[self._agent_actor] = (self.tick_count, self._read_location(self._agent_actor))
        for npc in self.npc_specs:
            self._snapshots[npc.actor_name] = (self.tick_count, self._read_location(npc.actor_name))

    def _read_collisions(self) -> dict[str, int] | None:
        """Reply keys from communicator.py:465-468. Optional because it is a blueprint call."""
        try:
            reply = json.loads(str(self.wire.request(c.get_collisions(self._agent_actor), resend=True)))
            return {key: int(reply[key]) for key in
                    ("HumanCollision", "ObjectCollision", "BuildingCollision", "VehicleCollision")}
        except (CommandError, ValueError, KeyError, TypeError):
            return None

    def _task_status(self) -> TaskStatus | None:
        if self.task:
            return TaskStatus(type="move_to", phase=self.task.phase, goal=self.task.goal, target_id=self.task.target_id,
                              distance_remaining_cm=self.task.last_distance_cm)
        if self.walking:
            return TaskStatus(type="move_forward", phase="walking")
        return None

    def read_state(self) -> PhysicalState:
        """Read the whole physical state from the server, right now."""
        pose = self._read_pose(self._agent_actor)
        agent = AgentState(id="agent", actor=self._agent_actor, pose=pose,
                           velocity=self._velocity(self._agent_actor, pose.location), posture=self.posture,
                           held_object=self.held, max_speed_cm_s=self.agent_speed, gesture=self.gesture,
                           active_task=self._task_status(), collisions=self._read_collisions())
        npcs = []
        for spec in self.npc_specs:
            npc_pose = self._read_pose(spec.actor_name)
            npcs.append(NpcState(id=spec.id, actor=spec.actor_name, pose=npc_pose,
                                 velocity=self._velocity(spec.actor_name, npc_pose.location)))
        objects = []
        for spec in self.config.objects:
            try:
                object_pose: Pose | None = self._read_pose(spec.actor_name)
            except CommandError:
                object_pose = None  # some actions consume the actor, as the humanoid is while riding
            objects.append(ObjectState(id=spec.id, actor=spec.actor_name, kind=spec.kind, present=object_pose is not None,
                                       pose=object_pose, held_by="agent" if self.held == spec.id else None))
        return PhysicalState(tick_count=self.tick_count, sim_time_s=self.sim_time_s, agent=agent,
                             npcs=sorted(npcs, key=lambda n: n.id), objects=sorted(objects, key=lambda o: o.id),
                             time_of_day=self._time_of_day(self.sim_time_s), weather=self.read_weather(),
                             camera=self._read_camera())

    ###################################################
    # Rendering
    ###################################################

    def _render_dir(self) -> Path:
        run = self.config.run_id or f"wmloop_seed{self.seed}"
        return Path(self.config.out_dir) / run / f"branch_{self.branch}" / f"step_{self.step_index:04d}"

    def render(self, modality: str, offset_s: float) -> RenderFile:
        """Fetch one image and save the server's bytes untouched.

        We do not use UnrealCV.get_image: it turns any error into a black 640x480 image
        (unrealcv.py:1083-1085) and turns depth into a colour picture (unrealcv.py:1096-1110).
        """
        viewmode, fmt = VIEWMODES[modality]
        data = self.wire.request(c.render(self.camera_id, viewmode, fmt), timeout=self.config.render_timeout_s)
        if not isinstance(data, bytes | bytearray):
            raise CommandError(f"expected {fmt} bytes for {modality}, got {str(data)[:200]!r}")
        stats = None
        if fmt == "png":
            if not data.startswith(PNG_SIGNATURE) or len(data) < 24:
                raise CommandError(f"{modality} reply is not a PNG (starts {bytes(data[:8])!r})")
            width, height = struct.unpack(">II", data[16:24])  # PNG IHDR holds the size at this offset
        else:
            if not data.startswith(NPY_SIGNATURE):
                raise CommandError(f"{modality} reply is not an npy file (starts {bytes(data[:8])!r})")
            array = np.load(BytesIO(data), allow_pickle=False)
            height, width = array.shape[:2]
            stats = {"min": float(np.min(array)), "median": float(np.median(array)), "max": float(np.max(array))}
        if (width, height) != tuple(self.config.resolution):
            self.warnings.append(f"{modality} came back {width}x{height}, asked for {self.config.resolution}")
        folder = self._render_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"t{offset_s:04.0f}_{modality}.{fmt}"
        path.write_bytes(data)
        return RenderFile(modality=cast(Any, modality), path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                          num_bytes=len(data), format=cast(Any, fmt), width=int(width), height=int(height), depth_stats=stats)

    def _capture(self, offset_s: float, timing: StageTiming) -> Capture:
        start = time.perf_counter()
        state = self.read_state()
        timing.state_capture_s += time.perf_counter() - start
        renders = {}
        for modality in self.config.modalities:
            start = time.perf_counter()
            renders[modality] = self.render(modality, offset_s)
            timing.render_s[f"{offset_s:g}s:{modality}"] = time.perf_counter() - start
        return Capture(offset_s=offset_s, tick_count=self.tick_count, sim_time_s=self.sim_time_s, state=state,
                       renders=renders, mask_colors=self.mask_colors)

    def _before_capture(self, capture_time_s: float) -> None:
        """Runs one tick before a capture, so light and camera changes reach the rendered frame."""
        self._apply_sun(capture_time_s)
        if self.gaze:
            self._aim_camera()
        elif self._camera_overridden:
            # Unverified whether a set rotation sticks or the camera follows the body again.
            # Doing this before every capture makes the render right in both cases.
            yaw = self._read_pose(self._agent_actor).rotation.yaw + self._camera_yaw_offset
            self.wire.request(c.set_camera_rotation(self.camera_id, self._camera_base_pitch, round(yaw, 4), 0), resend=False)

    def _gaze_point(self) -> Vec3:
        assert self.gaze is not None  # only called while a gaze is set
        if self.gaze.get("target_id"):
            return self._read_location(self._actor_for(self.gaze["target_id"]))
        return Vec3(**self.gaze["position"])

    def _aim_camera(self) -> None:
        assert self.camera_id is not None  # set by reset() before any aim
        camera = self._read_camera_location(self.camera_id)
        yaw, pitch = heading_to(camera, self._gaze_point())
        self.wire.request(c.set_camera_rotation(self.camera_id, round(pitch, 4), round(yaw, 4), 0), resend=False)
        self._camera_overridden = True

    def _actor_for(self, target_id: str) -> str:
        return self._tracked()[target_id]

    ###################################################
    # Stepping
    ###################################################

    def step(self, action: Any) -> StepResult:
        """Apply one action, then advance exactly one step, capturing at each offset.

        A bad action raises pydantic.ValidationError before anything changes. A failure during
        the step leaves the world half-advanced, so stepping refuses until restore_state or reset.
        """
        action = parse_action(action, self.targets)
        if not self._ready:
            raise SimWorldError("call reset() or restore_state() before step()")
        if self._broken:
            raise SimWorldError(f"cannot step: {self._broken}")
        # A read first, because reads can reconnect safely. An idle link that dropped between
        # steps recovers here, instead of surfacing as a lost tick that forces a restore.
        self._objects()
        if self._broken:
            raise SimWorldError(f"cannot step: {self._broken}")
        try:
            return self._step(action)
        except SimWorldError as e:
            self._broken = f"the previous step failed at tick {self.tick_count}: {e}"
            raise

    def _step(self, action: Any) -> StepResult:
        cfg = self.config
        self.step_index += 1
        started, sent_before, tick_start = time.perf_counter(), self.wire.commands_sent, self.tick_count
        timing = StageTiming()

        start = time.perf_counter()
        self._speech = []
        outcome = self._apply(action)
        timing.action_apply_s = time.perf_counter() - start

        control_every = cfg._ticks_for(cfg.control_interval_s)
        window = cfg._ticks_for(cfg.velocity_window_s)
        capture_ticks = {cfg._ticks_for(offset): offset for offset in cfg.capture_offsets_s}
        self._snapshots = {}
        captures = []
        snapshot_ticks = {t - window for t in capture_ticks}
        for done in range(1, cfg.ticks_per_step + 1):
            if done in capture_ticks:  # the last tick before a capture
                start = time.perf_counter()
                self._before_capture(round((tick_start + done) * cfg.tick_interval_s, 6))
                timing.state_capture_s += time.perf_counter() - start

            start = time.perf_counter()
            self.wire.request(c.tick(), resend=False)
            self.tick_count += 1
            timing.stepping_s += time.perf_counter() - start

            if done % control_every == 0:
                start = time.perf_counter()
                self._control()
                timing.control_s += time.perf_counter() - start
            if done in snapshot_ticks:
                start = time.perf_counter()
                self._snapshot_for_velocity()
                timing.state_capture_s += time.perf_counter() - start
            if done in capture_ticks:
                captures.append(self._capture(capture_ticks[done], timing))

        outcome = self._finish_outcome(outcome)
        timing.total_s = time.perf_counter() - started
        timing.commands_sent = self.wire.commands_sent - sent_before
        return StepResult(step_index=self.step_index, action=action.model_dump(), outcome=outcome,
                          tick_start=tick_start, tick_end=self.tick_count, ticks_advanced=self.tick_count - tick_start,
                          sim_time_s=self.sim_time_s, captures=captures, speech_events=self._speech, timing=timing)

    ###################################################
    # Checkpoint and restore
    ###################################################

    def get_state(self) -> SimCheckpoint:
        """Snapshot between steps. Refuses if the last step failed, since the state is suspect."""
        if not self._ready:
            raise SimWorldError("no world to checkpoint, call reset() first")
        if self._broken:
            raise SimWorldError(f"will not checkpoint: {self._broken}")
        physical = self.read_state()
        return SimCheckpoint(
            backend="simworld", tick_count=self.tick_count, step_index=self.step_index, seeds={"master": self.seed},
            physical=physical, not_restored=list(NOT_RESTORED),
            # Through JSON, so later steps cannot rewrite a checkpoint already taken, and so it
            # compares equal to a copy loaded from disk (tuples would come back as lists).
            backend_state=json.loads(json.dumps({
                "tick_interval_s": self.config.tick_interval_s, "start_s": self.start_s, "sun_max": self.sun_max,
                "agent_speed": self.agent_speed, "posture": self.posture, "held": self.held, "riding": self.riding,
                "vehicle": self.vehicle, "walking": self.walking, "gesture": self.gesture,
                "gesture_variant": self.gesture_variant, "gaze": self.gaze,
                "task": self.task.to_dict() if self.task else None,
                "npc_specs": [npc.model_dump(mode="json") for npc in self.npc_specs],
                "npc_movers": {i: m.to_dict() for i, m in self.npc_movers.items()},
                "npc_waypoint": self.npc_waypoint, "fog": self.fog, "atmosphere": self.atmosphere,
                "camera_id": self.camera_id, "branch": self.branch, "camera_overridden": self._camera_overridden,
                "camera_base_pitch": self._camera_base_pitch, "camera_yaw_offset": self._camera_yaw_offset,
                "mask_colors": [m.model_dump() for m in self.mask_colors],
            })))

    def restore_state(self, checkpoint: SimCheckpoint) -> RestoreReport:
        """Put actors back by teleporting them. Works on a restarted server by respawning what is missing.

        This is not a save-state. Read checkpoint.not_restored for what cannot come back.
        Returns measured position errors rather than assuming the teleports worked.
        """
        saved = checkpoint.backend_state
        if checkpoint.backend != "simworld":
            raise ValueError(f"checkpoint is from {checkpoint.backend!r}")
        if saved["tick_interval_s"] != self.config.tick_interval_s:
            raise ValueError(f"checkpoint used tick interval {saved['tick_interval_s']}, config says "
                             f"{self.config.tick_interval_s}. Sim time would stop meaning the same thing.")
        self.connect()
        self._ready = False
        self.seed = checkpoint.seeds["master"]
        self.npc_specs = [NpcSpec(**npc) for npc in saved["npc_specs"]]
        self._index_targets()

        self._leave_carriers()
        respawned = self._respawn_missing()
        self._enter_sync()

        if AGENT_ACTOR in respawned:  # a new humanoid is standing, empty-handed and idle
            self.held, self.gesture, self.posture = None, None, "standing"
        self.wire.request(c.stop_agent(AGENT_ACTOR), resend=False)
        if self.gesture:
            self.wire.request(c.stop_gesture(AGENT_ACTOR), resend=False)
        if self.held:  # drop before moving things, or the held object follows the hand
            self.wire.request(c.drop_object(AGENT_ACTOR), resend=False)
        if self.posture == "sitting":
            self.wire.request(c.stand_up(AGENT_ACTOR), resend=False)
        state = checkpoint.physical
        for npc in state.npcs:
            self.wire.request(c.npc_stop(npc.actor), resend=False)
        # A stop may not cancel a turn already playing, which would keep rotating an actor
        # after we place it. So run it out on uncounted ticks first. They do not change sim time.
        for _ in range(self.config._ticks_for(self.config.restore_flush_s) if self.config.restore_flush_s else 0):
            self.wire.request(c.tick(), resend=False)

        self._place(AGENT_ACTOR, state.agent.pose)
        self.wire.request(c.set_speed(AGENT_ACTOR, saved["agent_speed"]), resend=False)
        for npc in state.npcs:
            self._place(npc.actor, npc.pose)
        for spec in self.npc_specs:
            self.wire.request(c.npc_speed(spec.actor_name, spec.speed_cm_s), resend=False)
        for obj in state.objects:
            if obj.pose is not None and not obj.held_by:
                self._place(obj.actor, obj.pose)

        self._restore_posture(checkpoint)
        self._restore_adapter_state(checkpoint)
        report = self._measure_restore(checkpoint, respawned)
        self._ready = True
        self._broken = None
        return report

    def _present(self) -> set[str]:
        return {name.lower() for name in self._objects()}

    def _leave_carriers(self) -> None:
        """Get the humanoid back on foot, if the scooter or vehicle still exists."""
        present = self._present()
        if self.riding:
            if self.specs[self.riding].actor_name.lower() in present:
                self._do_get_off_scooter(None)
            self.riding, self.posture = None, "standing"
        if self.vehicle:
            if self._actor_for(self.vehicle).lower() in present:
                self.wire.request(c.exit_vehicle(AGENT_ACTOR, self._actor_for(self.vehicle)), resend=False)
            self.vehicle, self.posture = None, "standing"

    def _respawn_missing(self) -> list[str]:
        """After a server restart everything is gone. The agent goes first to keep its camera id."""
        present = self._present()
        spawners = [(AGENT_ACTOR, self._spawn_agent)]
        spawners += [(npc.actor_name, lambda npc=npc: self._spawn_npc(npc)) for npc in self.npc_specs]
        spawners += [(spec.actor_name, lambda spec=spec: self._spawn_object(spec))
                     for spec in self.config.objects if not spec.existing]
        if self.config.spawn_ue_manager:
            spawners.append((UE_MANAGER_ACTOR, self._spawn_manager))
        if self.config.spawn_weather_manager:
            spawners.append((WEATHER_ACTOR, self._spawn_weather))
        missing = [(name, spawn) for name, spawn in spawners if name.lower() not in present]
        if missing:
            self.wire.request(c.resume(), resend=False)  # reset spawns unpaused, so do the same here
            self._sync_mode = False
        for _, spawn in missing:
            spawn()
        self.weather_available = self.config.spawn_weather_manager and WEATHER_ACTOR.lower() in self._present()
        return [name for name, _ in missing]

    def _place(self, actor: str, pose: Pose) -> None:
        loc, rot = pose.location, pose.rotation
        self.wire.request(c.set_location(actor, loc.x, loc.y, loc.z), resend=False)
        self.wire.request(c.set_rotation(actor, rot.pitch, rot.yaw, rot.roll), resend=False)

    def _restore_posture(self, checkpoint: SimCheckpoint) -> None:
        """Replay what the agent was doing. Best effort, and the animations restart from the top."""
        saved = checkpoint.backend_state
        if saved["held"]:
            self.wire.request(c.pick_up(AGENT_ACTOR, self._actor_for(saved["held"])), resend=False)
        if saved["posture"] == "sitting":
            self.wire.request(c.sit_down(AGENT_ACTOR), resend=False)
        if saved["riding"]:
            self.wire.request(c.get_on_scooter(AGENT_ACTOR), resend=False)
            self.wire.request(c.clean_garbage(), resend=False)
            self._place(self.specs[saved["riding"]].actor_name, checkpoint.physical.agent.pose)
        if saved["vehicle"]:
            self.wire.request(c.enter_vehicle(AGENT_ACTOR, self._actor_for(saved["vehicle"])), resend=False)
        if saved["walking"]:
            self.wire.request(c.move_forward(AGENT_ACTOR), resend=False)
        if saved["gesture"]:
            self._do_gesture(Gesture(kind=saved["gesture"], variant=saved["gesture_variant"]))

    def _restore_adapter_state(self, checkpoint: SimCheckpoint) -> None:
        saved = checkpoint.backend_state
        self.tick_count, self.step_index = checkpoint.tick_count, checkpoint.step_index
        self.start_s, self.sun_max = saved["start_s"], saved["sun_max"]
        self.agent_speed, self.gesture_variant = saved["agent_speed"], saved["gesture_variant"]
        self.held, self.riding, self.vehicle = saved["held"], saved["riding"], saved["vehicle"]
        self.posture, self.walking, self.gesture, self.gaze = saved["posture"], saved["walking"], saved["gesture"], saved["gaze"]
        self.fog = tuple(saved["fog"]) if saved["fog"] else None
        self.atmosphere = tuple(saved["atmosphere"]) if saved["atmosphere"] else None
        self.task = Mover(**saved["task"]) if saved["task"] else None
        if self.task:
            self.task.restart()
        self.npc_waypoint = dict(saved["npc_waypoint"])
        self.npc_movers = {i: Mover(**m) for i, m in saved["npc_movers"].items()}
        for mover in self.npc_movers.values():
            mover.restart()
        self._snapshots = {}
        self._last_task_result = None
        self.branch = self._unused_branch(saved["branch"] + 1)

        self.camera_id = saved["camera_id"]
        self._setup_camera()
        self.mask_colors = [MaskColor(**m) for m in saved["mask_colors"]]
        for color in self.mask_colors:  # a respawned actor has lost its colour
            if color.assigned_rgb:
                self.wire.request(c.set_mask_color(color.actor, *color.assigned_rgb), resend=False)
        self._camera_base_pitch, self._camera_yaw_offset = saved["camera_base_pitch"], saved["camera_yaw_offset"]
        if self._camera_overridden or saved["camera_overridden"]:  # leave an untouched camera alone
            camera = checkpoint.physical.camera.extrinsics.rotation_deg
            self.wire.request(c.set_camera_rotation(self.camera_id, camera.pitch, camera.yaw, camera.roll), resend=False)
            self._camera_overridden = True
        if self.weather_available:
            if self.fog:
                self.wire.request(c.set_fog(WEATHER_ACTOR, *self.fog), resend=False)
            if self.atmosphere:
                self.wire.request(c.set_atmosphere(WEATHER_ACTOR, *self.atmosphere), resend=False)
            self._apply_sun(self.sim_time_s)

    def _unused_branch(self, first: int) -> int:
        """A replay must not overwrite the renders of the run it branched from."""
        run = self.config.run_id or f"wmloop_seed{self.seed}"
        branch = first
        while (Path(self.config.out_dir) / run / f"branch_{branch}").exists():
            branch += 1
        return branch

    def _measure_restore(self, checkpoint: SimCheckpoint, respawned: list[str]) -> RestoreReport:
        state = checkpoint.physical
        errors = {"agent": distance_cm(self._read_location(self._agent_actor), state.agent.pose.location)}
        for npc in state.npcs:
            errors[npc.id] = distance_cm(self._read_location(npc.actor), npc.pose.location)
        for obj in state.objects:
            if obj.pose is not None and not obj.held_by:
                errors[obj.id] = distance_cm(self._read_location(obj.actor), obj.pose.location)
        worst = max(errors.values())
        return RestoreReport(ok=worst <= self.config.restore_tolerance_cm, max_position_error_cm=worst,
                             position_errors_cm=errors, respawned=respawned, not_restored=list(NOT_RESTORED))
