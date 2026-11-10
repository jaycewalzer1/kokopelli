"""Two thinking people meet for lunch inside the world model: each sees only what Cosmos3-Nano-Sim-Transfer paints.

    kokopelli/agents/run_wm_lunch.sh --minutes 5                       # the real thing (queue it; see AGENTS.md)
    .venv/bin/python -m kokopelli.agents.lunch_wm --port 9001 --minutes 5
    .venv/bin/python -m kokopelli.agents.lunch_wm --fake-wm ...        # SimWorld for real, world model faked (no weights)

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
import time
from datetime import datetime
from pathlib import Path

from kokopelli.agents import live  # noqa: E402  (borrows unrealcv)
from kokopelli.agents.live import Cast, parse_reply, rough, bearing, compass  # noqa: E402,F401
from kokopelli.agents.live_wm import BLUR_DOWNUP, FAR_CM, NEAR_CM, REACH_M, Film  # noqa: E402,F401
from kokopelli.agents.navmap import NavMap  # noqa: E402
from kokopelli.agents import lunch_fixes as fx  # noqa: E402

ROOT = live.ROOT
from kokopelli.wm.controls import controls as ctl  # noqa: E402
from kokopelli.loop.adapters import simworld_commands as c  # noqa: E402,F401  (demo_lunch imports c from here)
from kokopelli.loop.adapters.simworld import (AGENT_ACTOR, AGENT_ASSET, MUG_ASSET, NpcSpec, SimWorldConfig,  # noqa: E402,F401
                                       SimWorldPhysics, SpawnSpec)
from kokopelli.loop.adapters.simworld_control import MoverIO  # noqa: E402,F401
from kokopelli.loop.adapters.simworld_math import angle_delta, distance_cm, heading_to  # noqa: E402,F401
from kokopelli.loop.physics import Vec3  # noqa: E402,F401

# The parts live in four files; every name stays importable from here (tools/bodies/demo_lunch.py, tests/agents/test_city_lunch.py).
# demo_lunch.py replaces lunch_wm.TwoBodySim and lunch_wm.Lunch: make_world() and main() below read those names from
# this module when they run, so keep both functions here.
from kokopelli.agents.lunch_text import (FORMAT_NOTE, IRIS_SITUATION, IRIS_WHO, LUNCH_TOPIC, MARA_SITUATION,  # noqa: E402,F401
                        RETRY_SHAPE, WM_PROMPT, LunchWords, QuietCast, lunch_cast, people)
from kokopelli.agents.lunch_sim import FRIEND_ACTOR, TwoBodySim  # noqa: E402,F401
from kokopelli.agents.lunch_parts import (HINTS, Body, LunchRecord, Mind, QwenBrain, SideBySide, SimWorldPair,  # noqa: E402,F401
                         controls_for, open_streams, place_or_point)

HEAR_M = live.HEAR_M
PATIENCE = 2           # steps a speaker waits for an answer before deciding again
FORGET_M = 25.0        # walk this far apart and running into each other again counts as meeting again


# ================================================================ the lunch

class Lunch(LunchWords, LunchRecord):
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
        self.fixes = set(getattr(args, "fixes", None) or ())
        self.on_change = bool(getattr(args, "decide_on_change", False))
        self.lines = []   # (speaker id, text) for every line said, in order

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
        if t == "pick_up" and "loops" in self.fixes:
            me = self.world.bodies()[mind.id].xy
            for oid, xy, held in self.world.objects():
                if oid != act["object"]:
                    continue
                if held:
                    who = "you are" if held == mind.id else f"{self.minds[held].name if held in self.minds else held} is"
                    raise ValueError(f"{oid} can't be picked up: {who} already holding it")
                if math.dist(me, xy) > REACH_M:
                    raise ValueError(f"{oid} is {rough(math.dist(me, xy))} away, out of reach; approach it first")

    def check_repeat(self, mind, act):
        mine = [t for k, t in self.lines if k == mind.id]
        theirs = [t for k, t in self.lines if k != mind.id]
        hit = fx.repeated(act["text"], mine, theirs)
        if hit:
            whose, line = hit
            said = "you just said" if whose == "you" else "you just heard"
            raise ValueError(f"{said} almost exactly that (\"{line[:120]}\"). Don't repeat it: say something new that "
                             f"answers or moves the conversation on, or choose another action")

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
                if "repeats" in self.fixes and act.get("type") == "say":
                    self.check_repeat(mind, act)
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
        self.lines.append((mind.id, text))
        clock = self.world.clock[:5]
        if "memory" in self.fixes:
            mind.talk.append(f"[{clock}] you: \"{text}\"")
        listeners = []
        other = self.minds[mind.other]
        if math.dist(me, bodies[other.id].xy) <= HEAR_M:
            other.heard.append(f"{mind.name} ({mind.id}): \"{text}\"")
            if "memory" in self.fixes:
                other.talk.append(f"[{clock}] {mind.name}: \"{text}\"")
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
                        if "memory" in self.fixes:
                            m.talk.append(f"[{clock}] {pname}: \"{line}\"")
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
            person = act["target"] == mind.other or (self.cast and act["target"] in self.cast.people)
            if person and "loops" in self.fixes:
                xy = self.world.bodies()[mind.other].xy if act["target"] == mind.other else dict(self.world.npcs()).get(act["target"])
                if xy and math.dist(me, xy) <= live.CHASE_M + 0.5:
                    name = self.minds[mind.other].name if act["target"] == mind.other else self.cast.people[act["target"]]["name"]
                    return self.face_other(mind) or {"type": "wait"}, f"You're already right next to {name}."
            mind.approaching = act["target"]
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
        if not self.on_change:
            return bool(mind.pending) or (mind.idle and mind.awaiting is None)
        # --decide-on-change: speech, an arrival, a meeting or a problem set `pending`; otherwise an idle mind decides
        # only when what it sees changed, or after QUIET_STEPS quiet steps
        if mind.pending:
            return True
        if not mind.idle or mind.awaiting is not None:
            return False
        return mind.quiet >= fx.QUIET_STEPS or fx.frame_diff(mind.seen, mind.decided_frame) > fx.FRAME_CHANGE

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
            mind.decided_frame, mind.quiet = mind.seen, 0
            n = mind.decisions
            if mind.seen:
                shutil.copy(mind.seen, self.out / "frames" / k / f"{self.step_no:04d}.png")
            if diary and not ("memory" in self.fixes and fx.restates(diary, mind.diary)):
                mind.diary.append(f"[{clock}] {diary}")
            mind.last_thought, mind.last_action = thought, act
            self.say(f"\n### {clock[:5]} — step {self.step_no} — {mind.name}"
                     + (" (answering)" if mind.pending == "heard" else "") + "\n"
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
                mind.quiet += mind.idle
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


# ================================================================ entry point
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
    ap.add_argument("--fixes", default="", help=f"behavior fixes, comma-separated, off by default: {','.join(fx.FIXES)} or all "
                                                "(kokopelli/agents/lunch_fixes.py)")
    ap.add_argument("--life", help="a lunch_life.py database: each person also knows their generated past (off by default)")
    ap.add_argument("--view-prompts", action="store_true",
                    help="one world-model prompt per view for Fern Court, each person described the same in both (lunch_text.py)")
    ap.add_argument("--decide-on-change", action="store_true",
                    help="idle minds decide only when their painted frame changes (or after a few quiet steps)")
    args = ap.parse_args(argv)
    try:
        args.fixes = sorted(fx.parse_fixes(args.fixes))
    except ValueError as e:
        ap.error(str(e))
    args.steps = max(1, int(round(args.minutes * 60 / args.step_s)))
    if abs(args.step_s * args.fps - round(args.step_s * args.fps)) > 1e-9:
        ap.error("--step-s times --fps must be a whole number of frames")
    return args

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
    return SimWorldPair(cfg, args.first["id"], args.second["id"], second, yaw(second), sim_class=TwoBodySim)


def main(argv=None):
    from kokopelli.wm.world_stream_multi import MultiWorldStream
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
