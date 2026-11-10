#!/usr/bin/env python
"""Gate script: does the SimWorld adapter's belief about the server hold on a real one?

    python tools/pace/wmloop_one_tick.py --port 9000                 # one real step, seconds per stage
    python tools/pace/wmloop_one_tick.py --port 9000 --checklist     # exercise every capability once
    python tools/pace/wmloop_one_tick.py --fake --checklist          # same, against the fake server

A check prints PASS only when it measured the thing itself. Where a person has to look at a
picture it prints LOOK and the file. The exit code is 0 only if nothing FAILed.
"""
import argparse
import json
import math
import os
import platform
import sys
import tempfile
import time
import traceback
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kokopelli.loop.adapters.simworld import (AGENT_ACTOR, WEATHER_ACTOR, SimWorldConfig,  # noqa: E402
                                       SimWorldPhysics)
from kokopelli.loop.adapters import simworld_commands as c  # noqa: E402
from kokopelli.loop.adapters.simworld_math import (distance_2d_cm, heading_to, project_point,  # noqa: E402
                                            sun_pitch_from_elevation)
from kokopelli.loop.adapters.simworld_wire import SimWorldError, probe_server  # noqa: E402
from kokopelli.loop.physics import ACTION_CATALOG, PhysicalState, SimCheckpoint, StepResult, parse_action  # noqa: E402

FAKE_BANNER = """
################################################################
#  FAKE SERVER. Nothing below says anything about Unreal.      #
#  It only shows our client sends what we believe is right.    #
################################################################
"""


class Report:
    """Collects results, prints them as they happen, and writes JSON for sending back."""

    def __init__(self, fake: bool):
        self.fake = fake
        self.rows = []
        self.extra = {}

    def add(self, name: str, status: str, detail: str = "") -> None:
        label = f"FAKE {status}" if self.fake else status
        print(f"[{label:>9}] {name}: {detail}", flush=True)
        self.rows.append({"check": name, "status": status, "detail": detail})

    def check(self, name, function) -> None:
        """Run one check. Any exception is that check's FAIL, and the next check still runs."""
        started = time.perf_counter()
        try:
            status, detail = function()
        except Exception as e:
            status, detail = "FAIL", f"{type(e).__name__}: {e}"
            self.extra.setdefault("tracebacks", {})[name] = traceback.format_exc()
        self.add(name, status, f"{detail} ({time.perf_counter() - started:.2f}s)")

    @property
    def failed(self) -> int:
        return sum(row["status"] == "FAIL" for row in self.rows)

    def summary(self) -> None:
        counts = {s: sum(r["status"] == s for r in self.rows) for s in ("PASS", "FAIL", "LOOK", "SKIP")}
        tag = "FAKE SERVER" if self.fake else "REAL SERVER"
        print(f"\n{tag} SUMMARY: {counts['PASS']} pass, {counts['FAIL']} fail, "
              f"{counts['LOOK']} to look at, {counts['SKIP']} skipped")
        for row in self.rows:
            if row["status"] == "FAIL":
                print(f"  FAILED: {row['check']}: {row['detail']}")

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"server": "FAKE" if self.fake else "REAL", "results": self.rows, **self.extra}, indent=1))
        print(f"\nWrote {path}. Send this file back, along with the UE log.")


def verdict(ok: bool, detail: str) -> tuple[str, str]:
    return ("PASS" if ok else "FAIL"), detail


def png_mean_and_colors(path: str):
    """Mean brightness and the set of colours in a PNG. Needs pillow, which simworld requires."""
    import numpy as np
    from PIL import Image
    array = np.asarray(Image.open(path).convert("RGB"))
    return float(array.mean()), {tuple(int(v) for v in rgb) for rgb in np.unique(array.reshape(-1, 3), axis=0)}


def print_timing(result: StepResult) -> None:
    t = result.timing
    print(f"\nSeconds per stage for one step ({result.ticks_advanced} engine ticks, {t.commands_sent} commands):")
    print(f"  action apply   {t.action_apply_s:10.3f}")
    print(f"  stepping       {t.stepping_s:10.3f}   ({t.stepping_s / max(1, result.ticks_advanced) * 1000:.1f} ms per tick)")
    print(f"  waypoint ctrl  {t.control_s:10.3f}")
    print(f"  state capture  {t.state_capture_s:10.3f}")
    for name, seconds in t.render_s.items():
        print(f"  render {name:<16}{seconds:7.3f}")
    print(f"  total          {t.total_s:10.3f}")
    # 60 steps of total_s seconds, divided by 60 seconds per minute, cancels out.
    print(f"  60 steps (30 sim-minutes) would take about {t.total_s:.1f} wall-clock minutes at this rate")


class Checklist:
    """One check per capability in kokopelli/loop/SIMWORLD.md."""

    def __init__(self, sim: SimWorldPhysics, report: Report, out: Path):
        self.sim, self.report, self.out = sim, report, out

    def run(self) -> None:
        r, sim = self.report, self.sim
        r.check("1 server says hello", self.hello)
        self.first = None
        r.check("1 reset spawns the world", self.reset)
        if self.first is None:
            r.add("remaining checks", "SKIP", "reset failed, so nothing else can run")
            return
        r.check("1 server command list", self.server_commands)
        r.check("1 reconnect after a dropped link", self.reconnect)
        r.check("2 paused means paused", self.paused_means_paused)
        r.check("2 step is exactly 30 sim-seconds by tick count", self.exact_step)
        r.check("2 tick interval really scales sim time", self.tick_scale)
        r.check("3 state serializes and round-trips", self.state_round_trip)
        r.check("3 velocity agrees with distance over time", self.velocity)
        r.check("3 NPCs have poses and walk their routes", self.npcs_move)
        r.check("3 camera rotation order is pitch yaw roll", self.camera_rotation_order)
        r.check("3 camera is the agent's and rides with it", self.camera_rides)
        r.check("3 intrinsics agree with server fov and size", self.intrinsics)
        r.check("4 renders are real images, not black", self.renders)
        r.check("4 depth values look like distances", self.depth)
        r.check("4 mask colours map to actors", self.mask_map)
        r.check("5 schema rejects bad actions", self.schema)
        r.check("6 move_to reaches a goal in sim time", self.move_to)
        r.check("6 move_to over 30s continues across steps", self.long_move)
        r.check("6 look_at puts the target in the middle of the frame", self.look_at)
        r.check("6 camera follows the body again after look_at", self.camera_after_look)
        r.check("6 speak emits an event and changes nothing", self.speak)
        r.check("6 interact picks up an object", self.interact_pick_up)
        r.check("5 native actions are accepted", self.native_actions)
        r.check("6 interact rides the scooter and gets off", self.scooter)
        r.check("7 time of day sets the sun, read back", self.sun_read_back)
        r.check("7 daytime sign: brighter at noon than midnight", self.sun_sign)
        r.check("7 weather set and read back", self.weather)
        r.check("8 checkpoint round-trips through disk", self.checkpoint_file)
        r.check("8 restore puts actors back", self.restore)
        r.check("9 replay from a checkpoint repeats", self.replay_drift)
        r.check("10 timing fields are filled", self.timing)
        unsupported = sim.wire.unsupported_seen()
        r.extra["unsupported_commands_seen"] = unsupported
        r.extra["adapter_warnings"] = sim.warnings
        r.add("commands the server does not advertise", "LOOK" if unsupported else "PASS",
              f"{len(unsupported)} kinds, full list in the report: {unsupported[:6]}")
        r.add("adapter warnings", "LOOK" if sim.warnings else "PASS", f"{len(sim.warnings)}: {sim.warnings[:5]}")

    # 1. Lifecycle
    def hello(self):
        return "PASS", repr(probe_server(self.sim.config.host, self.sim.config.port, 10.0))

    def reset(self):
        self.first = self.sim.reset()
        return "PASS", f"camera {self.sim.camera_id}, {len(self.first.state.npcs)} NPCs, {len(self.first.state.objects)} objects"

    def server_commands(self):
        templates = self.sim.wire.templates
        self.report.extra["server_commands"] = list(templates) if templates else None
        (self.out / "server_commands.txt").write_text("\n".join(templates) if templates else "server gave no list\n")
        return "LOOK", f"{len(templates) if templates else 'no'} commands advertised, saved to server_commands.txt"

    def reconnect(self):
        before = self.sim.wire.reconnects
        self.sim.wire._drop()
        self.sim.wire.request(c.list_objects())
        return verdict(self.sim.wire.reconnects == before + 1 and self.sim.wire.connected, "dropped and reconnected once")

    # 2. Stepping
    def paused_means_paused(self):
        """If the game is really paused, a walker goes nowhere while no ticks are sent."""
        self.sim.wire.request(c.move_forward(AGENT_ACTOR), resend=False)
        a = self.sim._read_location(AGENT_ACTOR)
        time.sleep(2.0)
        b = self.sim._read_location(AGENT_ACTOR)
        self.sim.wire.request(c.stop_agent(AGENT_ACTOR), resend=False)
        moved = distance_2d_cm(a, b)
        return verdict(moved < 1.0, f"moved {moved:.2f}cm during 2s of wall clock with no ticks")

    def exact_step(self):
        before = self.sim.tick_count
        self.result = self.sim.step({"type": "wait"})
        offsets = [capture.offset_s for capture in self.result.captures]
        ok = self.sim.tick_count - before == self.sim.config.ticks_per_step and offsets == [15.0, 30.0]
        print_timing(self.result)
        return verdict(ok, f"{self.result.ticks_advanced} ticks, captures at {offsets}")

    def _walk_distance(self, ticks: int) -> float:
        speed_start = self.sim._read_location(AGENT_ACTOR)
        self.sim.wire.request(c.move_forward(AGENT_ACTOR), resend=False)
        for _ in range(ticks):
            self.sim.wire.request(c.tick(), resend=False)
        self.sim.wire.request(c.stop_agent(AGENT_ACTOR), resend=False)
        return distance_2d_cm(speed_start, self.sim._read_location(AGENT_ACTOR))

    def tick_scale(self):
        """The central assumption: one tick advances the world by exactly tick_interval_s."""
        dt = self.sim.config.tick_interval_s
        ticks = round(10 / dt)
        distance = self._walk_distance(ticks)
        expected = self.sim.agent_speed * ticks * dt
        ratio = distance / expected
        self.report.extra["sim_time_ratio"] = ratio
        return verdict(0.8 < ratio < 1.2, f"walked {distance:.0f}cm in {ticks} ticks, expected {expected:.0f}cm at "
                       f"{self.sim.agent_speed:.0f}cm/s, ratio {ratio:.2f}. Near 1 means sim time follows ticks.")

    # 3. State
    def state_round_trip(self):
        state = self.result.final_state
        text = state.to_json()
        ok = PhysicalState.from_json(text) == state
        self.report.extra["example_prompt_text"] = state.to_prompt_text()
        print(state.to_prompt_text())
        return verdict(ok, f"{len(text)} bytes of JSON, {len(state.to_prompt_text())} chars of prompt text")

    def velocity(self):
        result = self.sim.step({"type": "move_forward"})
        velocity = result.final_state.agent.velocity
        self.sim.step({"type": "stop"})
        ratio = velocity.speed_cm_s / self.sim.agent_speed
        return verdict(0.5 < ratio < 1.5, f"{velocity.speed_cm_s:.0f}cm/s over a {velocity.window_s}s window "
                       f"({velocity.source}), asked for {self.sim.agent_speed:.0f}")

    def npcs_move(self):
        if not self.first.state.npcs:
            return "SKIP", "no NPCs configured"
        start = {n.id: n.pose.location for n in self.first.state.npcs}
        now = self.sim.read_state().npcs
        moved = {n.id: distance_2d_cm(start[n.id], n.pose.location) for n in now}
        return verdict(all(d > 50 for d in moved.values()), f"cm moved since reset: { {k: round(v) for k, v in moved.items()} }")

    def camera_rotation_order(self):
        """Setting a known rotation and reading it back settles the conflict at unrealcv.py:921 and :969."""
        cam = self.sim.camera_id
        self.sim.wire.request(c.set_camera_rotation(cam, 10, 20, 0), resend=False)
        self.sim.wire.request(c.tick(), resend=False)
        reply = self.sim.wire.request(c.get_camera_rotation(cam))
        rotation = self.sim._read_camera().extrinsics.rotation_deg
        self.sim.wire.request(c.set_camera_rotation(cam, 0, self.sim._read_pose(AGENT_ACTOR).rotation.yaw, 0), resend=False)
        self.sim._camera_overridden = True
        return verdict(abs(rotation.pitch - 10) < 1 and abs(rotation.yaw - 20) < 1, f"set pitch=10 yaw=20, reply was {reply!r}")

    def camera_rides(self):
        before = self.sim._read_camera().extrinsics.location_cm
        agent = self.sim._read_location(AGENT_ACTOR)
        offset = distance_2d_cm(before, agent)
        self.sim.step({"type": "step_forward", "duration_s": 3})
        after = self.sim._read_camera().extrinsics.location_cm
        carried = distance_2d_cm(before, after)
        moved = distance_2d_cm(agent, self.sim._read_location(AGENT_ACTOR))
        return verdict(offset < 500 and abs(carried - moved) < 100,
                       f"camera {self.sim.camera_id} starts {offset:.0f}cm from the agent, moved {carried:.0f}cm when the agent moved {moved:.0f}cm")

    def intrinsics(self):
        camera = self.sim._read_camera()
        k = camera.intrinsics
        expected = (k.width / 2) / math.tan(math.radians(k.fov_horizontal_deg) / 2)
        wanted = tuple(self.sim.config.resolution)
        return verdict(abs(k.fx - expected) < 1e-6 and (k.width, k.height) == wanted,
                       f"{k.width}x{k.height} fov {k.fov_horizontal_deg} gives fx={k.fx:.1f}, wanted size {wanted}")

    # 4. Renders
    def renders(self):
        renders = self.result.captures[-1].renders
        mean, colors = png_mean_and_colors(renders["rgb"].path)
        self.report.extra["example_renders"] = {m: r.path for m, r in renders.items()}
        sizes = {m: (r.width, r.height) for m, r in renders.items()}
        ok = mean > 1.0 and len(colors) > 1 and all(s == tuple(self.sim.config.resolution) for s in sizes.values())
        return verdict(ok, f"mean brightness {mean:.1f}, {len(colors)} colours, sizes {sizes}. Open {renders['rgb'].path}")

    def depth(self):
        stats = self.result.captures[-1].renders["depth"].depth_stats
        ok = stats["max"] > stats["min"] and stats["min"] >= 0
        return ("LOOK" if ok else "FAIL"), f"{stats}. Unit is unverified: a wall 10 m away should read about 1000 if cm."

    def mask_map(self):
        colors = self.sim.mask_colors
        path = self.result.captures[-1].renders["segmentation"].path
        _, present = png_mean_and_colors(path)
        mapped = {tuple(m.readback_rgb or m.assigned_rgb or ()): m.id for m in colors}
        visible = sorted(actor_id for rgb, actor_id in mapped.items() if rgb in present)
        readable = sum(m.readback_rgb is not None for m in colors)
        agree = sum(m.readback_rgb == m.assigned_rgb for m in colors)
        return ("LOOK" if not visible else "PASS"), (f"{readable}/{len(colors)} colours read back, {agree} match what we "
                                                     f"assigned, {len(present)} colours in frame, tracked actors visible: {visible}")

    # 5, 6. Actions
    def schema(self):
        rejected = 0
        for bad in ({"type": "fly"}, {"type": "rotate", "angle_deg": -1, "direction": "up"}, {"type": "pick_up", "target_id": "ghost"}):
            try:
                parse_action(bad, self.sim.targets)
            except ValueError:
                rejected += 1
        return verdict(rejected == 3, f"rejected {rejected}/3, {len(ACTION_CATALOG)} actions in the catalog")

    def move_to(self):
        here = self.sim._read_location(AGENT_ACTOR)
        goal = {"x": here.x + 800, "y": here.y + 400, "z": here.z}
        result = self.sim.step({"type": "move_to", "position": goal})
        left = distance_2d_cm(self.sim._read_location(AGENT_ACTOR), parse_action({"type": "move_to", "position": goal}).position)
        return verdict(result.outcome.status == "completed", f"{result.outcome.status}: {result.outcome.detail}, {left:.0f}cm left")

    def long_move(self):
        here = self.sim._read_location(AGENT_ACTOR)
        result = self.sim.step({"type": "move_to", "position": {"x": here.x + 20000, "y": here.y, "z": here.z}})
        first = result.outcome.status
        walked = distance_2d_cm(here, self.sim._read_location(AGENT_ACTOR))
        second = self.sim.step({"type": "continue"}).outcome.status
        self.sim.step({"type": "stop"})
        return verdict(first in ("in_progress", "failed") and walked > 100,
                       f"first step {first} after {walked:.0f}cm, then {second}. 'failed' means blocked by something real.")

    def look_at(self):
        """Project the target with our own camera maths. This tests pose and intrinsics together."""
        target = self.sim.targets and next((n for n in self.sim.read_state().npcs), None)
        if target is None:
            return "SKIP", "no NPC to look at"
        result = self.sim.step({"type": "look_at", "target_id": target.id})
        state = result.final_state
        npc = next(n for n in state.npcs if n.id == target.id)
        camera = state.camera
        pixel = project_point(npc.pose.location, camera.extrinsics.location_cm, camera.extrinsics.rotation_deg, camera.intrinsics)
        centre = (camera.intrinsics.cx, camera.intrinsics.cy)
        if pixel is None:
            return "FAIL", "target is behind the camera"
        off = math.hypot(pixel[0] - centre[0], pixel[1] - centre[1])
        yaw, pitch = heading_to(camera.extrinsics.location_cm, npc.pose.location)
        return ("PASS" if off < camera.intrinsics.width * 0.25 else "FAIL"), (
            f"target {off:.0f}px from centre, yaw {camera.extrinsics.rotation_deg.yaw:.1f} vs {yaw:.1f}, "
            f"pitch {camera.extrinsics.rotation_deg.pitch:.1f} vs {pitch:.1f}. Look for it in {result.captures[-1].renders['rgb'].path}")

    def camera_after_look(self):
        """Learn whether a set rotation sticks, then check the adapter copes either way."""
        self.sim.step({"type": "wait"})
        yaw_before = self.sim._read_camera().extrinsics.rotation_deg.yaw
        self.sim.wire.request(c.turn(AGENT_ACTOR, 90, "right"), resend=False)
        for _ in range(round(2 / self.sim.config.tick_interval_s)):
            self.sim.wire.request(c.tick(), resend=False)
        raw_turn = abs((self.sim._read_camera().extrinsics.rotation_deg.yaw - yaw_before + 180) % 360 - 180)
        sticks = "sticks: it did not follow the body" if raw_turn < 10 else "does not stick: it followed the body"
        self.report.extra["camera_rotation_sticks"] = raw_turn < 10
        state = self.sim.step({"type": "rotate", "angle_deg": 90, "direction": "right"}).final_state
        body, camera = state.agent.pose.rotation.yaw, state.camera.extrinsics.rotation_deg.yaw
        gap = abs((body - camera + 180) % 360 - 180)
        return verdict(gap < 10, f"a set camera rotation {sticks} (turned {raw_turn:.0f} degrees). "
                       f"With the adapter's realign, gap at capture is {gap:.1f} degrees.")

    def speak(self):
        before = self.sim._read_location(AGENT_ACTOR)
        result = self.sim.step({"type": "speak", "text": "checking the hearing radius"})
        event = result.speech_events[0]
        moved = distance_2d_cm(before, self.sim._read_location(AGENT_ACTOR))
        return verdict(result.outcome.mapping == "no_physics" and moved < 10, f"heard by {event.heard_by}, agent moved {moved:.1f}cm")

    def _objects_of_kind(self, kind):
        return [t for t, k in self.sim.targets.items() if k == kind]

    def _move_next_to(self, target_id):
        goal = self.sim._read_location(self.sim._actor_for(target_id))
        self.sim.wire.request(c.set_location(AGENT_ACTOR, goal.x + 60, goal.y, self.sim._read_location(AGENT_ACTOR).z), resend=False)
        self.sim.wire.request(c.tick(), resend=False)

    def interact_pick_up(self):
        objects = self._objects_of_kind("object")
        if not objects:
            return "SKIP", "no objects configured"
        self._move_next_to(objects[0])
        result = self.sim.step({"type": "interact", "target_id": objects[0]})
        held = result.final_state.agent.held_object
        status = result.outcome.status
        if held:
            self.sim.step({"type": "drop_object"})
        return verdict(status == "completed" and held == objects[0], f"{status}: {result.outcome.detail}, holding {held}")

    def native_actions(self):
        """Sent once each. PASS means accepted, not that the animation looked right."""
        replies = {}
        for action in ({"type": "stop"}, {"type": "set_speed", "speed_cm_s": 200}, {"type": "step_forward", "duration_s": 1},
                       {"type": "rotate", "angle_deg": 30, "direction": "left"}, {"type": "move_forward"},
                       {"type": "gesture", "kind": "wave"}, {"type": "stop_gesture"}):
            replies[action["type"]] = self.sim.step(action).outcome.status
        if any(s == "failed" for s in replies.values()):
            return "FAIL", str(replies)
        # SitDown names no seat, so with none nearby a refusal is the right answer, not a failure.
        sit = self.sim.step({"type": "sit_down"}).outcome.status
        stand = self.sim.step({"type": "stand_up"}).outcome.status if sit != "failed" else "not tried"
        replies.update(sit_down=sit, stand_up=stand)
        return ("PASS" if sit != "failed" else "LOOK"), f"{replies}. A failed sit_down may only mean no seat is nearby."

    def scooter(self):
        scooters = self._objects_of_kind("scooter")
        if not scooters:
            return "SKIP", "no scooter configured"
        self._move_next_to(scooters[0])
        on = self.sim.step({"type": "interact", "target_id": scooters[0]})
        camera = self.sim.camera_id
        driven = self.sim.step({"type": "drive", "throttle": 0.5})
        off = self.sim.step({"type": "get_off_scooter"})
        back = AGENT_ACTOR.lower() in self.sim._present()
        return verdict(on.outcome.status == "completed" and off.outcome.status == "completed" and back,
                       f"on={on.outcome.status} drive={driven.outcome.status} off={off.outcome.status} humanoid back={back}, "
                       f"camera {camera} while riding, then {self.sim.camera_id}")

    # 7. Time and weather
    def sun_read_back(self):
        if not self.sim.weather_available:
            return "FAIL", f"{WEATHER_ACTOR} is not in this package, so no time-of-day control"
        tod = self.sim.set_clock("12:00")
        weather = self.sim.read_weather()
        expected = sun_pitch_from_elevation(tod.sun_elevation_deg, self.sim.config.sun_pitch_sign)
        self.report.extra["level_weather_at_first_contact"] = self.sim.initial_weather.model_dump() if self.sim.initial_weather else None
        level = self.sim.initial_weather
        return verdict(abs(weather.sun_pitch_deg - expected) < 1, f"asked pitch {expected:.1f}, read {weather.sun_pitch_deg}, "
                       f"intensity {weather.sun_intensity}. Level started at pitch {level.sun_pitch_deg}, intensity {level.sun_intensity}, "
                       "unless an earlier run on this server changed it. Compare with max_sun_intensity.")

    def sun_sign(self):
        """Renders noon and midnight. If the sign is wrong, midnight is brighter, so flip sun_pitch_sign."""
        if not self.sim.weather_available:
            return "SKIP", "no weather manager"
        brightness = {}
        for clock in ("12:00", "00:00"):
            self.sim.set_clock(clock)
            self.sim.wire.request(c.tick(), resend=False)
            render = self.sim.render("rgb", 0)
            brightness[clock], _ = png_mean_and_colors(render.path)
            copy_to = self.out / f"sun_{clock.replace(':', '')}.png"
            copy_to.write_bytes(Path(render.path).read_bytes())
        self.sim.set_clock(self.sim.config.start_time)
        return verdict(brightness["12:00"] > brightness["00:00"] + 5, f"mean brightness {brightness}. Images saved in {self.out}")

    def weather(self):
        if not self.sim.weather_available:
            return "SKIP", "no weather manager"
        weather = self.sim.set_weather(fog=(10, 2000, 0.5), atmosphere=(0.3, 0.2))
        ok = weather.fog_density == 10 and weather.rayleigh == 0.3
        self.sim.set_weather(fog=(0, 0, 0), atmosphere=(1, 1))
        return verdict(ok, f"read fog {weather.fog_density}/{weather.fog_distance_cm}/{weather.fog_falloff}, atmosphere {weather.rayleigh}/{weather.mie}")

    # 8, 9. Restore and repeatability
    def checkpoint_file(self):
        self.checkpoint = self.sim.get_state()
        path = self.checkpoint.save(self.out / "checkpoint.json")
        return verdict(SimCheckpoint.load(path) == self.checkpoint, f"{path.stat().st_size} bytes at {path}")

    def restore(self):
        self.sim.step({"type": "move_forward"})
        report = self.sim.restore_state(self.checkpoint)
        self.report.extra["restore_report"] = report.model_dump()
        return verdict(report.ok, f"worst error {report.max_position_error_cm:.2f}cm, {report.position_errors_cm}")

    def replay_drift(self):
        """How repeatable is this engine? The number matters more than the pass mark."""
        def run():
            self.sim.restore_state(self.checkpoint)
            self.sim.step({"type": "step_forward", "duration_s": 5})
            return self.sim.read_state()
        a, b = run(), run()
        agent = distance_2d_cm(a.agent.pose.location, b.agent.pose.location)
        npc = max((distance_2d_cm(x.pose.location, y.pose.location) for x, y in zip(a.npcs, b.npcs)), default=0.0)
        self.report.extra["replay_drift_cm"] = {"agent": agent, "npc_worst": npc}
        return verdict(agent < 50 and npc < 100, f"after 30 sim-seconds, two replays differ by {agent:.2f}cm for the agent and {npc:.2f}cm for the worst NPC")

    # 10. Timing
    def timing(self):
        t = self.result.timing
        return verdict(t.stepping_s > 0 and t.state_capture_s > 0 and len(t.render_s) == 6 and t.total_s > 0,
                       f"total {t.total_s:.2f}s, stepping {t.stepping_s:.2f}s, renders {sum(t.render_s.values()):.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--fake", action="store_true", help="start the fake server in this process")
    parser.add_argument("--checklist", action="store_true", help="exercise every capability once")
    parser.add_argument("--tick-interval", type=float, default=0.1)
    parser.add_argument("--resolution", default="320x240")
    parser.add_argument("--map", default=None, help="switch to this map. Normally the launch script sets it.")
    parser.add_argument("--out", default=None, help="folder for renders and the report")
    args = parser.parse_args()

    server = None
    if args.fake:
        from kokopelli.loop.tests.fake_unrealcv import FakeUnrealCV
        print(FAKE_BANNER)
        server = FakeUnrealCV().start()
        args.host, args.port = "127.0.0.1", server.port

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="wmloop_gate_"))
    out.mkdir(parents=True, exist_ok=True)
    width, height = (int(v) for v in args.resolution.split("x"))
    settings = dict(host=args.host, port=args.port, tick_interval_s=args.tick_interval, resolution=(width, height),
                    out_dir=str(out / "renders"), map_path=args.map, run_id="checklist" if args.checklist else "one_tick")
    if args.fake:  # no real loading to wait for, and a coarser tick keeps it quick
        settings.update(init_settle_s=0, settle_s=0, reconnect_backoff_s=0.01, agent_position=(0.0, 0.0, 100.0))
        settings["objects"] = [{"id": "mug_0", "kind": "object", "asset": "/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C", "position": (290, -110, 100)},
                               {"id": "scooter_0", "kind": "scooter", "asset": "/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn.BP_Scooter_Pawn_C",
                                "position": (200, 200, 100), "actor": "GEN_BP_Scooter_0"}]

    report = Report(args.fake)
    report.extra["environment"] = {"python": sys.version, "platform": platform.platform(), "host": args.host, "port": args.port,
                                   "tick_interval_s": args.tick_interval, "resolution": args.resolution,
                                   "slurm_job": os.environ.get("SLURM_JOB_ID"), "gpu": os.environ.get("CUDA_VISIBLE_DEVICES")}
    try:
        import unrealcv
        report.extra["environment"]["unrealcv_client"] = unrealcv.__version__
    except ImportError:
        pass

    sim = SimWorldPhysics(SimWorldConfig(**settings))
    try:
        if args.checklist:
            Checklist(sim, report, out).run()
        else:
            one_tick(sim, report, out)
    except SimWorldError as e:
        report.add("run", "FAIL", f"{type(e).__name__}: {e}")
    finally:
        sim.close()
        if server:
            server.stop()
    report.summary()
    report.write(out / ("checklist_report.json" if args.checklist else "one_tick_report.json"))
    if args.fake:
        print("\nThat was the FAKE SERVER. Run it on PACE before believing any of it.")
    return 1 if report.failed else 0


def one_tick(sim: SimWorldPhysics, report: Report, out: Path) -> None:
    """The basic gate: reset, one real step with a real action, seconds per stage."""
    started = time.perf_counter()
    first = sim.reset()
    report.add("reset", "PASS", f"{time.perf_counter() - started:.2f}s, camera {sim.camera_id}")
    here = first.state.agent.pose.location
    result = sim.step({"type": "move_to", "position": {"x": here.x + 500, "y": here.y, "z": here.z}})
    print_timing(result)
    report.extra["timing"] = result.timing.model_dump()
    report.add("one step", "PASS" if result.ticks_advanced == sim.config.ticks_per_step else "FAIL",
               f"{result.ticks_advanced} ticks, action {result.outcome.status}, sim time {result.sim_time_s}s")
    print("\n" + result.final_state.to_prompt_text() + "\n")
    for capture in result.captures:
        for modality, render in capture.renders.items():
            print(f"  +{capture.offset_s:g}s {modality}: {render.path} sha256={render.sha256[:12]}")


if __name__ == "__main__":
    sys.exit(main())
