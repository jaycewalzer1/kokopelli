"""Behavior bench for the lunch (P5): the real Lunch loop on a toy world, scored for repeated lines, stuck loops, memory
use, the lunch routine and Qwen calls per simulated minute. No SimWorld and no Cosmos: the world is the test suite's
FakeWorld (real NavMap coordinates, toy walking at 1.6 m/s, 10 s steps) plus the two lunch bowls and the barista, and
the world model is the fake worker. This measures behavior only; it is not a quality test of the world model.

    .venv/bin/python -m tools.fable.lunch_bench run --brain parrot --out out/fable/P5/bench/parrot_off
    .venv/bin/python -m tools.fable.lunch_bench run --brain qwen --seed 7 --fixes all --out ...   # queue this (kokopelli/ops/gpu.py)
    .venv/bin/python -m tools.fable.lunch_bench score out/bodies/demo/runs/wm ...                 # any lunch run folder

With --brain qwen, Qwen3-VL-8B-Instruct-4bit (QwenBrain's sampling, temperature 0.4) gets a fixed random seed per call
and, instead of the fake world model's abstract frames, a real painted frame recorded by the owner's closed-loop run
(out/bodies/demo/runs/wm/frames/<agent>/, the n-th decision gets the n-th frame), so it sees a street, not a test pattern.
"""
import argparse
import json
import math
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STEP_S, FPS, SPEED = 10.0, 1, 1.6
RECORDED = ROOT / "out" / "bodies" / "demo" / "runs" / "wm" / "frames"
NEWS = {"mara": r"\b(bees?|hives?|swarm\w*)\b", "iris": r"\b(banners?|harvest fair)\b"}   # what each wants to hear about


# ================================================================ metrics

def load_events(run):
    return [json.loads(line) for line in (Path(run) / "events.jsonl").read_text().splitlines() if line.strip()]


def metrics(events, step_s=STEP_S):
    """Behavior numbers from a lunch events.jsonl (any lunch run: bench, golden or a real closed loop)."""
    from kokopelli.agents import lunch_fixes as fx
    says = [e for e in events if e["kind"] == "says"]
    acts = [e for e in events if e["kind"] == "act"]
    steps = max([e["step"] for e in events] or [0]) + 1
    repeats = echoes = 0
    by = {}
    for e in says:
        mine = by.setdefault(e["mind"], [])
        theirs = [x["text"] for x in says[:says.index(e)] if x["mind"] != e["mind"]]
        if any(fx.similarity(e["text"], t) >= fx.SAME_LINE for t in mine[-4:]):
            repeats += 1
        elif any(fx.similarity(e["text"], t) >= fx.SAME_LINE for t in theirs[-2:]):
            echoes += 1
        mine.append(e["text"])
    # stuck loops: the longest run of the same non-speech action by one mind over its consecutive decisions
    longest, run_of = 0, {}
    for e in acts:
        key = None if e["action"]["type"] == "say" else json.dumps(e["action"], sort_keys=True)
        prev, n = run_of.get(e["mind"], (None, 0))
        n = n + 1 if key and key == prev else (1 if key else 0)
        run_of[e["mind"]] = (key, n)
        longest = max(longest, n)
    # memory: a question about the other's news asked after the other already told it
    reasks = 0
    for i, e in enumerate(says):
        other_told = any(x["mind"] != e["mind"] and re.search(NEWS.get(e["mind"], "^$"), x["text"].lower())
                         for x in says[:i])
        if other_told and "?" in e["text"] and re.search(NEWS.get(e["mind"], "^$"), e["text"].lower()):
            reasks += 1
    calls = sum(e["kind"] in ("decision", "bad_reply") for e in events)
    routine = {}
    for e in events:
        if e["kind"] == "outcome" and e.get("phase") == "arrived":
            routine.setdefault(f"{e['mind']}_first_arrival_step", e["step"])
        if e["kind"] == "act" and e["action"]["type"] == "pick_up":
            routine.setdefault(f"{e['mind']}_first_pick_up_step", e["step"])
    first_line = next((e["step"] for e in says), None)
    minutes = steps * step_s / 60
    return {"steps": steps, "lines": len(says), "repeated_lines": repeats, "echoed_lines": echoes,
            "repeat_share": round((repeats + echoes) / len(says), 3) if says else 0.0,
            "longest_loop": longest, "reasked_answered_news": reasks,
            "decisions": sum(e["kind"] == "decision" for e in events), "bad_replies": sum(e["kind"] == "bad_reply" for e in events),
            "qwen_calls": calls, "calls_per_sim_minute": round(calls / minutes, 2) if minutes else None,
            "actions": dict(Counter(e["action"]["type"] for e in acts)), "first_line_step": first_line, **routine}


# ================================================================ the toy world and the brains

def bench_world(nav, folder, cast):
    import numpy as np  # noqa: F401  (test_city_lunch needs it importable)
    from tests.agents import test_city_lunch as tcl
    from kokopelli.agents.live_wm import REACH_M

    class BenchWorld(tcl.FakeWorld):
        """FakeWorld plus the two lunch bowls on the cafe's doorstep, picking up and putting down."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            mx, my = nav.doors["kettle_cafe"]
            self.bowls = {f"lunch_bowl_{k}": [mx + 1.2 + 0.6 * k, my + 1.2] for k in (1, 2)}
            self.holder = {b: None for b in self.bowls}

        def step(self, actions):
            # FakeWorld reads its step length from test_city_lunch's globals: set them for this call only, so the
            # tests that share the module (the golden run) keep theirs
            saved = tcl.STEP_S, tcl.FRAMES_PER_STEP
            tcl.STEP_S, tcl.FRAMES_PER_STEP = STEP_S, int(STEP_S * FPS)
            try:
                outcomes, frames = super().step(actions)
            finally:
                tcl.STEP_S, tcl.FRAMES_PER_STEP = saved
            for k, a in actions.items():
                if a["type"] == "interact":
                    b = a.get("target_id")
                    ok = b in self.bowls and self.holder[b] is None and math.dist(self.pos[k], self.bowls[b]) <= REACH_M
                    if ok:
                        self.holder[b] = k
                    outcomes[k] = {"status": "completed" if ok else "failed", "phase": None,
                                   "detail": "" if ok else f"couldn't pick up {b}"}
                elif a["type"] == "drop_object":
                    for b, h in self.holder.items():
                        if h == k:
                            self.holder[b], self.bowls[b] = None, list(self.pos[k])
            return outcomes, frames

        def objects(self):
            return [(b, tuple(self.pos[self.holder[b]]) if self.holder[b] else tuple(xy), self.holder[b])
                    for b, xy in self.bowls.items()]

    npcs = [(pid, tuple(nav.doors[p["stay_at"]])) for pid, p in cast.people.items() if "stay_at" in p] if cast else []
    return BenchWorld(nav, folder, {"mara": nav.doors["fern_common"], "iris": nav.doors["fern_bakery"]},
                      speed=SPEED, npcs=npcs)


NEW_LINES = ["Shall we grab the window table?", "The soup smells like nettles and pepper.", "I walked past the plum tree "
             "this morning.", "Market Hall was packed at nine.", "My sister is visiting next weekend.", "Did you see the "
             "new mural by the library?", "I could sit in this sun all afternoon.", "Let's split a flatbread."]


class ParrotBrain:
    """A fake brain with the failure modes seen in real runs: walks to lunch, then repeats its own line, echoes what it
    heard, walks up to the other again and again, and grabs the first bowl. Fixes are measured against it on CPU."""

    def __init__(self):
        self.n = Counter()

    def ask(self, prompt, image):
        from tests.agents import test_city_lunch as tcl
        name = re.match(r"You are (\w+)", prompt).group(1)  # pyright: ignore[reportOptionalMemberAccess]  # every prompt starts this way
        other = "Iris" if name == "Mara" else "Mara"
        self.n[name] += 1
        n = self.n[name]
        heard = tcl.section(prompt, "What you heard:\n", "\n\nYour notes")
        close = tcl.section(prompt, "Who is right next to you (close enough to talk):\n", "\nAnyone or anything")
        rejected = "Your last reply was rejected" in prompt
        if other.lower() not in close:
            if "You are at The Kettle" in prompt:
                return json.dumps({"thought": "find her", "action": {"type": "approach", "target": other.lower()}})
            return json.dumps({"thought": "lunch", "action": {"type": "go_to", "place": "kettle_cafe"}})
        if rejected:   # told it repeated itself: say something new
            return json.dumps({"thought": "new", "action": {"type": "say", "text": NEW_LINES[n % len(NEW_LINES)]}})
        if other in heard and n % 3 == 0:   # echo the other's last line
            line = re.findall(r'"(.*)"', heard)[-1]
            return json.dumps({"thought": "echo", "action": {"type": "say", "text": line}})
        if other in heard or n % 4 == 1:
            return json.dumps({"thought": "same again", "action": {"type": "say",
                               "text": f"{other}! How are you, and how is everything going today?"},
                               "diary": f"Met {other} at The Kettle, lovely to catch up."})
        if n % 4 == 2:
            return json.dumps({"thought": "grab food", "action": {"type": "pick_up", "object": "lunch_bowl_1"}})
        return json.dumps({"thought": "closer", "action": {"type": "approach", "target": other.lower()}})

    def unload(self):
        pass


class SeededQwen:
    """QwenBrain with a fixed seed per call, shown a recorded painted frame instead of the fake world model's."""

    def __init__(self, weights, seed, frames=RECORDED):
        from kokopelli.agents.lunch_parts import QwenBrain
        self.inner, self.seed, self.calls = QwenBrain(weights), seed, Counter()
        self.frames = {k: sorted(p for p in (Path(frames) / k).glob("[0-9]*.png")) for k in ("mara", "iris")}

    def ask(self, prompt, image):
        import mlx.core as mx
        k = re.match(r"You are (\w+)", prompt).group(1).lower()  # pyright: ignore[reportOptionalMemberAccess]  # every prompt starts this way
        n = self.calls[k]
        self.calls[k] += 1
        shown = self.frames.get(k) or []
        img = str(shown[min(n, len(shown) - 1)]) if shown else image
        mx.random.seed(self.seed * 10007 + sum(self.calls.values()))
        return self.inner.ask(prompt, img)

    def unload(self):
        self.inner.unload()


# ================================================================ one run

def run(argv=None):
    from kokopelli.agents import lunch_wm as lw
    from kokopelli.wm.world_stream_multi import MultiWorldStream
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", choices=("parrot", "scripted", "qwen"), default="parrot")
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--minutes", type=float, default=4.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--weights", default=str(ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit"))
    ap.add_argument("--no-npcs", action="store_true")
    a, rest = ap.parse_known_args(argv)
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out / "film", ignore_errors=True)
        (out / "events.jsonl").unlink(missing_ok=True)
        (out / "transcript.md").unlink(missing_ok=True)
    args = lw.build_args(["--minutes", str(a.minutes), "--step-s", str(STEP_S), "--fps", str(FPS), "--size", "64x32",
                          "--fake-wm", "--out", str(out), "--seed", str(a.seed), "--weights", a.weights, *rest])
    nav = lw.NavMap()
    lw.people(args, nav)
    cast = None if a.no_npcs else lw.lunch_cast(nav)
    world = bench_world(nav, out / "sim", cast)
    if a.brain == "qwen":
        brain = SeededQwen(a.weights, a.seed)
    elif a.brain == "scripted":
        from tests.agents import test_golden_lunch as tg
        brain = tg.GoldenBrain()
    else:
        brain = ParrotBrain()
    wm = MultiWorldStream(out_dir=out / "wm", fake=True)
    try:
        lw.open_streams(wm, args, ["mara", "iris"])
        lw.Lunch(args, world, wm, brain, out=out, nav=nav, cast=cast).run(args.steps)
    finally:
        wm.close()
    shutil.rmtree(out / "sim", ignore_errors=True)   # toy frames, nothing to keep
    m = metrics(load_events(out))
    m.update(brain=a.brain, seed=a.seed, fixes=args.fixes, decide_on_change=args.decide_on_change,
             life=getattr(args, "life", None), world="FakeWorld (toy), fake world model; not a world-model test")
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    print(json.dumps(m))
    return m


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "score":
        for d in argv[1:]:
            print(d, json.dumps(metrics(load_events(d))))
        return
    if argv and argv[0] == "run":
        argv = argv[1:]
    run(argv)


if __name__ == "__main__":
    main()
