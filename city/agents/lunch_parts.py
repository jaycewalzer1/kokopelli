"""The lunch's small parts (city/agents/lunch_wm.py): bodies, the two-body world view, minds, the shared Qwen, the
side-by-side film, the controls, and the run's log/transcript/live.json/run.json writers (a mixin of Lunch)."""
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:   # imported through lunch_wm, which set up the path already, this is a no-op
    sys.path.insert(0, str(HERE))
import live  # noqa: E402
ROOT = live.ROOT
for _p in (ROOT, ROOT / "city" / "wm"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import controls as ctl  # noqa: E402  (city/wm/controls.py)
from live_wm import BLUR_DOWNUP, FAR_CM, NEAR_CM  # noqa: E402
from lunch_sim import FRIEND_ACTOR, TwoBodySim  # noqa: E402
from runtime.adapters.simworld import AGENT_ACTOR  # noqa: E402

HINTS = ("blur", "seg", "depth", "edge")


# ================================================================ the world as the two minds use it

@dataclass
class Body:
    xy: tuple
    yaw: float
    posture: str = "standing"
    held: str = None


class SimWorldPair:
    """Uniform view over TwoBodySim for the orchestrator (and the interface the dry test fakes):
    reset() / step({mind: sim_action}) -> ({mind: outcome}, {mind: [ {modality: path} per frame ]}),
    bodies(), npcs(), objects(), clock, sim_time_s, halt()."""

    def __init__(self, cfg, first, second, second_xy, second_yaw, sim_class=None):
        # lunch_wm.make_world passes lunch_wm.TwoBodySim, looked up when it runs: the bodies demo replaces that name
        self.first, self.second = first, second
        self.sim = (sim_class or TwoBodySim)(cfg, friend_id=second,
                                             friend_position=(second_xy[0] * 100, second_xy[1] * 100, 200),
                                             friend_yaw=second_yaw)
        self.state = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.sim.close()

    def _frames(self, captures):
        return {self.first: [{m: r.path for m, r in cap.renders.items()} for cap in captures],
                self.second: [{m: r.path for m, r in rs.items()} for rs in self.sim.friend_captures]}

    def _read(self, state):
        self.state = state
        self._friend = self.sim.friend_pose()

    def reset(self):
        cap = self.sim.reset(seed=0)
        self._read(cap.state)
        return self._frames([cap])

    def _translate(self, a):
        """The second body's targets: the first mind's id means the adapter's agent."""
        a = dict(a)
        if a.get("target_id") == self.first:
            a["target_id"] = "agent"
        return a

    def step(self, actions):
        self.sim.friend_action = self._translate(actions.get(self.second, {"type": "continue"}))
        result = self.sim.step(actions.get(self.first, {"type": "continue"}))
        self._read(result.final_state)
        o = result.outcome
        first = {"status": o.status, "detail": o.detail, "phase": o.task.phase if o.task else None}
        return {self.first: first, self.second: dict(self.sim.friend_result)}, self._frames(result.captures)

    @property
    def clock(self):
        return self.state.time_of_day.clock

    @property
    def sim_time_s(self):
        return self.state.sim_time_s

    def bodies(self):
        a, f = self.state.agent, self._friend
        return {self.first: Body(live.m(a.pose.location), a.pose.rotation.yaw, a.posture, a.held_object),
                self.second: Body(live.m(f.location), f.rotation.yaw, "standing", self.sim.friend_held)}

    def npcs(self):
        return [(n.id, live.m(n.pose.location)) for n in self.state.npcs]

    def objects(self):
        out = []
        for o in self.state.objects:
            if not o.pose:
                continue
            held = self.second if o.id == self.sim.friend_held else (self.first if o.held_by else None)
            out.append((o.id, live.m(o.pose.location), held))
        return out

    def halt(self):
        """Stop everyone before the adapter un-pauses the game (live.Life.halt explains why)."""
        names = [f"vbp {s.actor_name} StopPedestrian" for s in self.sim.config.npcs or []]
        names += [f"vbp {AGENT_ACTOR} StopAgent", f"vbp {FRIEND_ACTOR} StopAgent"]
        for cmd in names:
            try:
                self.sim.wire.request(cmd, resend=False)
            except Exception as e:
                print(f"(could not send {cmd}: {e})")


# ================================================================ minds

@dataclass
class Mind:
    id: str
    name: str
    who: str
    situation: str
    other: str = ""
    last: str = ""
    diary: list = field(default_factory=list)
    heard: list = field(default_factory=list)
    recent: list = field(default_factory=list)
    route: list = field(default_factory=list)
    goal_place: str = None
    approaching: str = None
    new_leg: bool = False
    blocked_count: int = 0
    awaiting: int = None        # steps since this mind spoke to someone and got no answer; None = not waiting
    pending: str = None         # why this mind should decide at the next chance
    met: set = field(default_factory=set)
    seen: str = None
    k_seen: int = 0
    last_thought: str = ""
    last_action: dict = None
    decisions: int = 0
    talk: list = field(default_factory=list)    # --fixes memory: every line said near this mind, both voices
    decided_frame: str = None   # --decide-on-change: the frame this mind last decided from
    quiet: int = 0              # --decide-on-change: steps idle without a decision

    @property
    def idle(self):
        return not self.route and not self.approaching


class QwenBrain:
    """One Qwen3-VL for every mind: each call carries that mind's own prompt and picture."""

    def __init__(self, weights):
        self.weights = Path(weights)

    def ask(self, prompt, image):
        from core import llm_model
        llm_model.LLM_MODEL_WEIGHTS = self.weights
        try:
            raw = llm_model.ask(prompt, [image], max_tokens=300, temperature=0.4)
        except RuntimeError:
            llm_model.unload()   # "Failed to create Metal shared event" next to Unreal (live.py): reload once
            raw = llm_model.ask(prompt, [image], max_tokens=300, temperature=0.4)
        try:
            import mlx.core as mx
            mx.clear_cache()
        except ImportError:
            pass
        return raw

    def unload(self):
        from core import llm_model
        llm_model.unload()


class SideBySide:
    """Pairs the two films frame by frame (holding back whichever is ahead) into one labelled side-by-side film."""

    def __init__(self, film, names, gap=4):
        import numpy as np
        self.film, self.names, self.gap, self.np = film, names, gap, np
        self.buf = {n: None for n in names}

    def add(self, name, frames):
        np = self.np
        self.buf[name] = frames if self.buf[name] is None else np.concatenate([self.buf[name], frames])

    def flush(self):
        np = self.np
        if any(b is None for b in self.buf.values()):
            return 0
        n = min(len(b) for b in self.buf.values())
        if not n:
            return 0
        left, right = (self.buf[k][:n] for k in self.names)
        gap = np.full((n, left.shape[1], self.gap, 3), 20, np.uint8)
        both = np.concatenate([left, gap, right], axis=2)
        for k, label in ((0, self.names[0]), (left.shape[2] + self.gap, self.names[1])):
            for f in both:
                ctl.cv2.putText(f, label, (k + 6, 16), ctl.cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, ctl.cv2.LINE_AA)
        for k in self.names:
            self.buf[k] = self.buf[k][n:]
        self.film.add(both)
        return n


def controls_for(frames, size, palette):
    """{modality: path} per frame -> the 4 controls (live_wm.py's conventions) and the sim RGB, all at `size`."""
    import numpy as np
    out = {h: [] for h in HINTS}
    rgbs = []
    for fr in frames:
        rgb = np.array(ctl.Image.open(fr["rgb"]).convert("RGB"))
        small = ctl.resize_rgb(rgb, size)
        depth = np.load(fr["depth"]).astype(np.float32)
        seg = np.array(ctl.Image.open(fr["segmentation"]).convert("RGB"))
        ids = ctl.refined_ids(seg, rgb)
        out["blur"].append(ctl.blur(small, downup=BLUR_DOWNUP)[0])
        out["seg"].append(ctl.cv2.resize(palette.paint(ids), size, interpolation=ctl.cv2.INTER_NEAREST))
        out["depth"].append(ctl.depth_inverse_frame(depth, NEAR_CM, FAR_CM, size))
        out["edge"].append(ctl.edge(small))
        rgbs.append(small)
    return {h: np.stack(v) for h, v in out.items()}, np.stack(rgbs)


# ================================================================ the run's files (Lunch's logging and sidecars)

class LunchRecord:
    """events.jsonl, transcript.md, live.json and run.json for Lunch (needs self.out, self.events, self.transcript,
    self.minds, self.world, self.nav, self.wm, self.args, self.sim_t, self.step_no, self.running, self.steps_done)."""

    # --- logging
    def log(self, kind, **data):
        self.events.write(json.dumps({"t": round(self.sim_t, 1), "step": self.step_no, "kind": kind, **data}) + "\n")
        self.events.flush()

    def say(self, md):
        print(md, flush=True)
        self.transcript.write(md + "\n")
        self.transcript.flush()

    # --- files for people and the dev panel
    def snapshot(self):
        try:
            bodies = self.world.bodies()
        except Exception:
            bodies = {}
        first = next(iter(self.minds.values()))
        snap = {"run": self.out.name, "updated": datetime.now().isoformat(timespec="seconds"), "running": self.running,
                "who": first.who, "situation": first.situation, "vision": "world_model", "step": self.step_no,
                "last_thought": first.last_thought, "last_action": first.last_action, "last_result": first.last,
                "diary": first.diary[-8:], "heard": first.heard[-4:],
                "frame": f"frames/{first.id}/live.png" if first.seen else None, "agents": {}}
        for k, mind in self.minds.items():
            if mind.seen:
                tmp = self.out / "frames" / k / "live.tmp.png"
                shutil.copy(mind.seen, tmp)
                tmp.replace(self.out / "frames" / k / "live.png")
            b = bodies.get(k)
            snap["agents"][k] = {"name": mind.name, "who": mind.who, "last_thought": mind.last_thought,
                                 "last_action": mind.last_action, "last_result": mind.last, "frame": f"frames/{k}/live.png",
                                 "x_m": round(b.xy[0], 2) if b else None, "y_m": round(b.xy[1], 2) if b else None,
                                 "yaw": round(b.yaw, 1) if b else None, "route": [[round(x, 1), round(y, 1)] for x, y in mind.route],
                                 "goal": mind.goal_place}
        if bodies:
            b = bodies[first.id]
            snap["agent"] = {"x_m": round(b.xy[0], 2), "y_m": round(b.xy[1], 2), "yaw": round(b.yaw, 1), "carrying": b.held,
                             "place": self.nav.place_at(b.xy)}
            other = self.minds[first.other]
            ob = bodies[other.id]
            snap["npcs"] = [{"id": other.id, "name": other.name, "role": "neighbour (thinking agent)",
                             "x_m": round(ob.xy[0], 2), "y_m": round(ob.xy[1], 2)}]
            snap["route"], snap["goal"] = [[round(x, 1), round(y, 1)] for x, y in first.route], first.goal_place
            try:
                snap["clock"] = self.world.clock
            except Exception:
                pass
        path = self.out / "live.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, indent=1))
        tmp.replace(path)

    def write_sidecar(self, final):
        a = self.args
        meta = {"model": "Cosmos3-Nano-Sim-Transfer", "world_model": "Cosmos3-Nano-Sim-Transfer",
                "agent_model": Path(a.weights).name, "agent_model_path": str(a.weights),
                "fake_world_model": bool(getattr(a, "fake_wm", False)),
                "runtime": "world_stream_multi.py (one MLX worker, one set of weights, one causal rollout per agent) + "
                           "city/agents/lunch_wm.py; bodies and cameras from SimWorld via TwoBodySim",
                "worker": getattr(self.wm, "hello", None), "streams": getattr(self.wm, "info", None),
                "controls": {"blur": f"downup {BLUR_DOWNUP} (v2 high)", "seg": "SimWorld masks x material class",
                             "depth": f"inverse depth, near {NEAR_CM} cm, far {FAR_CM} cm", "edge": "Canny 100/200",
                             "weights": "0.25 each"},
                "wm_prompt": a.wm_prompt, "size": a.size, "fps": a.fps, "seeds": {k: a.seed + i for i, k in enumerate(self.minds)},
                "denoise_steps": 4, "window": a.window, "sink": a.sink, "quantize": a.quantize,
                "sim_steps": a.steps, "step_seconds": a.step_s, "clock": a.clock, "meet": a.meet,
                "agents": {k: {"name": m.name, "who": m.who, "situation": m.situation, "decisions": m.decisions}
                           for k, m in self.minds.items()},
                "finished": final, "steps_done": self.steps_done,
                "switches": {"fixes": list(getattr(a, "fixes", None) or []), "decide_on_change": bool(getattr(a, "decide_on_change", False)),
                             "view_prompts": bool(getattr(a, "view_prompts", False)), "life": getattr(a, "life", None)},
                "films": {"side_by_side": "film/side_by_side.mp4", **{k: f"film/{k}.mp4" for k in self.minds}}}
        from core.manifest import manifest   # commit, dirty, weight hashes: see core/manifest.py
        fake_wm, fake_brain = meta["fake_world_model"], not isinstance(getattr(self, "brain", None), QwenBrain)
        meta["manifest"] = manifest(
            weights={"agent": None if fake_brain else a.weights,
                     "world_model": None if fake_wm else ROOT / "models" / meta["world_model"]},
            seed=meta["seeds"], prompt=a.wm_prompt, quantize=a.quantize, controls=meta["controls"], resolution=a.size,
            fake=fake_wm or fake_brain, fake_world_model=fake_wm, fake_brain=fake_brain,
            brain=type(getattr(self, "brain", None)).__name__)
        (self.out / "run.json").write_text(json.dumps(meta, indent=1, default=str))
        if final:
            for name in ["side_by_side", *self.minds]:
                film = self.out / "film" / f"{name}.mp4"
                if film.exists():
                    film.with_name(film.name + ".json").write_text(json.dumps({**meta, "film": name}, indent=1, default=str))


def place_or_point(nav, text):
    if text in nav.doors:
        return tuple(nav.doors[text])
    x, y = (float(v) for v in text.split(","))
    return (x, y)


def open_streams(wm, args, ids):
    planned = int(args.steps * args.step_s * args.fps) + 1
    for i, k in enumerate(ids):
        wm.open(k, args.wm_prompt, size=args.size, fps=args.fps, seed=args.seed + i, window=args.window, sink=args.sink,
                planned_frames=planned)
