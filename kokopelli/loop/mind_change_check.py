"""Does real Qwen notice real changes, ignore non-changes, and stop copying its history once it's told what changed?

    PYTHONPATH=.claude/worktrees/wm-agent-loop:. .venv/bin/python -m kokopelli.loop.mind_change_check    # go through the GPU queue

Each moment has a known answer, so this doesn't depend on a scene where something happens to occur:
    same:  one frame repeated. Nothing changed, by construction.
    next:  consecutive ticks of a real Cosmos run. Should mostly be nothing, though the picture does soften.
    event: the start of a clip against its later frames. A real event may or may not fit in 0.67 seconds.
    cut:   the Cosmos scene, then a different clip. Something obviously changed.
Appraisals plant "curious" and "uneasy" as the current mood. If the reply still just repeats the planted feeling, copying remains.

    --notice-only --wide    only the noticing, on a bigger labelled set, for each prompt in PROMPTS
"""
import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from kokopelli.loop.mind_check import Ask
from kokopelli.mind.feeling import CHANGE, MAX_CHANGE_CHARS, appraisal_prompt, parse_appraisal, parse_change, settle
from kokopelli.loop.run_mind import measured_qwen

KOKOPELLI = Path(__file__).resolve().parents[2]
REAL = KOKOPELLI / ".claude/worktrees/wm-agent-loop/runs/wmloop_real_20"
CLIPS = KOKOPELLI / "out/world_data_20261104/clips"
OUT = KOKOPELLI / "out/mind/change_check"
SAMPLES = (2, 5, 8, 10, 12, 15)
EVENTS = {"p03": "A ceramic mug slides off a counter and shatters on a tile floor.", "p05": "A candle flame goes out as a window blows open.",
          "p06": "A person opens a front door, steps outside and closes it.", "p07": "A toddler knocks over a stack of wooden blocks."}
CUTS = {"p03": EVENTS["p03"], "p05": EVENTS["p05"], "p20": "Storm clouds gather over a wheat field.", "p21": "A dog runs across a backyard."}
PLANTED = ("curious", "uneasy")
# The first run missed an obvious cut while saying nothing changed, so this asks it to look at both ends before judging.
DESCRIBE = ("The first image is from a moment ago. The others are what you see now. First say in a few words what the first image "
            "shows and what the last image shows. Then say whether anything actually changed: someone arrived or left, something "
            "moved somewhere new, something happened? Small movements, camera drift and blur don't count. Reply with one JSON object "
            'and nothing else:\n{"before": "<a few words>", "now": "<a few words>", "changed": true or false, '
            '"what": "<one sentence about what changed, or empty>"}')
PROMPTS = {"current": CHANGE, "describe": DESCRIBE}
# Checked by eye: both of these really happen within the clip's frames, and the other two clips show no event in time.
SEEN = {"p03": True, "p05": False, "p06": True, "p07": False}
WHY = "I'm still taking in what's around me."


def tick_frames(tick):
    return sorted(str(path) for path in (REAL / "ticks" / f"{tick:04d}").glob("wm_00_sample_*.png"))


def clip_frames(name):
    folder = OUT / "frames" / name
    if not list(folder.glob("*.png")):
        folder.mkdir(parents=True, exist_ok=True)
        chosen = "+".join(f"eq(n\\,{index})" for index in (0, *SAMPLES))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(CLIPS / f"{name}_s101.mp4"), "-vf", f"select='{chosen}'", "-fps_mode", "vfr", str(folder / "%02d.png")], check=True)
    return sorted(str(path) for path in folder.glob("*.png"))


def wide_cases():
    """Only moments whose answer is certain: real ticks where nothing was scripted, and cuts to an unrelated clip."""
    for tick in (1, 2, 3, 4, 5):
        yield {"kind": "same", "name": f"tick {tick}", "images": [tick_frames(tick)[-1]] * 7, "truth": None}
    for tick in range(1, 11):
        kind = "next" if tick < 8 else "next_decayed"
        yield {"kind": kind, "name": f"tick {tick} to {tick + 1}", "images": [tick_frames(tick)[-1], *tick_frames(tick + 1)], "truth": None}
    clips = sorted({path.name.split("_")[0] for path in CLIPS.glob("p*_s101.mp4")})
    for index, name in enumerate(clips[:20]):
        tick = 1 + index % 4
        yield {"kind": "cut", "name": f"tick {tick} to {name}", "images": [tick_frames(tick)[-1], *clip_frames(name)[1:]], "truth": name}


def notice_only(agent):
    results = {}
    for label, prompt in PROMPTS.items():
        rows = []
        for case in wide_cases():
            raw = agent.decide(Ask(prompt, case["images"], [], "", 0))
            noticed, readable = parse_change(raw)
            rows.append({"kind": case["kind"], "name": case["name"], "noticed": noticed, "unreadable": not readable, "raw": raw,
                         "generation_tokens": agent.last_usage and agent.last_usage.get("generation_tokens")})
            print(label, case["name"], noticed, flush=True)
        score = {}
        for row in rows:
            kind = score.setdefault(row["kind"], [0, 0])
            kind[0] += row["noticed"] is not None
            kind[1] += 1
        results[label] = {"noticed_a_change": {kind: f"{hits} of {total}" for kind, (hits, total) in score.items()},
                          "unreadable": sum(row["unreadable"] for row in rows), "rows": rows}
        (OUT / "notice_wide.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({label: {key: value for key, value in result.items() if key != "rows"} for label, result in results.items()}, indent=2))


def cases():
    for tick in (1, 2, 3):
        frame = tick_frames(tick)[-1]
        yield {"kind": "same", "name": f"tick {tick}", "images": [frame] * 7, "truth": None}
    for tick in (1, 2, 3, 4):
        yield {"kind": "next", "name": f"tick {tick} to {tick + 1}", "images": [tick_frames(tick)[-1], *tick_frames(tick + 1)], "truth": None}
    for name, truth in EVENTS.items():
        yield {"kind": "event", "name": name, "images": clip_frames(name), "truth": truth}
    for name, truth in CUTS.items():
        yield {"kind": "cut", "name": name, "images": [tick_frames(2)[-1], *clip_frames(name)[1:]], "truth": truth}


def history(feeling):
    return [{"kind": "appraisal", "t": f"earlier {index}", "feeling": feeling, "intensity": 0.3, "why": WHY} for index in range(5)]


def summarize(results):
    noticed, moved = {}, Counter()
    for result in results:
        kind = noticed.setdefault(result["kind"], [0, 0])
        kind[0] += result["noticed"] is not None
        kind[1] += 1
        for trial in result["appraisals"]:
            reply = trial["reported"]
            moved["trials"] += 1
            moved["unreadable"] += not reply
            moved["same_word_as_planted"] += bool(reply) and reply["feeling"] == trial["planted"]
            moved["intensity_moved"] += bool(reply) and reply["intensity"] != 0.3
    return {"noticed_a_change": {kind: f"{hits} of {total}" for kind, (hits, total) in noticed.items()}, "appraisals": dict(moved)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notice-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    agent = measured_qwen()
    if args.notice_only:
        return notice_only(agent)
    prompt = next(event["data"]["prompt"] for event in map(json.loads, (REAL / "events.jsonl").read_text().splitlines())
                  if event["kind"] == "agent_input" and event["tick"] == 2)
    results = []
    for case in cases():
        raw = agent.decide(Ask(CHANGE, case["images"], [], "", 0))
        noticed, readable = parse_change(raw)
        result = {**case, "images": len(case["images"]), "noticed": noticed, "raw": None if readable else raw, "appraisals": []}
        if case["truth"]:
            # A missed change still gets told, so this measures the appraisal separately from the noticing.
            told = noticed or case["truth"]
            for planted in PLANTED:
                reply = agent.decide(Ask(appraisal_prompt(prompt, history(planted), told), case["images"][1:], [], "", 0))
                reported = parse_appraisal(reply)
                settled = reported and settle({"feeling": planted, "intensity": 0.3, "why": WHY}, reported)
                result["appraisals"].append({"planted": planted, "reported": reported, "settled": settled, "raw": None if reported else reply})
        results.append(result)
        print(json.dumps(result), flush=True)
        (OUT / "results.json").write_text(json.dumps({"summary": summarize(results), "results": results}, indent=2))
    print(json.dumps(summarize(results), indent=2))


if __name__ == "__main__":
    main()
