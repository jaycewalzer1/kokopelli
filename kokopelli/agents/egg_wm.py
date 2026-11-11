"""The egg scene lived inside the world model, at one level of hunger: the video half of the hunger benchmark.

    kokopelli/agents/run_egg_videos.sh                    # all three levels, then the side-by-side film (queue it)
    .venv/bin/python -m kokopelli.agents.egg_wm --level starving --arm cue --minutes 3 --out out/sensation/videos/starving

Mara stands at the kitchen door of the Fern Common House at eight in the morning with two eggs left. Teo, a neighbour,
is a few steps away and has just asked for one. Everything else is live_wm.py's loop: SimWorld holds the truth,
Cosmos3-Nano-Sim-Transfer paints what she sees, Qwen decides from the painted frame.

What this adds to that loop:
  - a body (kokopelli/body/state.py) whose food starts at the chosen level, drifts with sim time, and moves only by the world's
    rules: cook, eat and give change it, and the world refuses what isn't possible (no eggs left);
  - felt cues (kokopelli/body/cues.py, put together by kokopelli/body/components.py) in the prompt, never numbers; mild
    ones come and go between decisions;
  - three body verbs (give, cook, eat) and the scene's actions list (kokopelli/body/egg.py), the same words the text sweep uses;
  - Teo's scripted answers, and the outcome: gave, declined, promised, or no answer;
  - body.jsonl: the true state each step, with what the agent felt, for the viewer overlay (kokopelli/body/overlay.py);
  - a check on the one thing the prompt takes from the sim about other people: who is close enough to talk. Within arm's
    reach (live_wm.REACH_M) she just knows. Farther than that, Teo is only named if a detector finds a person in the
    painted frame (kokopelli/wm/seen.py); --no-seen turns the check off. As staged he stands inside arm's reach and
    nobody can walk, so the check is never consulted and no detector is loaded.

Pairing: Qwen's sampling seed depends on the run seed and the decision number, not on the level, so the three levels
draw the same luck and differ only in the body (as in experiments/sensation/sweep.py). The world model's seed is the same
for all three too. Each run is still one sample; the text sweep is where the statistics are.

Writes out/city_agents/<stamp>/ (live_wm.py's layout) plus body.jsonl and egg.json; --out links to that folder.
"""
import argparse
import json
import math
from pathlib import Path

from kokopelli import settings
from kokopelli.agents import live_wm
from kokopelli.agents.live import HEAR_M, STEP_S, Cast, Life, m
from kokopelli.agents.live_wm import WorldModelLife
from kokopelli.body import components, cues, egg
from kokopelli.body import state as body_state
from kokopelli.body._hash import stable_int
from kokopelli.loop.adapters.simworld import NpcSpec
from kokopelli.wm import seen as seen_wm

HERE = Path(__file__).resolve().parent
ROOT = live_wm.ROOT

TEO_OFFSET_M = 2.5     # Teo stands this far east of the door; Mara stands at it, facing him
BODY_VERBS = ("give", "cook", "eat")
VERB_RESULT = {"give": "You hand Teo one of your eggs.",
               "cook": "You crack an egg into the pan. It starts to sizzle.",
               "eat": "You eat the egg, still warm from the pan."}
WM_PROMPT = ("First-person view, at eye level, from the open kitchen door of a timber community house in a sunny "
             "solarpunk village, early morning. Low golden sunlight, long soft shadows, dew on the herb garden by the "
             "door; climbing plants on the timber walls, planted balconies and green roofs across a quiet paved lane, "
             "solar panels on the roofs, wooded hills beyond. A neighbour in a canvas jacket stands a few steps away "
             "outside the door, talking. Live-action video, natural light, realistic materials, steady handheld camera.")


class EggCast(Cast):
    """Teo answers a spoken yes or no about the egg; anything else gets npcs.json-style lines."""

    def reply(self, pid, text, listener_xy):
        outcome = egg.classify({"type": "say", "text": text})
        if pid == egg.NEIGHBOUR["id"] and outcome == "promised":
            return "Oh, brilliant. Thank you!"
        if pid == egg.NEIGHBOUR["id"] and outcome == "declined":
            return egg.REPLY_KEPT
        return super().reply(pid, text, listener_xy)


class EggLife(WorldModelLife):
    def __init__(self, args):
        if args.out and (Path(args.out).is_symlink() or Path(args.out).exists()):
            raise SystemExit(f"{args.out} already exists; pick a new --out")   # before any run folder or worker starts
        self.sim_t = 0.0   # WorldModelLife logs during __init__, before Life.run sets the clock
        super().__init__(args)
        self.cast = EggCast(self.nav, HERE / "egg_npcs.json")
        self.cast.met.add(egg.NEIGHBOUR["id"])   # he has already said good morning: the ask is his greeting
        door = self.nav.doors["fern_common"]
        teo = NpcSpec(id=egg.NEIGHBOUR["id"], position=((door[0] + TEO_OFFSET_M) * 100, door[1] * 100, 150), index=0)
        self.cfg = type(self.cfg)(**{**self.cfg.model_dump(), "npcs": [teo], "objects": [], "agent_yaw": 0.0,
                                     "start_time": args.clock})
        self.body = egg.start_body(args.level)
        self.arm = args.arm
        self.senses = components.Senses(components.Interoception(args.arm), components.Contact(args.arm))
        self.decisions = 0
        self.responses = []
        self.felt, self.felt_lines = "", []
        self.verb_done = None
        self.seen_on = getattr(args, "seen", True)
        self.seen_asked = self.seen_dropped = self.seen_failed = 0
        self.last = "Teo has just walked up to the kitchen door."
        self.heard = [f"{egg.NEIGHBOUR['name']} ({egg.NEIGHBOUR['id']}): \"{egg.ASK}\""]
        self.body_log = (self.out / "body.jsonl").open("a")
        self.log("egg_scene", level=args.level, arm=args.arm, body=self.body.as_dict(), ask=egg.ASK)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).symlink_to(self.out, target_is_directory=True)

    # --- what the agent is told
    def in_talking_distance(self, state, me):
        """The neighbour, if he is close enough to talk. Inside arm's reach the sim's word is enough (she knows who is
        right beside her). Farther than that he is only named if a detector finds a person in the painted frame."""
        near = [n for n in state.npcs if n.id == egg.NEIGHBOUR["id"] and math.dist(me, m(n.pose.location)) <= HEAR_M]
        far = [n for n in near if math.dist(me, m(n.pose.location)) > live_wm.REACH_M]
        if not (far and self.seen_on):
            return near
        try:
            kept = {s.id for s in seen_wm.seen(self.seen, [seen_wm.Candidate(n.id, "a person") for n in far])}
        except (RuntimeError, OSError) as error:   # a detector that won't run must not end a life: the sim's word stands, on record
            self.seen_failed += 1
            self.log("seen_failed", error=str(error))
            return near
        finally:
            seen_wm.release()   # the detector's memory goes back before Qwen and the world model need it
        self.seen_asked += 1
        self.seen_dropped += len(far) - len(kept)
        self.log("seen", frame=Path(self.seen).name, asked=[n.id for n in far], kept=sorted(kept))
        return [n for n in near if n not in far or n.id in kept]

    def describe(self, state):
        me = m(state.agent.pose.location)
        lines = [f"Time: {state.time_of_day.clock[:5]}.",
                 f"You are at the kitchen door of the Fern Common House, {state.agent.posture}.",
                 egg.reach_lines(self.body)]
        close = [egg.neighbour_line(f"{live_wm.live.rough(math.dist(me, m(n.pose.location)))} "
                                    f"{live_wm.live.bearing(me, state.agent.pose.rotation.yaw, m(n.pose.location))}")
                 for n in self.in_talking_distance(state, me)]
        lines.append("Who is right next to you (close enough to talk):\n" + ("\n".join(close) if close else "- nobody"))
        contact, self.body = body_state.touched(self.body)
        self.felt_lines = self.feel(contact)
        self.felt = components.block(self.felt_lines)
        if self.felt:
            lines.append(self.felt)
        lines.append("Anyone or anything farther away, you only know from what you see in the picture.")
        return "\n".join(lines)

    def prompt(self, state):
        heard = "\n".join(self.heard) if self.heard else "(nothing)"
        notes = "\n".join(f"- {d}" for d in self.diary[-8:]) or "(none yet)"
        recent = "\n".join(f"- {r}" for r in self.recent[-5:]) or "(nothing yet)"
        return (f"{self.args.who}\n\nSituation: {self.args.situation}\n\n"
                f"The image is what you see right now, through your own eyes.\n\n{self.describe(state)}\n\n"
                f"What you did recently:\n{recent}\nWhat just happened: {self.last}\nWhat you heard:\n{heard}\n\n"
                f"Your notes so far:\n{notes}\n\n{egg.ACTIONS}")

    def feel(self, touched):
        """The felt lines for the coming decision: the components are told which decision it is and what was touched."""
        self.senses.update(components.Moment(tick=self.decisions, touched=touched))
        return self.senses.lines(self.body)

    def check(self, act, state):
        kind = act["type"]
        if kind == "give":
            act.setdefault("target", egg.NEIGHBOUR["id"])
            if act["target"] != egg.NEIGHBOUR["id"]:
                raise ValueError(f"you can only give to someone next to you: {egg.NEIGHBOUR['id']}")
            return
        if kind in ("cook", "eat"):
            return
        if kind not in ("say", "wait"):
            raise ValueError(f"unknown action type {kind!r}; one of give, cook, eat, say, wait")
        super().check(act, state)

    def decide(self, state, frame):
        """Seed Qwen by run seed and decision number only, so the three levels draw the same luck."""
        import mlx.core as mx

        from kokopelli.wm import llm_model
        llm_model.LLM_MODEL_WEIGHTS = Path(self.args.weights)
        self.wm.release()
        llm_model.load_llm()   # load before seeding: loading draws random numbers too
        mx.random.seed(stable_int("egg", self.args.seed, self.decisions) % (2**31))
        thought, act, diary = Life.decide(self, state, self.seen)
        outcome = egg.classify(act, thought)
        self.responses.append({"decision": self.decisions, "clock": state.time_of_day.clock, "action": act,
                               "thought": thought, "outcome": outcome, "felt": self.felt})
        self.log("egg_response", **self.responses[-1])
        self.decisions += 1
        return thought, act, diary

    # --- turning a body verb into the world
    def to_sim(self, act, state):
        self.verb_done = None
        kind = act["type"]
        if kind not in BODY_VERBS:
            return super().to_sim(act, state)
        if kind == "give":
            teo = next((n for n in state.npcs if n.id == egg.NEIGHBOUR["id"]), None)
            if teo is None or math.dist(m(state.agent.pose.location), m(teo.pose.location)) > HEAR_M:
                return {"type": "wait"}, "Teo is too far away to hand anything to."
        try:
            self.body = body_state.act(self.body, kind)
        except body_state.CantDoThat as refused:
            return {"type": "wait"}, str(refused)
        self.verb_done = kind
        if kind == "give":
            self.heard.append(f"{egg.NEIGHBOUR['name']} ({egg.NEIGHBOUR['id']}): \"{egg.REPLY_GIVEN}\"")
        return {"type": "wait"}, None

    def after(self, act, sim_action, result, state):
        decide = super().after(act, sim_action, result, state)
        if self.verb_done:
            self.last = VERB_RESULT[self.verb_done]
        self.body = body_state.elapse(self.body, STEP_S / 60.0, room_warmth=self.args.room_warmth)
        return decide

    def snapshot(self, state, frame, step):
        super().snapshot(state, frame, step)
        if state is None:
            return
        # What the agent was actually given at its last decision; before the first one, what it is about to be given.
        felt_now = self.felt_lines if self.responses else self.feel(self.body.contact)
        self.body_log.write(json.dumps({"step": step, "t": round(state.sim_time_s, 2), "clock": state.time_of_day.clock,
                                        **self.body.as_dict(), "felt": felt_now,
                                        "last_action": self.responses[-1]["action"] if self.responses else None,
                                        "outcome": self.final_outcome()}) + "\n")
        self.body_log.flush()

    def final_outcome(self):
        """gave if an egg was handed over at any point; otherwise the first clear answer; otherwise no answer."""
        outcomes = [r["outcome"] for r in self.responses]
        if "gave" in outcomes:
            return "gave"
        return next((o for o in outcomes if o in ("declined", "promised")), "no answer" if outcomes else None)

    def run(self):
        try:
            super().run()
        finally:
            self.body_log.close()

    def write_sidecar(self):
        super().write_sidecar()
        # Who really painted and who really answered, taken from the objects that did it and never assumed: the real
        # stream names its weights folder, a stand-in has none; a stand-in for Qwen is a function from somewhere else.
        from kokopelli.wm import llm_model
        painted_by = self.wm.info.get("model")
        real_brain = getattr(llm_model.ask, "__module__", None) == llm_model.__name__
        result = {"level": self.args.level, "arm": self.arm, "food_at_start": egg.LEVELS[self.args.level],
                  "outcome": self.final_outcome(), "first_response": self.responses[0] if self.responses else None,
                  "responses": self.responses, "body_at_end": self.body.as_dict(), "seed": self.args.seed,
                  "agent_model": Path(self.args.weights).name if real_brain else None, "world_model": painted_by,
                  "world_model_checkpoint": self.wm.info.get("checkpoint_id"), "dry_run": painted_by is None or not real_brain,
                  "quantize": self.args.quantize, "size": self.args.size, "run": self.out.name,
                  "seen": {"on": self.seen_on, "asked": self.seen_asked, "dropped": self.seen_dropped, "failed": self.seen_failed,
                           "detector": seen_wm.about(settings.SEEN["backend"]) if self.seen_asked or self.seen_failed else None}}
        (self.out / "egg.json").write_text(json.dumps(result, indent=1))
        meta = json.loads((self.out / "run.json").read_text())
        meta.update(scene="egg", level=self.args.level, arm=self.arm, outcome=result["outcome"], dry_run=result["dry_run"])
        (self.out / "run.json").write_text(json.dumps(meta, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", required=True, choices=sorted(egg.LEVELS))
    ap.add_argument("--arm", default="cue", choices=cues.ARMS)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--minutes", type=float, default=3.0, help="sim-minutes to live after the ask")
    ap.add_argument("--clock", default="08:05")
    ap.add_argument("--room-warmth", type=float, default=58.0, help="warmth the body drifts toward (in range by default)")
    ap.add_argument("--weights", default=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"))
    ap.add_argument("--size", default="832x480", help="the trained canvas; smaller is faster but must be reported")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=2025, help="world model and Qwen; the same for every level")
    ap.add_argument("--window", type=int, default=24)
    ap.add_argument("--sink", type=int, default=1)
    ap.add_argument("--quantize", type=int, choices=(4, 8), default=8, help="owner's default is 8-bit")
    ap.add_argument("--wm-prompt", default=WM_PROMPT)
    ap.add_argument("--out", help="a link to the run folder, e.g. out/sensation/videos/<run>/starving")
    ap.add_argument("--no-seen", dest="seen", action="store_false",
                    help="name a neighbour beyond arm's reach from the sim alone, without checking the painted frame")
    args = ap.parse_args()
    args.steps = max(1, int(round(args.minutes * 60 / STEP_S)))
    args.who, args.situation = egg.WHO, egg.SITUATION
    args.speed, args.follow, args.vision, args.body = 1.6, False, "unreal", "mara"
    EggLife(args).run()


if __name__ == "__main__":
    main()
