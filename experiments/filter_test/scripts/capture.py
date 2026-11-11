"""Record the one 10-second SimWorld clip every filter in this test is run on: rgb, depth and segmentation at 30 fps.

    .venv/bin/python -m experiments.filter_test.scripts.capture              # needs the packaged server on port 9001, nobody else connected
    .venv/bin/python -m experiments.filter_test.scripts.capture --labels labels.json   # also the object-label pass (kokopelli/wm/labels.py)

The camera is a walking head (head.py): it looks around, bobs with each step, and holds steady on what it looks at.
--still turns that off and leaves SimWorld's own camera, which is locked to the body.

No model is loaded. The walk replays a decision Qwen already made in a city agent run (its first "go_to", from
out/city_agents/<run>/events.jsonl), so the clip comes out the same every time: same route, no NPCs, a fixed clock.

One sim step of 301 ticks at 1/30 s, capturing on ticks 2-301. Tick 1 can't be captured: the adapter measures velocity
over the tick before a capture, so the first capture has to come at least two ticks in.
"""
import argparse
import json
import math
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from experiments.filter_test.scripts.head import Head  # noqa: E402
from kokopelli.agents import live  # noqa: E402, F401  (imported for its side effect: sets up the unrealcv client, the same way the city agent does)
from kokopelli.agents.navmap import NavMap  # noqa: E402
from kokopelli.loop.adapters.simworld import AGENT_ACTOR, SimWorldConfig, SimWorldPhysics  # noqa: E402
from kokopelli.wm import labels as object_labels  # noqa: E402

OUT = ROOT / "out" / "filter_test" / "test_clip"
SOURCE_RUN = ROOT / "out" / "city_agents" / "20261106-115650"
FPS, FRAMES = 30, 300
TICK = 1 / FPS
MIN_LEG_M = 15.0


class Recorder(SimWorldPhysics):
    """Names each render by its tick (the adapter names them by whole seconds, so 30 frames a second would overwrite each other),
    and moves the camera like a head one tick before each capture.

    Measured on the packaged server: a camera location set here is world coordinates, and the camera then stays attached to the
    body at that offset. So placing it from the body's position before the tick puts it in the right place after the tick."""

    head = None
    moves = []

    def render(self, modality, offset_s):
        return super().render(modality, self.tick_count)

    def _before_capture(self, capture_time_s):
        super()._before_capture(capture_time_s)
        if not self.head:
            return
        pose = self._read_pose(AGENT_ACTOR)
        agent = (pose.location.x, pose.location.y, pose.location.z)
        (x, y, z), (pitch, yaw, roll), parts = self.head.update(agent, pose.rotation.yaw)
        self.wire.request(f"vset /camera/{self.camera_id}/location {x:.2f} {y:.2f} {z:.2f}", resend=False)
        self.wire.request(f"vset /camera/{self.camera_id}/rotation {pitch:.3f} {yaw:.3f} {roll:.3f}", resend=False)
        self.moves.append({"tick": self.tick_count + 1, "camera": [round(v, 2) for v in (x, y, z)],
                           "rotation": [round(v, 3) for v in (pitch, yaw, roll)], **parts})


def qwen_choice(run):
    """The first place Qwen chose to walk to in that run, and where it started."""
    for line in (run / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "act" and event["action"].get("type") == "go_to":
            return event["action"]["place"], event
    raise SystemExit(f"no go_to in {run}")


def first_long_leg(nav, start, place):
    """The first straight stretch of Qwen's route long enough to fill 10 s of walking."""
    points = [start] + nav.route(start, nav.doors[place])
    for a, b in zip(points, points[1:], strict=False):
        if math.dist(a, b) >= MIN_LEG_M:
            return a, b
    raise SystemExit(f"no stretch of {MIN_LEG_M} m on the route to {place}")


# Where to walk. "garden" replays Qwen's first route of a city run; "bridge" is a spot the user picked: the Moss-Commons sky
# bridge, 17.5 m up, walking east from Moss's roof toward the Commons tower with the library's dome ahead-right.
# Glances are (from second, yaw degrees right, pitch degrees up), relative to the walking direction.
PLACES = {
    "bridge": {"start": (356.0, 115.0), "goal": (380.0, 115.0), "deck_m": 17.5, "about": "Moss-Commons sky bridge, toward the dome",
               "glances": [(0.0, 0, 2), (1.6, -38, -6), (2.9, 4, 0), (3.8, 42, -14), (6.0, 58, -8), (8.4, 20, 3), (9.3, 6, 4)]},
    "garden": {"about": "Fern Court garden path, Qwen's route to Rise Bakery"},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--clock", default="14:00")
    ap.add_argument("--speed", type=float, default=1.6, help="walking speed, m/s (the city agent's default)")
    ap.add_argument("--still", action="store_true", help="no head motion: SimWorld's own camera, locked to the body")
    ap.add_argument("--place", choices=sorted(PLACES), default="bridge")
    ap.add_argument("--labels", help="labels.json: its actors get mask colours, and labels/NNNN.png + labels_meta.json are written")
    args = ap.parse_args()
    labels = object_labels.load(args.labels) if args.labels else []   # read before the old clip is removed, so a bad file stops here
    width, height = map(int, args.size.split("x"))

    spot = PLACES[args.place]
    if args.place == "garden":
        nav = NavMap()
        place, event = qwen_choice(SOURCE_RUN)
        a, b = first_long_leg(nav, nav.doors["fern_common"], place)
        source = {"chosen_by": "qwen", "run": SOURCE_RUN.name, "event": event, "place": place}
    else:
        a, b = spot["start"], spot["goal"]
        source = {"chosen_by": "user", "place": args.place}
    floor = spot.get("deck_m", 0.0) * 100
    yaw = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))  # Unreal: yaw 0 is +X, 90 is +Y

    if OUT.exists():
        shutil.rmtree(OUT)
    raw = OUT / "raw"
    cfg = SimWorldConfig(
        port=args.port, tick_interval_s=TICK, step_seconds=(FRAMES + 1) * TICK, velocity_window_s=TICK,
        capture_offsets_s=tuple(k * TICK for k in range(2, FRAMES + 2)), resolution=(width, height), fov_deg=90,
        modalities=("rgb", "depth", "segmentation"), out_dir=str(raw), run_id="clip", npcs=[], objects=[],
        agent_position=(a[0] * 100, a[1] * 100, floor + 200), agent_yaw=yaw, agent_speed_cm_s=args.speed * 100,
        spawn_weather_manager=False, start_time=args.clock, seed=0, label_actors=tuple(e["actor"] for e in labels))

    with Recorder(cfg) as sim:
        sim.head = None if args.still else Head(dt=TICK, **({"glances": spot["glances"]} if "glances" in spot else {}))
        sim.moves = []
        try:
            sim.reset(seed=0)
            standing = sim._read_pose(AGENT_ACTOR).location.z
            if floor and standing < floor:
                raise SystemExit(f"the agent fell through to z={standing:.0f} cm instead of standing on the deck at {floor:.0f}")
            result = sim.step({"type": "move_to", "position": {"x": b[0] * 100, "y": b[1] * 100, "z": floor + 100},
                               "arrival_radius_cm": 120})
        finally:
            sim.wire.request("vbp GEN_BP_Humanoid_0 StopAgent", resend=False)  # see kokopelli/loop/HANDOFF.md, last section

    for k, cap in enumerate(result.captures):
        for modality, render in cap.renders.items():
            folder = OUT / modality
            folder.mkdir(parents=True, exist_ok=True)
            Path(render.path).replace(folder / f"{k:04d}.{render.format}")
    shutil.rmtree(raw)
    poses = [{"frame": k, "tick": cap.tick_count, "sim_time_s": cap.sim_time_s, "state": cap.state.model_dump(mode="json")}
             for k, cap in enumerate(result.captures)]
    (OUT / "poses.jsonl").write_text("".join(json.dumps(p) + "\n" for p in poses))
    if sim.moves:
        (OUT / "head.jsonl").write_text("".join(json.dumps(move) + "\n" for move in sim.moves))
    (OUT / "capture.json").write_text(json.dumps({
        "fps": FPS, "frames": len(result.captures), "size": [width, height], "fov_deg": 90, "clock": args.clock,
        "speed_m_s": args.speed, "head": "still" if args.still else "head.py", "server_port": args.port, "camera_id": sim.camera_id, "warnings": sim.warnings,
        "place": args.place, "place_about": spot["about"], "route_source": source, "leg_m": [list(a), list(b)], "floor_cm": floor,
        "outcome": result.outcome.model_dump(mode="json"), "depth_units": "cm, float32; sky clamps near 65504",
        "mask_colors": [m.model_dump() for m in sim.mask_colors],
    }, indent=1))
    if labels:
        meta = object_labels.build_pass(OUT, labels, object_labels.capture_colors({"mask_colors": [m.model_dump() for m in sim.mask_colors]}),
                                        args.labels)
        for warning in meta["warnings"]:
            print(f"labels: {warning}")
    print(f"{len(result.captures)} frames to {OUT}, outcome {result.outcome.status}: {result.outcome.detail}")


if __name__ == "__main__":
    main()
