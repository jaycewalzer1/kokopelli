"""Two thinking people meet for lunch inside the world model: each sees only what Cosmos3-Nano-Sim-Transfer paints.

    city/agents/run_wm_lunch.sh --minutes 5                       # the real thing (queue it; see AGENTS.md)
    .venv/bin/python city/agents/lunch_wm.py --port 9001 --minutes 5
    .venv/bin/python city/agents/lunch_wm.py --fake-wm ...        # SimWorld for real, world model faked (no weights)

Mara (live.DEFAULT_WHO) and her neighbour Iris agreed to meet at The Kettle for lunch and then sit and talk. Both are the
same Qwen3-VL (loaded once), each asked with its own prompt, memory and picture.

Bodies and eyes (SimWorld, one server, one connection):
  - Mara is the adapter's own agent, GEN_BP_Humanoid_0, with its head camera.
  - Iris is a second Base_User_Agent humanoid, GEN_BP_Humanoid_1, spawned right after Mara. The server gives every
    Base_User_Agent its own SimCV camera at eye height (mac_server SPEC 3.1, SWHumanoid.cpp), so Iris has real eyes
    that move with her body. TwoBodySim walks her with the adapter's own waypoint Mover and the same blueprint calls
    (MoveForward / TurnAround / StopAgent / PickUp / DropOff) and renders her camera at every capture tick.
Perception: per step the sim advances STEP seconds and captures both cameras at video rate (rgb, depth, masks). Each
agent's frames become the 4 controls (live_wm.py's conventions) and go to that agent's own stream in ONE world-model
worker (world_stream_multi.py: one set of weights, one causal rollout per agent kept for the whole run). Qwen decides
from the newest painted frame of its own film. The sim's render is never shown to it.
Words given to an agent: places it knows, what it heard, who is within talking distance (10 m) and what is within reach.

Conversation: speech has no physics. When someone speaks, every agent within 10 m hears it at once ("What you heard")
and gets a decision point in the same step, after the speaker. Someone who has just spoken waits for an answer (no
decision of their own) for up to PATIENCE steps. That gives an alternating back-and-forth: each step one line, then the
reply. People keep walking while they talk; an idle speaker or listener turns to face the other.

Writes out/city_agents/<stamp>_lunch/: events.jsonl, transcript.md (both voices), frames/<agent>/, film/ (mara.mp4,
iris.mp4, side_by_side.mp4, and the sim's own renders sim_*.mp4 for comparison only), controls/<agent>/, wm/ (worker
log), live.json, run.json (+ a .json sidecar next to every film) naming every model.
"""
import argparse
import json
import math
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live  # noqa: E402  (borrows unrealcv, puts the wm-agent-loop worktree on the path)
from live import Cast, parse_reply, rough, bearing, compass  # noqa: E402
from live_wm import BLUR_DOWNUP, FAR_CM, NEAR_CM, REACH_M, Film  # noqa: E402
from navmap import NavMap  # noqa: E402

ROOT = live.ROOT
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "city" / "wm"))
import controls as ctl  # noqa: E402  (city/wm/controls.py)
from runtime.adapters import simworld_commands as c  # noqa: E402
from runtime.adapters.simworld import (AGENT_ACTOR, AGENT_ASSET, MUG_ASSET, NpcSpec, SimWorldConfig,  # noqa: E402
                                       SimWorldPhysics, SpawnSpec)
from runtime.adapters.simworld_control import MoverIO  # noqa: E402
from runtime.adapters.simworld_math import angle_delta, distance_cm, heading_to  # noqa: E402
from runtime.physics import Vec3  # noqa: E402

HEAR_M = live.HEAR_M
# Qwen sometimes put its words in "diary" with no "text" (bodies demo); these show it the exact shape.
FORMAT_NOTE = ('\nAlways write "action" as an object with its fields inside it. To speak, put your exact words in "text": '
               '{"type": "say", "text": "Iris! There you are."}. The diary is a private note, nobody hears it.')
RETRY_SHAPE = ('{"thought": "<one sentence>", "action": {"type": "say", "text": "<the words you say out loud>"}, '
               '"diary": "<optional note>"}')
PATIENCE = 2           # steps a speaker waits for an answer before deciding again
FORGET_M = 25.0        # walk this far apart and running into each other again counts as meeting again
FRIEND_ACTOR = "GEN_BP_Humanoid_1"
HINTS = ("blur", "seg", "depth", "edge")

IRIS_WHO = ("You are Iris, 41, a beekeeper who keeps the hives on the Fern Court roofs and fixes bikes at Clover Works "
            "two days a week. You live in Fern Court, two doors from Mara. You're dry-humoured and practical, and you "
            "notice weather, insects and anything with a broken spoke.")
MARA_SITUATION = ("It's Saturday, just before half past twelve. Yesterday you and your neighbour Iris agreed to meet at "
                  "The Kettle (kettle_cafe) for lunch today, get something to eat together, then sit and catch up. You "
                  "haven't really talked in two weeks: you want to hear how her bees are doing, and to tell her that "
                  "Loom & Thread asked you to design the banners for the harvest fair. Iris is 41, a beekeeper, about "
                  "your height, usually in a canvas jacket.")
IRIS_SITUATION = ("It's Saturday, just before half past twelve. You just came out of Rise Bakery with a loaf for the "
                  "weekend. Yesterday you and your neighbour Mara agreed to meet at The Kettle (kettle_cafe) for lunch "
                  "today, get something to eat together, then sit and talk. You have news: one of your hives swarmed on "
                  "Thursday and you caught the swarm in the Fern Court plum tree. Mara is 34, a textile designer, "
                  "warm and chatty.")
LUNCH_TOPIC = {"lunch|soup|sandwich|eat|food|hungry|menu": "Lunch today is nettle soup with rye, or a halloumi flatbread. "
               "Two bowls are on the end of the bar, help yourselves, and grab the table by the window."}
WM_PROMPT = ("First-person view of someone walking through a sunny solarpunk village around midday, at eye level. "
             "Timber apartment buildings with planted balconies, vines and green roofs line paved streets and footpaths; "
             "flowering shrubs, fruit trees and community gardens; solar panels and copper domes on the roofs; neighbours "
             "walking, chatting and carrying things; a cafe with tables outside; wooded hills on the horizon, deep blue sky "
             "with white clouds. Live-action video, natural light, realistic materials, steady handheld camera.")


# ================================================================ the sim: two humanoids, two head cameras

class TwoBodySim(SimWorldPhysics):
    """The adapter, plus a second humanoid ("the friend") with its own head camera, driven like the agent.

    Set `friend_action` before step(); it takes the same dicts as the agent's actions, restricted to
    continue / wait / move_to (position or target_id) / look_at (target_id or position) / interact / drop_object.
    After a step, `friend_captures` holds one {modality: RenderFile} per capture tick and `friend_result` its outcome.
    Not supported for the friend: checkpoint/restore, sitting, scooters, vehicles, gestures."""

    def __init__(self, config, friend_id="friend", friend_position=(0.0, 0.0, 200.0), friend_yaw=0.0):
        self.friend_id, self.friend_position, self.friend_yaw = friend_id, tuple(friend_position), friend_yaw
        self.friend_camera_id = None
        self.friend_action = None
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
            status = {"arrived": "completed", "blocked": "failed"}.get(phase, "in_progress")
            detail = f"move_to {phase}, {mover.last_distance_cm or 0:.0f}cm from the goal"
        self.friend_result = {"status": status, "detail": detail, "phase": phase}
        return outcome

    def friend_pose(self):
        return self._read_pose(FRIEND_ACTOR)


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

    def __init__(self, cfg, first, second, second_xy, second_yaw):
        self.first, self.second = first, second
        self.sim = TwoBodySim(cfg, friend_id=second, friend_position=(second_xy[0] * 100, second_xy[1] * 100, 200),
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

    @property
    def idle(self):
        return not self.route and not self.approaching


class QwenBrain:
    """One Qwen3-VL for every mind: each call carries that mind's own prompt and picture."""

    def __init__(self, weights):
        self.weights = Path(weights)

    def ask(self, prompt, image):
        import llm_model
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
        import llm_model
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


# ================================================================ the lunch

class Lunch:
    def __init__(self, args, world, wm, brain, out=None, nav=None, cast=None):
        self.args, self.world, self.wm, self.brain = args, world, wm, brain
        self.nav = nav or NavMap()
        self.cast = cast
        self.size = tuple(int(n) for n in args.size.split("x"))
        self.out = Path(out or ROOT / "out" / "city_agents" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "_lunch"))
        self.out.mkdir(parents=True, exist_ok=True)
        a, b = args.first, args.second
        self.minds = {a["id"]: Mind(a["id"], a["name"], a["who"], a["situation"], other=b["id"]),
                      b["id"]: Mind(b["id"], b["name"], b["who"], b["situation"], other=a["id"])}
        for mind in self.minds.values():
            mind.last = a["start_note"] if mind.id == a["id"] else b["start_note"]
            (self.out / "frames" / mind.id).mkdir(parents=True, exist_ok=True)
        self.events = (self.out / "events.jsonl").open("a")
        self.transcript = (self.out / "transcript.md").open("a")
        fps = args.fps
        # live_wm.Film writes numbered segments into its folder and the joined film next to that folder
        parts = self.out / "film" / "parts"
        self.films = {k: Film(parts, self.size, fps, k) for k in self.minds}
        self.sim_films = {k: Film(parts, self.size, fps, f"sim_{k}") for k in self.minds}
        self.ctl_films = {k: {h: Film(self.out / "controls" / k / "parts", self.size, fps, h) for h in HINTS} for k in self.minds}
        sbs_size = (2 * self.size[0] + 4, self.size[1])
        self.side = SideBySide(Film(parts, sbs_size, fps, "side_by_side"), [m.name for m in self.minds.values()])
        self.steps_done = 0
        self.palette = ctl.Palette()
        self.sim_t, self.step_no, self.running = 0.0, 0, True
        self.wm_info = {}

    # --- logging
    def log(self, kind, **data):
        self.events.write(json.dumps({"t": round(self.sim_t, 1), "step": self.step_no, "kind": kind, **data}) + "\n")
        self.events.flush()

    def say(self, md):
        print(md, flush=True)
        self.transcript.write(md + "\n")
        self.transcript.flush()

    # --- perception
    def perceive(self, frames):
        """Both agents' new captures -> controls -> their own world-model stream -> films. Returns nothing; each
        mind's `seen` is its newest painted frame."""
        self.brain.unload()   # Qwen out of the way while the world model paints
        painted_any = {}
        for k, mind in self.minds.items():
            if not frames.get(k):
                continue
            t0 = time.time()
            controls, rgb = controls_for(frames[k], self.size, self.palette)
            t_ctl = time.time() - t0
            painted = self.wm.push(k, controls)
            self.films[k].add(painted)
            self.sim_films[k].add(rgb)
            for h, f in self.ctl_films[k].items():
                f.add(controls[h])
            self.side.add(self.minds[k].name, painted)
            for fr in frames[k]:   # raw captures are big; the controls keep what matters
                for p in fr.values():
                    Path(p).unlink(missing_ok=True)
            last = getattr(self.wm, "last", {}).get(k, {})
            self.log("painted", mind=k, frames_in=len(rgb), frames_out=len(painted), controls_s=round(t_ctl, 1),
                     total_s=round(time.time() - t0, 1), **{x: last.get(x) for x in ("latents", "s_per_latent", "peak_gb", "weight_loads")})
            if len(painted):
                mind.k_seen += 1
                path = self.out / "frames" / k / f"seen_{mind.k_seen:04d}.png"
                ctl.Image.fromarray(painted[-1]).save(path)
                mind.seen = str(path)
            painted_any[k] = len(painted)
        self.side.flush()
        return painted_any

    # --- what a mind is told
    def describe(self, mind):
        bodies = self.world.bodies()
        me = bodies[mind.id]
        here, near = self.nav.place_at(me.xy), self.nav.place_at(me.xy, 40.0)
        where = (f"at {self.nav.places[here]['name']}" if here else
                 f"out in the streets near {self.nav.places[near]['name']}" if near else "out in the streets")
        lines = [f"Time: {self.world.clock[:5]}.", f"You are {where}, {me.posture}, carrying {me.held or 'nothing'}."]
        if mind.route:
            lines.append(f"You are walking to {self.nav.places[mind.goal_place]['name']}, "
                         f"{rough(self.nav.length(me.xy, mind.route))} to go.")
        close = []
        other = self.minds[mind.other]
        d = math.dist(me.xy, bodies[other.id].xy)
        if d <= HEAR_M:
            close.append(f"- {other.id}: {other.name}, your neighbour, {rough(d)} {bearing(me.xy, me.yaw, bodies[other.id].xy)}")
        for pid, xy in self.world.npcs():
            d = math.dist(me.xy, xy)
            if d <= HEAR_M and self.cast:
                p = self.cast.people[pid]
                close.append(f"- {pid}: {p['name']}, {p['role']}, {rough(d)} {bearing(me.xy, me.yaw, xy)}")
        lines.append("Who is right next to you (close enough to talk):\n" + ("\n".join(close) if close else "- nobody"))
        d = math.dist(me.xy, bodies[other.id].xy)
        if d <= HEAR_M:   # a bare list line wasn't enough: Iris wrote "Mara's inside" with Mara 2 m away (bodies demo)
            lines.append(f"{other.name} is here with you now ({rough(d)}), out in the open: talk to her directly, "
                         f"she hears everything you say.")
        reach = [f"- {oid}" for oid, xy, held in self.world.objects() if not held and math.dist(me.xy, xy) <= REACH_M]
        if reach:
            lines.append("Within arm's reach:\n" + "\n".join(reach))
        lines.append("Anyone or anything farther away, you only know from what you see in the picture.")
        ranked = sorted(self.nav.places.items(), key=lambda kv: math.dist(me.xy, self.nav.doors[kv[0]]))
        lines.append("Places you know in the village (nearest first):\n" + "\n".join(
            f"- {pid}: {p['name']} ({p['category'].replace('_', ' ')}), {rough(math.dist(me.xy, self.nav.doors[pid]))} "
            f"{compass(me.xy, self.nav.doors[pid])}" for pid, p in ranked[:14]))
        return "\n".join(lines)

    def prompt(self, mind):
        heard = "\n".join(mind.heard) if mind.heard else "(nothing)"
        notes = "\n".join(f"- {d}" for d in mind.diary[-8:]) or "(none yet)"
        recent = "\n".join(f"- {r}" for r in mind.recent[-6:]) or "(nothing yet)"
        return (f"{mind.who}\n\nSituation: {mind.situation}\n\n"
                f"The image is what you see right now, through your own eyes.\n\n{self.describe(mind)}\n\n"
                f"What you did and said recently:\n{recent}\nWhat just happened: {mind.last}\nWhat you heard:\n{heard}\n\n"
                f"Your notes so far:\n{notes}\n\n{live.ACTIONS}{FORMAT_NOTE}")

    def check(self, mind, act):
        t = act.get("type")
        people = {mind.other} | (set(self.cast.people) if self.cast else set())
        objects = {oid for oid, _, _ in self.world.objects()}
        if t == "go_to" and act.get("place") not in self.nav.places:
            raise ValueError(f"unknown place {act.get('place')!r}; use an id from the list")
        if t == "approach":
            act.setdefault("target", act.pop("person", None) or act.pop("object", None))
            if act["target"] not in people | objects:
                raise ValueError(f"unknown person or object {act['target']!r}")
        if t == "say" and not str(act.get("text", "")).strip():
            raise ValueError("say needs text")
        if t == "pick_up" and act.get("object") not in objects:
            raise ValueError(f"unknown object {act.get('object')!r}")
        if t == "look_at" and act.get("target") not in people | set(self.nav.places):
            raise ValueError(f"unknown person or place {act.get('target')!r}")
        if t not in ("go_to", "approach", "say", "look_at", "pick_up", "put_down", "wait"):
            raise ValueError(f"unknown action type {t!r}")

    def decide(self, mind):
        prompt = self.prompt(mind)
        error = None
        for _ in range(3):
            p = prompt if not error else (f"{prompt}\n\nYour last reply was rejected: {error}. Reply with only the JSON "
                                          f"object, with \"action\" as an object. For speech the words go in \"text\" "
                                          f"inside the action, like this: {RETRY_SHAPE}")
            t = time.time()
            raw = self.brain.ask(p, mind.seen)
            try:
                thought, act, diary = parse_reply(raw)
                self.check(mind, act)
                self.log("decision", mind=mind.id, prompt=prompt, raw=raw, seconds=round(time.time() - t, 1), frame=mind.seen)
                return thought, act, diary
            except Exception as e:
                error = str(e)
                self.log("bad_reply", mind=mind.id, raw=raw, error=error)
        return "(couldn't decide)", {"type": "wait"}, None

    # --- speech: no physics; whoever is within HEAR_M hears it now
    def speak(self, mind, text, queue, decided):
        bodies = self.world.bodies()
        me = bodies[mind.id].xy
        self.say(f"> **{mind.name}:** {text}")
        self.log("says", mind=mind.id, text=text)
        listeners = []
        other = self.minds[mind.other]
        if math.dist(me, bodies[other.id].xy) <= HEAR_M:
            other.heard.append(f"{mind.name} ({mind.id}): \"{text}\"")
            other.pending, other.awaiting = "heard", None
            listeners.append(other.id)
            if other.id not in decided and other.id not in queue:
                queue.append(other.id)   # the listener answers in the same step, after the speaker
        if self.cast:
            for pid, xy in self.world.npcs():
                if math.dist(me, xy) > HEAR_M:
                    continue
                line = self.cast.reply(pid, text, xy)
                if not line:   # QuietCast: nothing to add to someone else's conversation
                    continue
                listeners.append(pid)
                pname = self.cast.people[pid]["name"]
                self.say(f"> **{pname}:** {line}")
                self.log("npc_says", npc=pid, text=line, to=mind.id)
                for m in self.minds.values():   # an NPC's answer is heard by everyone near the NPC
                    if math.dist(bodies[m.id].xy, xy) <= HEAR_M:
                        m.heard.append(f"{pname} ({pid}): \"{line}\"")
                        m.pending = m.pending or "heard"
        self.log("heard_by", mind=mind.id, listeners=listeners)
        if not listeners:
            mind.last = f"You said \"{text}\", but nobody was close enough to hear."
            mind.awaiting = None
        else:
            mind.last = f"You said: \"{text}\""
            mind.awaiting = 0 if other.id in listeners else None
        return listeners

    # --- turning a decision into a sim action
    def next_leg(self, mind):
        x, y = mind.route[0]
        return {"type": "move_to", "position": {"x": x * 100, "y": y * 100, "z": 100}, "arrival_radius_cm": 120}

    def continuation(self, mind):
        if mind.new_leg and mind.route:
            mind.new_leg = False
            return self.next_leg(mind)
        if mind.idle:
            return self.face_other(mind) or {"type": "continue"}
        return {"type": "continue"}

    def face_other(self, mind):
        bodies = self.world.bodies()
        if math.dist(bodies[mind.id].xy, bodies[mind.other].xy) <= HEAR_M:
            return {"type": "look_at", "target_id": mind.other}
        return None

    def to_sim(self, mind, act):
        """Returns (sim action, problem). Speaking doesn't move anyone: walking goes on, idle people face each other."""
        t = act["type"]
        me = self.world.bodies()[mind.id].xy
        if t == "say":
            return self.continuation(mind), None
        if t == "go_to":
            if self.nav.place_at(me, 6.0) == act["place"]:
                return self.continuation(mind), f"You're already at {self.nav.places[act['place']]['name']}."
            route = self.nav.route(me, self.nav.doors[act["place"]])
            if route is None:
                return {"type": "wait"}, f"you can't find a way to {act['place']}"
            mind.route, mind.goal_place, mind.approaching, mind.blocked_count = route, act["place"], None, 0
            return self.next_leg(mind), None
        mind.route, mind.approaching = [], None
        if t == "approach":
            mind.approaching = act["target"]
            person = act["target"] == mind.other or (self.cast and act["target"] in self.cast.people)
            return {"type": "move_to", "target_id": act["target"], "arrival_radius_cm": (live.CHASE_M if person else 1.0) * 100}, None
        if t == "look_at":
            target = act["target"]
            if target in self.nav.places:
                x, y = self.nav.doors[target]
                return {"type": "look_at", "position": {"x": x * 100, "y": y * 100, "z": 200}}, None
            return {"type": "look_at", "target_id": target}, None
        if t == "pick_up":
            return {"type": "interact", "target_id": act["object"]}, None
        if t == "put_down":
            return {"type": "drop_object"}, None
        return self.face_other(mind) or {"type": "wait"}, None   # wait

    # --- after a step: who needs to decide next
    def after(self, mind, outcome):
        bodies = self.world.bodies()
        me = bodies[mind.id].xy
        phase = outcome.get("phase")
        self.log("outcome", mind=mind.id, at=[round(v, 2) for v in me], **outcome)
        if mind.route:
            if phase == "arrived":
                mind.route.pop(0)
                mind.blocked_count = 0
                if not mind.route:
                    mind.last = f"You arrived at {self.nav.places[mind.goal_place]['name']}."
                    mind.pending = mind.pending or "arrived"
                    self.say(f"_({mind.name} arrived at {self.nav.places[mind.goal_place]['name']})_")
                else:
                    mind.new_leg = True
            elif phase == "blocked" or outcome.get("status") == "failed":
                mind.blocked_count += 1
                if mind.blocked_count <= 2:
                    mind.route = self.nav.route(me, self.nav.doors[mind.goal_place]) or []
                    mind.new_leg = bool(mind.route)
                    if not mind.route:
                        mind.last, mind.pending = f"You lost your way to {self.nav.places[mind.goal_place]['name']}.", mind.pending or "failed"
                else:
                    mind.last = f"Something keeps blocking your way to {self.nav.places[mind.goal_place]['name']}."
                    mind.route, mind.pending = [], mind.pending or "failed"
            elif phase is None:   # the walk was interrupted (a look or a stop); pick the leg up again
                mind.new_leg = True
        elif mind.approaching:
            if phase in ("arrived", "blocked") or outcome.get("status") in ("completed", "failed"):
                who = mind.approaching
                name = self.minds[who].name if who in self.minds else who
                mind.last = f"You walked up to {name}." if phase == "arrived" else f"You couldn't reach {name}: {outcome.get('detail')}"
                mind.approaching, mind.pending = None, mind.pending or "approached"
        elif outcome.get("status") == "failed":
            mind.last, mind.pending = f"That didn't work: {outcome.get('detail')}", mind.pending or "failed"
        elif (mind.last_action or {}).get("type") in ("pick_up", "put_down") and not mind.last_action.get("reported") \
                and outcome.get("status") == "completed":
            act = mind.last_action
            mind.last = f"You picked up {act.get('object')}." if act["type"] == "pick_up" else "You put it down."
            mind.last_action = {**act, "reported": True}
        # running into people
        for pid, xy in [(mind.other, bodies[mind.other].xy)] + list(self.world.npcs() if self.cast else []):
            d = math.dist(me, xy)
            if d > FORGET_M:
                mind.met.discard(pid)
            elif d <= HEAR_M and pid not in mind.met:
                mind.met.add(pid)
                if not mind.idle or pid == mind.other:
                    name = self.minds[pid].name if pid in self.minds else self.cast.people[pid]["name"]
                    mind.last = f"{name} is right next to you now." if pid == mind.other else f"You pass {name} ({self.cast.people[pid]['role']})."
                    mind.pending = mind.pending or "met"
        # waiting for an answer
        if mind.awaiting is not None:
            mind.awaiting += 1
            if mind.awaiting >= PATIENCE:
                mind.awaiting = None
                mind.last, mind.pending = f"{self.minds[mind.other].name} hasn't answered you.", mind.pending or "no answer"

    def wants_to_decide(self, mind):
        return bool(mind.pending) or (mind.idle and mind.awaiting is None)

    def order(self):
        """Whoever has something to answer goes first; otherwise alternate who starts."""
        names = list(self.minds)
        if self.step_no % 2:
            names.reverse()
        return sorted([k for k in names if self.wants_to_decide(self.minds[k])],
                      key=lambda k: 0 if self.minds[k].heard else 1)

    # --- one step
    def step(self):
        queue, decided, actions, problems = self.order(), set(), {}, {}
        if queue and hasattr(self.wm, "release"):
            self.wm.release()   # the world model's weights go while Qwen thinks; the histories stay
        clock = self.world.clock
        while queue:
            k = queue.pop(0)
            if k in decided:
                continue
            mind = self.minds[k]
            decided.add(k)
            thought, act, diary = self.decide(mind)
            mind.decisions += 1
            n = mind.decisions
            if mind.seen:
                shutil.copy(mind.seen, self.out / "frames" / k / f"{self.step_no:04d}.png")
            if diary:
                mind.diary.append(f"[{clock}] {diary}")
            mind.last_thought, mind.last_action = thought, act
            self.say(f"\n### {clock[:5]} — step {self.step_no} — {mind.name}"
                     + (f" (answering)" if mind.pending == "heard" else "") + "\n"
                     + (f"![](frames/{k}/{self.step_no:04d}.png)\n\n" if mind.seen else "")
                     + f"*{thought}*\n\n**→** `{json.dumps(act)}`")
            self.log("act", mind=k, action=act, reason=mind.pending, n=n)
            mind.heard, mind.pending = [], None
            mind.recent.append(f"[{clock[:5]}] " + (f"you said \"{act['text']}\"" if act["type"] == "say" else json.dumps(act)))
            if act["type"] == "say":
                self.speak(mind, str(act["text"])[:500], queue, decided)
            actions[k], problems[k] = self.to_sim(mind, act)
            if problems[k]:
                mind.last = problems[k]
                mind.pending = "problem"
        for k, mind in self.minds.items():
            if k not in actions:
                actions[k] = self.continuation(mind)
        self.log("sim_actions", actions=actions)
        t = time.time()
        outcomes, frames = self.world.step(actions)
        t_sim = time.time() - t
        self.sim_t = self.world.sim_time_s
        self.perceive(frames)
        for k, mind in self.minds.items():
            self.after(mind, outcomes[k])
        self.log("step_time", sim_s=round(t_sim, 1), total_s=round(time.time() - t, 1))

    def run(self, steps):
        self.say(f"# Lunch at {self.args.meet_name} — {datetime.now():%Y-%m-%d %H:%M}\n\n"
                 + "\n\n".join(f"**{m.name}:** {m.who}\n\n*{m.situation}*" for m in self.minds.values()) + "\n")
        self.write_sidecar(final=False)
        try:
            frames = self.world.reset()
            self.sim_t = self.world.sim_time_s
            self.perceive(frames)
            for m in self.minds.values():
                m.pending = "start"
            self.snapshot()
            for self.step_no in range(steps):
                t = time.time()
                self.step()
                self.steps_done += 1
                self.snapshot()
                print(json.dumps({"step": self.step_no + 1, "of": steps, "clock": self.world.clock[:5],
                                  "step_s": round(time.time() - t, 1)}), flush=True)
        finally:
            self.running = False
            try:
                self.world.halt()
            finally:
                self.write_sidecar(final=True)
                self.snapshot()
                self.say(f"\n---\nRun folder: {self.out}")
                self.events.close()
                self.transcript.close()

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
                "films": {"side_by_side": "film/side_by_side.mp4", **{k: f"film/{k}.mp4" for k in self.minds}}}
        (self.out / "run.json").write_text(json.dumps(meta, indent=1, default=str))
        if final:
            for name in ["side_by_side", *self.minds]:
                film = self.out / "film" / f"{name}.mp4"
                if film.exists():
                    film.with_name(film.name + ".json").write_text(json.dumps({**meta, "film": name}, indent=1, default=str))


# ================================================================ entry point

def place_or_point(nav, text):
    if text in nav.doors:
        return tuple(nav.doors[text])
    x, y = (float(v) for v in text.split(","))
    return (x, y)


def build_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--minutes", type=float, default=5.0, help="sim-minutes to live")
    ap.add_argument("--step-s", type=float, default=10.0, help="sim-seconds per step (one decision chance each)")
    ap.add_argument("--clock", default="12:20")
    ap.add_argument("--speed", type=float, default=1.6, help="walking speed, m/s")
    ap.add_argument("--meet", default="kettle_cafe", help="where they agreed to meet for lunch")
    ap.add_argument("--first-start", default="fern_common", help="Mara's start: a place id or 'x,y' in metres")
    ap.add_argument("--second-start", default="fern_bakery", help="Iris's start: a place id or 'x,y' in metres")
    ap.add_argument("--no-npcs", action="store_true", help="leave out the scripted residents (Ana the barista included)")
    ap.add_argument("--weights", default=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"))
    ap.add_argument("--size", default="448x256", help="world-model canvas; 832x480 is the trained one, ~3x slower")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=2025, help="Mara's stream; Iris's is seed+1")
    ap.add_argument("--window", type=int, default=24, help="world-model history in latents (4 frames each), per stream")
    ap.add_argument("--sink", type=int, default=1)
    ap.add_argument("--quantize", type=int, choices=(4, 8), help="8 saves ~7 GB while painting; quality unmeasured")
    ap.add_argument("--wm-prompt", default=WM_PROMPT)
    ap.add_argument("--fake-wm", action="store_true", help="no world model: the 'painting' is a blend of the controls")
    ap.add_argument("--out", help="run folder (default out/city_agents/<stamp>_lunch)")
    args = ap.parse_args(argv)
    args.steps = max(1, int(round(args.minutes * 60 / args.step_s)))
    if abs(args.step_s * args.fps - round(args.step_s * args.fps)) > 1e-9:
        ap.error("--step-s times --fps must be a whole number of frames")
    return args


def people(args, nav):
    meet = nav.places[args.meet]["name"]
    args.meet_name = meet
    sit_m = MARA_SITUATION.replace("The Kettle (kettle_cafe)", f"{meet} ({args.meet})")
    sit_i = IRIS_SITUATION.replace("The Kettle (kettle_cafe)", f"{meet} ({args.meet})")
    args.first = {"id": "mara", "name": "Mara", "who": live.DEFAULT_WHO, "situation": sit_m,
                  "start_note": "You just stepped out of the Fern Common House."}
    args.second = {"id": "iris", "name": "Iris", "who": IRIS_WHO, "situation": sit_i,
                   "start_note": "You just stepped out of Rise Bakery with a loaf under your arm."}


class QuietCast(Cast):
    """live.Cast, but a resident only answers a line when it's her first greeting, a topic or place she knows, or she's
    named. Otherwise the barista answered every line Mara and Iris said to each other ("Ha, fair enough.")."""

    def reply(self, pid, text, listener_xy):
        p = self.people[pid]
        first = pid not in self.met
        named = p["name"].split()[0].lower() in text.lower()
        line = super().reply(pid, text, listener_xy)
        if not first and not named and line in p.get("fallback", ()):
            return None
        return line


def lunch_cast(nav):
    """live.py's residents, quiet unless spoken to, with the barista at the meeting place able to talk about lunch
    (npcs.json is not edited)."""
    cast = QuietCast(nav, HERE / "npcs.json")
    for p in cast.people.values():
        if p.get("stay_at") == "kettle_cafe":
            p["topics"] = {**LUNCH_TOPIC, **p["topics"]}
    return cast


def make_world(args, nav, cast):
    fps = args.fps
    tick = 1.0 / (2 * fps)   # the adapter needs a velocity window shorter than the first capture
    offsets = tuple(round(k / fps, 9) for k in range(1, int(round(args.step_s * fps)) + 1))
    first, second = place_or_point(nav, args.first_start), place_or_point(nav, args.second_start)
    meet = nav.doors[args.meet]
    yaw = lambda p: math.degrees(math.atan2(meet[1] - p[1], meet[0] - p[0]))   # both start facing roughly toward lunch
    bowls = [SpawnSpec(id=f"lunch_bowl_{k}", kind="object", asset=MUG_ASSET,
                       position=(meet[0] * 100 + 120 + 60 * k, meet[1] * 100 + 120, 30)) for k in (1, 2)]
    cfg = SimWorldConfig(port=args.port, step_seconds=args.step_s, tick_interval_s=tick, velocity_window_s=tick,
                         capture_offsets_s=offsets, resolution=(640, 360), fov_deg=90,
                         modalities=("rgb", "depth", "segmentation"), out_dir=str(Path(args.out) / "sim"),
                         npcs=cast.specs() if cast else [], objects=bowls,
                         agent_position=(first[0] * 100, first[1] * 100, 200), agent_yaw=yaw(first),
                         agent_speed_cm_s=args.speed * 100, hearing_radius_cm=HEAR_M * 100,
                         spawn_weather_manager=False, start_time=args.clock)
    return SimWorldPair(cfg, args.first["id"], args.second["id"], second, yaw(second))


def open_streams(wm, args, ids):
    planned = int(args.steps * args.step_s * args.fps) + 1
    for i, k in enumerate(ids):
        wm.open(k, args.wm_prompt, size=args.size, fps=args.fps, seed=args.seed + i, window=args.window, sink=args.sink,
                planned_frames=planned)


def main(argv=None):
    from world_stream_multi import MultiWorldStream
    args = build_args(argv)
    nav = NavMap()
    people(args, nav)
    cast = None if args.no_npcs else lunch_cast(nav)
    args.out = args.out or str(ROOT / "out" / "city_agents" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "_lunch"))
    Path(args.out).mkdir(parents=True, exist_ok=True)
    wm = MultiWorldStream(out_dir=Path(args.out) / "wm", quantize=args.quantize, fake=args.fake_wm)
    try:
        open_streams(wm, args, [args.first["id"], args.second["id"]])
        with make_world(args, nav, cast) as world:
            lunch = Lunch(args, world, wm, QwenBrain(args.weights), out=args.out, nav=nav, cast=cast)
            lunch.run(args.steps)
    finally:
        wm.close()


if __name__ == "__main__":
    main()
