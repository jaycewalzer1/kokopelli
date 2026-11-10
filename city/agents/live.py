"""A local Qwen living in the solarpunk city: it sees, decides, walks, talks and carries things.

    .venv/bin/python city/agents/live.py --port 9001 --steps 30
    .venv/bin/python city/agents/live.py --situation "You're hungry and it's lunchtime."
    .venv/bin/python city/agents/live.py --vision cosmos      # Qwen sees Cosmos's repaint of the frame

Each step the sim advances STEP_S sim-seconds. Qwen is asked only at decision points: when it has
arrived, when something failed, when someone spoke to it, or every step while it isn't walking.
While it walks a route, steps run without asking (that's the "keep going" a person doesn't think about).

Pieces:
- physics: runtime/adapters/simworld.py (owned by the wm-agent-loop branch; used read-only from its worktree)
- routes:  navmap.py, from world.json
- people:  npcs.json, scripted; they answer when spoken to within HEAR_M
- mind:    llm_model.ask (Qwen3-VL on MLX), 4-bit by default
- bodies:  city/bodies/client.py; after spawning, each person is asked into a body (--body, npcs.json "body")
Everything is written to out/city_agents/<run>/: events.jsonl, transcript.md, run.json (models, bodies) and the frames.
"""
import argparse
import json
import math
import random
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".claude" / "worktrees" / "wm-agent-loop"
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(RUNTIME))


def _borrow_unrealcv():
    """The unrealcv client is pure Python; load SimWorld's copy by path instead of installing it into the
    shared .venv. Only this one package: adding SimWorld's whole site-packages would shadow torch etc."""
    import importlib.util
    import types
    sys.modules.setdefault("docker", types.ModuleType("docker"))  # only its Docker launcher uses it; we never launch
    pkg = next((ROOT / "simworld" / ".venv" / "lib").glob("python*/site-packages/unrealcv"))
    spec = importlib.util.spec_from_file_location("unrealcv", pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["unrealcv"] = module
    spec.loader.exec_module(module)


try:
    import unrealcv  # noqa: F401
except ImportError:
    _borrow_unrealcv()
sys.path.insert(0, str(Path(__file__).resolve().parent))

from city.bodies import client as bodies  # noqa: E402
from navmap import NavMap  # noqa: E402
from runtime.adapters.simworld import AGENT_ACTOR, BOX_ASSET, NpcSpec, SimWorldConfig, SimWorldPhysics, SpawnSpec  # noqa: E402

STEP_S = 15.0
HEAR_M = 10.0
SEE_PEOPLE_M = 40.0
SEE_THINGS_M = 20.0
SENSE_M = 6.0  # close enough to notice without looking (footsteps, peripheral vision)
FOV_HALF_DEG = 60.0
NEAR_PLACES = 6
CHASE_M = 2.5

DEFAULT_WHO = ("You are Mara, 34, a textile designer at Loom & Thread. You live in Fern Court. "
               "You're warm, a bit chatty, and you notice plants and light.")
DEFAULT_SITUATION = ("It's a Friday afternoon. You promised Tomas you'd collect the bread order from Rise Bakery "
                     "and bring it to the Fern Common House for tonight's shared dinner. After that your time is "
                     "your own; you've been meaning to play chess with someone.")

ACTIONS = """Reply with ONE JSON object and nothing else:
{"thought": "<one sentence: what you notice and why you choose this>", "action": <action>, "diary": "<optional short note to your future self>"}
<action> is one of:
{"type": "go_to", "place": "<place id from the list>"}       walk there along the streets
{"type": "approach", "target": "<person id or object id>"}    walk right up to someone or something you can see
{"type": "say", "text": "<what you say out loud>"}            people within 10 m hear you
{"type": "look_at", "target": "<person id or place id>"}
{"type": "pick_up", "object": "<object id>"}                  must be within 3 m
{"type": "put_down"}
{"type": "wait"}                                              stay and let time pass"""


# --- small helpers -------------------------------------------------------------------------------

def m(v):
    """cm Vec3 -> (x, y) metres"""
    return (v.x / 100.0, v.y / 100.0)


def bearing(from_xy, yaw_deg, to_xy):
    """'ahead', 'left', ... relative to where you face. Unreal yaw 0 = +X (east), 90 = +Y (south)."""
    ang = math.degrees(math.atan2(to_xy[1] - from_xy[1], to_xy[0] - from_xy[0]))
    d = (ang - yaw_deg + 540) % 360 - 180
    for limit, word in ((30, "ahead"), (75, "ahead-right" if d > 0 else "ahead-left"),
                        (120, "to your right" if d > 0 else "to your left"), (180, "behind you")):
        if abs(d) <= limit:
            return word
    return "behind you"


def rough(d):
    """Distances the way people estimate them."""
    if d < 4:
        return "right here"
    if d < 20:
        return f"a few metres ({5 * round(d / 5):.0f} m)" if d >= 8 else "a few steps away"
    if d < 100:
        return f"about {10 * round(d / 10):.0f} m"
    return f"about {50 * round(d / 50):.0f} m"


def compass(from_xy, to_xy):
    ang = math.degrees(math.atan2(-(to_xy[1] - from_xy[1]), to_xy[0] - from_xy[0]))  # north is -y
    return ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"][round(ang / 45) % 8]


def parse_reply(raw):
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    data = json.loads(match.group())
    act = data.get("action")
    if isinstance(act, str):  # {"action": "go_to", "place": ...}
        act = {"type": act, **{k: v for k, v in data.items() if k not in ("action", "thought", "diary")}}
    if not isinstance(act, dict) or "type" not in act:
        raise ValueError("'action' must be an object with a 'type'")
    return data.get("thought", ""), act, data.get("diary")


# --- scripted people -----------------------------------------------------------------------------

class Cast:
    def __init__(self, nav, path):
        self.nav = nav
        self.people = {p["id"]: p for p in json.loads(Path(path).read_text())["npcs"]}
        self.met, self.said = set(), {}
        self.rng = random.Random(0)

    def specs(self):
        out = []
        for k, (pid, p) in enumerate(self.people.items()):
            if "stay_at" in p:
                x, y = self.nav.doors[p["stay_at"]]
                out.append(NpcSpec(id=pid, position=(x * 100, y * 100, 150), index=k))
            else:
                stops = [self.nav.doors[s] for s in p["walk"]]
                pts = []
                for a, b in zip(stops, stops[1:] + stops[:1]):
                    pts += [w for w in self.nav.route(a, b) or [b]]
                x, y = stops[0]
                out.append(NpcSpec(id=pid, position=(x * 100, y * 100, 150), index=k, speed_cm_s=110,
                                   waypoints=[(px * 100, py * 100) for px, py in pts]))
        return out

    def reply(self, pid, text, listener_xy):
        p, low = self.people[pid], text.lower()
        parts = []
        if pid not in self.met:
            self.met.add(pid)
            parts.append(self.rng.choice(p["greeting"]))
        said = self.said.setdefault(pid, set())
        for keys, line in p["topics"].items():
            if keys not in said and any(re.search(rf"\b{k}(s|es)?\b", low) for k in keys.split("|")):
                said.add(keys)  # a topic is answered once; next time a later keyword can match
                parts.append(line)
                break
        for place_id, place in self.nav.places.items():
            if place["name"].lower() in low or place_id.replace("_", " ") in low:
                door = self.nav.doors[place_id]
                d = math.dist(listener_xy, door)
                parts.append(f"{place['name']}? That's {rough(d)} {compass(listener_xy, door)} of here." if d > 15
                             else f"{place['name']}? You're standing at it!")
                break
        if not parts:
            parts.append(self.rng.choice(p["fallback"]))
        return " ".join(parts)


# --- what Qwen sees ------------------------------------------------------------------------------

class UnrealVision:
    name = "unreal"

    def see(self, frame, prompt_hint):
        return frame


class CosmosVision:
    """Cosmos3 Sim-Transfer repaints the Unreal frame before Qwen sees it, as in the world-model loop.
    Qwen and Cosmos don't fit in 36 GB together, so Qwen is unloaded around each repaint."""
    name = "cosmos"

    def __init__(self, out_dir):
        from runtime.adapters.cosmos import CosmosWorldModel
        from runtime.interfaces import ChunkRequest, CondFrame
        self.wm, self.Req, self.Cond = CosmosWorldModel("448x256", 30, 8), ChunkRequest, CondFrame  # runtime/config.py "demo"
        self.out = Path(out_dir) / "cosmos"
        self.out.mkdir(parents=True, exist_ok=True)
        self.k = 0

    def see(self, frame, prompt_hint):
        from core import llm_model
        from runtime.frames import read_clip, save_rgb
        llm_model.unload()
        self.k += 1
        clip = self.wm.render_chunk(self.Req(prompt=prompt_hint, cond=[self.Cond(frame, "sim")], target=None,
                                             output=str(self.out / f"c{self.k:04d}.mp4"), tick=self.k, chunk=0, frames=16, seed=0))
        path = self.out / f"c{self.k:04d}.png"
        save_rgb(read_clip(clip)[-1], path)
        return str(path)


# --- the loop ------------------------------------------------------------------------------------

class Life:
    def __init__(self, args):
        self.args = args
        self.nav = NavMap()
        self.cast = Cast(self.nav, Path(__file__).with_name("npcs.json"))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out = ROOT / "out" / "city_agents" / stamp
        (self.out / "frames").mkdir(parents=True, exist_ok=True)
        self.events = (self.out / "events.jsonl").open("a")
        self.transcript = (self.out / "transcript.md").open("a")
        self.route, self.goal_place = [], None
        self.diary, self.heard, self.recent, self.last = [], [], [], "You just stepped out of the Fern Common House."
        self.blocked_count = 0
        self.new_leg = False
        self.approaching = None
        self.running, self.last_thought, self.last_action = True, "", None
        self.bodies = {}  # who -> what the server said to SetBody (city/bodies/client.py BodyResult.as_dict())
        self.watch_tiers = False  # ask GetBody each step for near/far, while the server knows the command
        self.tiers = {}  # who -> last tier seen, so a fall back to the mannequin is warned about once, not every step
        self.vision = CosmosVision(self.out) if args.vision == "cosmos" else UnrealVision()
        bakery = self.nav.doors["fern_bakery"]
        self.objects = [SpawnSpec(id="bread_box", kind="object", asset=BOX_ASSET,
                                  position=(bakery[0] * 100 + 150, bakery[1] * 100 + 150, 30))]
        home = self.nav.doors["fern_common"]
        self.cfg = SimWorldConfig(
            port=args.port, step_seconds=STEP_S, capture_offsets_s=(STEP_S,), resolution=(640, 360), fov_deg=90,
            modalities=("rgb",), out_dir=str(self.out / "sim"), npcs=self.cast.specs(), objects=self.objects,
            agent_position=(home[0] * 100, home[1] * 100, 200), agent_yaw=-90.0, agent_speed_cm_s=args.speed * 100,
            hearing_radius_cm=HEAR_M * 100, spawn_weather_manager=False, start_time=args.clock)

    # logging
    def log(self, kind, **data):
        self.events.write(json.dumps({"t": round(self.sim_t, 1), "kind": kind, **data}) + "\n")
        self.events.flush()

    def write_run(self, finished=False):
        """out/city_agents/<run>/run.json: which models and bodies this run used, rewritten as they become known."""
        weights = Path(self.args.weights)
        meta = {"run": self.out.name, "agent_model": weights.name, "agent_model_path": str(weights),
                "vision": self.vision.name,
                "world_model": "runtime.adapters.cosmos.CosmosWorldModel 448x256" if self.vision.name == "cosmos" else None,
                "port": self.args.port, "steps": self.args.steps, "clock": self.args.clock,
                "body_asked": {"agent": self.agent_body,
                               **{pid: p.get("body") for pid, p in self.cast.people.items()}},
                "bodies": self.bodies, "finished": finished}
        tmp = self.out / "run.json.tmp"
        tmp.write_text(json.dumps(meta, indent=1))
        tmp.replace(self.out / "run.json")

    @property
    def agent_body(self):
        return getattr(self.args, "body", None) or None  # subclasses with their own args (live_wm.py) may not have it

    def dress(self, sim):
        """Ask the server to put each person in their body: the agent in --body, residents in npcs.json's "body".
        A body is a nicety: an old server without SetBody, or a missing asset, is a warning in events.jsonl and the
        run goes on with whatever the server gave the actor (its Bodies.json mapping, or the placeholder)."""
        who = {AGENT_ACTOR: "agent", **{spec.actor_name: spec.id for spec in self.cfg.npcs}}
        wants = {AGENT_ACTOR: self.agent_body,
                 **{spec.actor_name: self.cast.people[spec.id].get("body") for spec in self.cfg.npcs}}
        for actor, result in bodies.dress(sim.wire, wants).items():
            self.bodies[who[actor]] = result.as_dict()
            if result.ok:
                self.log("body", who=who[actor], **result.as_dict())
            else:
                self.log("body_warning", who=who[actor], **result.as_dict())
                print(f"(no body {result.requested!r} for {who[actor]}: {result.error}; keeping the server's choice)")
        self.watch_tiers = any(r["supported"] for r in self.bodies.values())
        self.write_run()

    def log_tiers(self, sim, step):
        """Each person's near/far body this step (PLAN.md "Near/far bodies"): a swap in view is a visible pop for
        the world model, so it has to be findable afterwards. Stops asking once the server never reports a tier."""
        if not self.watch_tiers:
            return
        who = {AGENT_ACTOR: "agent", **{spec.actor_name: spec.id for spec in self.cfg.npcs}}
        now = {who[actor]: tier for actor, tier in bodies.tiers(sim.wire, who).items()}
        if not any(now.values()):
            self.watch_tiers = False  # a server from before the near/far plan
            return
        self.log("tiers", step=step, tiers=now)  # step k = after k sim steps
        for who_, tier in now.items():
            if tier == "fallback" and self.tiers.get(who_) != "fallback":
                self.log("body_warning", who=who_, step=step, tier=tier,
                         error="showing the mannequin: the body failed to load (or memory pressure)")
        self.tiers = now

    def say(self, md):
        print(md, flush=True)
        self.transcript.write(md + "\n")
        self.transcript.flush()

    # the watchable view: camera 0 is the game window
    def follow(self, state):
        """Camera 0 is the game window, i.e. whoever is at the keyboard. Only steer it when asked (--follow)."""
        if not self.args.follow:
            return
        a = state.agent.pose
        yaw = math.radians(a.rotation.yaw)
        x, y = a.location.x - 700 * math.cos(yaw), a.location.y - 700 * math.sin(yaw)
        try:
            self.sim.wire.request(f"vset /camera/0/location {x:.0f} {y:.0f} {a.location.z + 380:.0f}", resend=False)
            self.sim.wire.request(f"vset /camera/0/rotation -18 {a.rotation.yaw:.1f} 0", resend=False)
        except Exception as e:  # the view is a nicety; never stop a life for it
            print(f"(camera follow failed: {e})")

    def snapshot(self, state, frame, step):
        """out/city_agents/<run>/live.json, rewritten atomically every step, for the dev panel's live view."""
        path = self.out / "live.json"
        snap = json.loads(path.read_text()) if path.exists() else {}
        snap.update(run=self.out.name, updated=datetime.now().isoformat(timespec="seconds"),
                    running=getattr(self, "running", True), who=self.args.who, situation=self.args.situation,
                    vision=self.vision.name, last_thought=self.last_thought, last_action=self.last_action,
                    last_result=self.last, heard=self.heard[-4:], diary=self.diary[-8:])
        if state is not None:
            me = m(state.agent.pose.location)
            shutil.copy(frame, self.out / "frames" / "live.tmp.png")
            (self.out / "frames" / "live.tmp.png").replace(self.out / "frames" / "live.png")
            snap.update(step=step, clock=state.time_of_day.clock, frame="frames/live.png",
                        agent={"x_m": round(me[0], 2), "y_m": round(me[1], 2), "yaw": round(state.agent.pose.rotation.yaw, 1),
                               "carrying": state.agent.held_object, "place": self.nav.place_at(me)},
                        npcs=[{"id": n.id, "name": self.cast.people[n.id]["name"], "role": self.cast.people[n.id]["role"],
                               "x_m": round(m(n.pose.location)[0], 2), "y_m": round(m(n.pose.location)[1], 2)} for n in state.npcs],
                        objects=[{"id": o.id, "x_m": round(m(o.pose.location)[0], 2), "y_m": round(m(o.pose.location)[1], 2),
                                  "held_by": o.held_by} for o in state.objects if o.pose],
                        route=[[round(x, 1), round(y, 1)] for x, y in self.route], goal=self.goal_place)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, indent=1))
        tmp.replace(path)

    def sees(self, me, yaw, p, max_m):
        """What a person standing here would notice: close enough to sense (sound, peripheral vision),
        or in front of them, within range, and not behind a building."""
        d = math.dist(me, p)
        if d <= SENSE_M:
            return True
        ahead = abs((math.degrees(math.atan2(p[1] - me[1], p[0] - me[0])) - yaw + 540) % 360 - 180) <= FOV_HALF_DEG
        return ahead and d <= max_m and self.nav.line_of_sight(me, p)

    def describe(self, state):
        """The situation in a person's terms: no coordinates, rough distances, only what is in view.
        Where the places are counts as knowledge: Mara has lived here for years."""
        me, yaw = m(state.agent.pose.location), state.agent.pose.rotation.yaw
        here = self.nav.place_at(me)
        near = self.nav.place_at(me, 40.0)
        where = (f"at {self.nav.places[here]['name']}" if here else
                 f"out in the streets near {self.nav.places[near]['name']}" if near else "out in the streets")
        lines = [f"Time: {state.time_of_day.clock[:5]}.",
                 f"You are {where}, {state.agent.posture}, carrying {state.agent.held_object or 'nothing'}."]
        if self.route:
            lines.append(f"You are walking to {self.nav.places[self.goal_place]['name']}, "
                         f"{rough(self.nav.length(me, self.route))} to go.")
        people = []
        for npc in state.npcs:
            p, at = self.cast.people[npc.id], m(npc.pose.location)
            if self.sees(me, yaw, at, SEE_PEOPLE_M):
                d = math.dist(me, at)
                people.append(f"- {npc.id}: {p['name']}, {p['role']}, {rough(d)} {bearing(me, yaw, at)}"
                              + (" (close enough to talk)" if d <= HEAR_M else ""))
        lines.append("People you notice:\n" + ("\n".join(people) if people else "- nobody"))
        things = [f"- {o.id}: {rough(math.dist(me, m(o.pose.location)))} {bearing(me, yaw, m(o.pose.location))}"
                  for o in state.objects if o.pose and not o.held_by and self.sees(me, yaw, m(o.pose.location), SEE_THINGS_M)]
        if things:
            lines.append("Things you notice:\n" + "\n".join(things))
        ranked = sorted(self.nav.places.items(), key=lambda kv: math.dist(me, self.nav.doors[kv[0]]))
        lines.append("Places you know in the village (nearest first):\n" + "\n".join(
            f"- {pid}: {p['name']} ({p['category'].replace('_', ' ')}), {rough(math.dist(me, self.nav.doors[pid]))} "
            f"{compass(me, self.nav.doors[pid])}" + (f" — {p['vibe']}" if k < NEAR_PLACES and p.get('vibe') else "")
            for k, (pid, p) in enumerate(ranked)))
        return "\n".join(lines)

    def prompt(self, state):
        heard = "\n".join(self.heard) if self.heard else "(nothing)"
        notes = "\n".join(f"- {d}" for d in self.diary[-8:]) or "(none yet)"
        recent = "\n".join(f"- {r}" for r in self.recent[-5:]) or "(nothing yet)"
        return (f"{self.args.who}\n\nSituation: {self.args.situation}\n\n"
                f"The image is what you see right now, through your own eyes.\n\n{self.describe(state)}\n\n"
                f"What you did recently:\n{recent}\nWhat just happened: {self.last}\nWhat you heard:\n{heard}\n\n"
                f"Your notes so far:\n{notes}\n\n{ACTIONS}")

    def decide(self, state, frame):
        from core import llm_model
        if self.args.weights:
            llm_model.LLM_MODEL_WEIGHTS = Path(self.args.weights)
        prompt = self.prompt(state)
        seen = self.vision.see(frame, "A sunny solarpunk village street, timber buildings with plants, people walking.")
        error = None
        for attempt in range(2):
            p = prompt if not error else f"{prompt}\n\nYour last reply was rejected: {error}. Reply with only the JSON object."
            t = time.time()
            try:
                raw = llm_model.ask(p, [seen], max_tokens=300, temperature=0.4)
            except RuntimeError as e:
                # Seen after ~40 decisions next to Unreal: "[Event::Event] Failed to create Metal shared event".
                # Free MLX's GPU state and reload once; a second failure ends the run.
                self.log("llm_error", error=str(e))
                llm_model.unload()
                raw = llm_model.ask(p, [seen], max_tokens=300, temperature=0.4)
            import mlx.core as mx
            mx.clear_cache()  # don't hold GPU buffers between decisions; Unreal shares the GPU
            try:
                thought, act, diary = parse_reply(raw)
                self.check(act, state)
                self.log("decision", prompt=prompt, raw=raw, seconds=round(time.time() - t, 1), frame=seen)
                return thought, act, diary
            except Exception as e:
                error = str(e)
                self.log("bad_reply", raw=raw, error=error)
        return "(couldn't decide)", {"type": "wait"}, None

    def check(self, act, state):
        t = act["type"]
        if t == "go_to" and act.get("place") not in self.nav.places:
            raise ValueError(f"unknown place {act.get('place')!r}; use an id from the list")
        if t == "approach":
            act.setdefault("target", act.pop("person", None) or act.pop("object", None))
            if act["target"] not in self.cast.people and act["target"] not in {o.id for o in state.objects}:
                raise ValueError(f"unknown person or object {act['target']!r}")
        if t == "say" and not str(act.get("text", "")).strip():
            raise ValueError("say needs text")
        if t == "pick_up" and act.get("object") not in {o.id for o in state.objects}:
            raise ValueError(f"unknown object {act.get('object')!r}")
        if t not in ("go_to", "approach", "say", "look_at", "pick_up", "put_down", "wait"):
            raise ValueError(f"unknown action type {t!r}")

    # turn a decision into a sim action
    def to_sim(self, act, state):
        t, me = act["type"], m(state.agent.pose.location)
        if t == "go_to":
            if self.nav.place_at(me, 6.0) == act["place"]:
                return {"type": "wait"}, f"You're already at {self.nav.places[act['place']]['name']}."
            route = self.nav.route(me, self.nav.doors[act["place"]])
            if route is None:
                return {"type": "wait"}, f"you can't find a way to {act['place']}"
            self.route, self.goal_place = route, act["place"]
            return self.next_leg(), None
        self.route, self.approaching = [], None
        if t == "approach":
            self.approaching = act["target"]
            near = CHASE_M if act["target"] in self.cast.people else 1.0  # things: within arm's reach
            return {"type": "move_to", "target_id": act["target"], "arrival_radius_cm": near * 100}, None
        if t == "say":
            return {"type": "speak", "text": act["text"][:500]}, None
        if t == "look_at":
            target = act.get("target", "")
            if target in self.cast.people:
                return {"type": "look_at", "target_id": target}, None
            if target in self.nav.places:
                x, y = self.nav.doors[target]
                return {"type": "look_at", "position": {"x": x * 100, "y": y * 100, "z": 200}}, None
            return {"type": "wait"}, f"you couldn't find {target!r} to look at"
        if t == "pick_up":
            return {"type": "interact", "target_id": act["object"]}, None
        if t == "put_down":
            return {"type": "drop_object"}, None
        return {"type": "wait"}, None

    def next_leg(self):
        x, y = self.route[0]
        return {"type": "move_to", "position": {"x": x * 100, "y": y * 100, "z": 100}, "arrival_radius_cm": 120}

    def run(self):
        self.sim_t = 0.0
        self.write_run()
        self.say(f"# A life in the city — {datetime.now():%Y-%m-%d %H:%M}\n\n**Who:** {self.args.who}\n\n"
                 f"**Situation:** {self.args.situation}\n\n**Vision:** {self.vision.name}\n")
        with SimWorldPhysics(self.cfg) as sim:
            self.sim = sim
            try:
                self._live(sim)
            finally:
                self.halt(sim)
        self.running = False
        self.write_run(finished=True)
        self.snapshot(None, None, None)
        self.say(f"\n---\nRun folder: {self.out}")

    def halt(self, sim):
        """Stop everyone before the adapter un-pauses the game. Otherwise residents keep walking in a straight
        line forever, leave the map and fall, and the far-out actors crashed UE 5.8's scene culling (~25 min later)."""
        for spec in self.cfg.npcs:
            try:
                sim.wire.request(f"vbp {spec.actor_name} StopPedestrian", resend=False)
            except Exception as e:
                print(f"(could not stop {spec.id}: {e})")
        try:
            sim.wire.request("vbp GEN_BP_Humanoid_0 StopAgent", resend=False)
        except Exception as e:
            print(f"(could not stop the agent: {e})")

    def _live(self, sim):
        cap = sim.reset(seed=0)
        self.dress(sim)  # after spawning, so every actor exists; the first frame may still show the old bodies
        self.log_tiers(sim, 0)
        state, frame = cap.state, cap.renders["rgb"].path
        self.follow(state)
        self.snapshot(state, frame, 0)
        decide = True
        for step in range(self.args.steps):
            self.sim_t = state.sim_time_s
            if decide:
                thought, act, diary = self.decide(state, frame)
                shutil.copy(frame, self.out / "frames" / f"{step:04d}.png")
                if diary:
                    self.diary.append(f"[{state.time_of_day.clock}] {diary}")
                self.last_thought, self.last_action = thought, act
                self.say(f"\n### {state.time_of_day.clock} — step {step}\n![](frames/{step:04d}.png)\n\n"
                         f"*{thought}*\n\n**→** `{json.dumps(act)}`")
                self.heard = []
                self.recent.append(f"[{state.time_of_day.clock}] " + json.dumps({k: v for k, v in act.items()}))
                sim_action, problem = self.to_sim(act, state)
                self.problem = problem
                if problem:
                    self.last = problem
            else:
                act, self.problem = {"type": "continue"}, None
                sim_action = self.next_leg() if self.new_leg else {"type": "continue"}
            self.log("act", action=act, sim_action=sim_action)
            result = sim.step(sim_action)
            self.log_tiers(sim, step + 1)
            state, frame = result.final_state, result.captures[-1].renders["rgb"].path
            self.follow(state)
            self.new_leg = False
            decide = self.after(act, sim_action, result, state)
            self.snapshot(state, frame, step + 1)

    def after(self, act, sim_action, result, state):
        """Update the route and what the agent will be told. Returns True if Qwen should decide now."""
        out = result.outcome
        me = m(state.agent.pose.location)
        self.log("outcome", status=out.status, detail=out.detail, at=me)
        # speech: who heard, and their scripted answers
        if sim_action["type"] == "speak":
            listeners = [n for n in state.npcs if math.dist(me, m(n.pose.location)) <= HEAR_M]
            if not listeners:
                self.last = "You spoke, but nobody was close enough to hear."
            else:
                self.last = f"You said: \"{sim_action['text']}\""
                for n in listeners:
                    line = self.cast.reply(n.id, sim_action["text"], m(n.pose.location))
                    self.heard.append(f"{self.cast.people[n.id]['name']} ({n.id}): \"{line}\"")
                    self.say(f"> **{self.cast.people[n.id]['name']}:** {line}")
                    self.log("npc_says", npc=n.id, text=line)
            return True
        # a walking step is either the leg's own move_to or a continue of it
        on_route = bool(self.route) and (sim_action["type"] == "continue" or "position" in sim_action)
        if on_route:
            if out.status == "completed":
                self.route.pop(0)
                self.blocked_count = 0
                if not self.route:
                    self.last = f"You arrived at {self.nav.places[self.goal_place]['name']}."
                    self.say(f"_(arrived at {self.nav.places[self.goal_place]['name']})_")
                    return True
                self.new_leg = True
                return self.someone_close(state)
            if out.status == "failed":
                self.blocked_count += 1
                if self.blocked_count <= 2:  # re-plan from where we are; obstacles off the plan (trees, stalls) nudge the path
                    self.route = self.nav.route(me, self.nav.doors[self.goal_place]) or []
                    self.new_leg = bool(self.route)
                    return not self.route
                self.last = f"Something keeps blocking your way to {self.nav.places[self.goal_place]['name']} ({out.detail})."
                self.route = []
                return True
            return self.someone_close(state)  # in progress
        if sim_action["type"] == "move_to" or (sim_action["type"] == "continue" and self.approaching):
            if out.status == "in_progress":
                return False
            who, self.approaching = self.approaching or "them", None
            self.last = f"You walked up to {who}." if out.status == "completed" else f"You couldn't reach them: {out.detail}"
            return True
        if sim_action["type"] == "continue":
            return True
        if self.problem:
            return True
        self.last = {"completed": f"Done: {act['type']}.", "failed": f"That didn't work: {out.detail}"}.get(out.status, f"{act['type']}: {out.status}")
        return True

    def someone_close(self, state):
        """While walking, stop and think when someone you haven't met comes within earshot."""
        me = m(state.agent.pose.location)
        for n in state.npcs:
            if n.id not in self.cast.met and math.dist(me, m(n.pose.location)) <= HEAR_M:
                self.last = f"While walking, you pass {self.cast.people[n.id]['name']} ({self.cast.people[n.id]['role']})."
                return True
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--steps", type=int, default=40, help=f"each is {STEP_S:.0f} sim-seconds")
    ap.add_argument("--who", default=DEFAULT_WHO)
    ap.add_argument("--situation", default=DEFAULT_SITUATION)
    ap.add_argument("--clock", default="14:00")
    ap.add_argument("--speed", type=float, default=1.6, help="walking speed, m/s")
    ap.add_argument("--follow", action="store_true", help="steer the game window's camera behind the agent each step")
    ap.add_argument("--vision", choices=["unreal", "cosmos"], default="unreal")
    ap.add_argument("--body", default="mara",
                    help="the agent's body id (mac_server/Config/Bodies.json); '' sends nothing and keeps the server's")
    ap.add_argument("--weights", default=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"),
                    help="Qwen weights folder; the full model needs ~18 GB")
    life = Life(ap.parse_args())
    try:
        life.run()
    except Exception:
        # Never got a first frame (e.g. the server's one connection was taken): don't leave an empty run behind.
        if not (life.out / "live.json").exists():
            life.events.close()
            life.transcript.close()
            shutil.rmtree(life.out, ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
