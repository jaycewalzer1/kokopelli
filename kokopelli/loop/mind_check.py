"""What mocks can't show: do a real model's feelings follow events, and does a feeling change the next action?

    python -m kokopelli.loop.mind_check out/mind/qwen_8          # reads the run, no model needed
    python -m kokopelli.loop.mind_check out/mind/qwen_8 --flip   # asks the model again; go through the GPU queue

The flip test is the one that can show cause. It re-asks each real decision with the same prompt and frames at
temperature 0, changing only the latest feeling. "content" against "calm" is the placebo: a near-synonym should change
little, so any effect only counts if "terrified" against "calm" changes more actions than the placebo does.

For a trained model, run these on a base run, so every model answers identical moments:
    python -m kokopelli.loop.mind_check out/mind/base --replay                          # should reproduce the run; the noise floor
    python -m kokopelli.loop.mind_check out/mind/base --replay --flip --weights <run>/fused
    python -m kokopelli.loop.mind_check out/mind/base --compare out/mind/adapter        # two separate runs on the same seed

Replay shows whether replies stay valid and whether behaviour moved. It can't show whether it moved in a healthier
direction, because the loop has no variables to keep in range. See "Known gaps" in experiments/homeostatic/HANDOFF.md.
"""
import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev

from kokopelli.mind.feeling import decision_prompt, parse_action, read_rows, timeline

MIN_FLIP_DECISIONS = 20
MIN_FLIP_GAP = 0.2
WHY = "That's how this moment feels."
CALM = {"feeling": "calm", "intensity": 0.2}
PLACEBO = {"feeling": "content", "intensity": 0.2}
STRONG = {"feeling": "terrified", "intensity": 0.9}


@dataclass
class Ask:
    prompt: str
    images: list
    visible: list
    now: str
    tick: int
    retry_error: str | None = None


def _rate(hits, total):
    return {"hits": hits, "total": total, "rate": round(hits / total, 3) if total else None}


def _events(folder):
    return [json.loads(line) for line in (Path(folder) / "events.jsonl").read_text().splitlines()]


def stats(folder):
    """From the run's own record. Patterns here are associations: feelings and events share the same run."""
    rows = read_rows(Path(folder) / "feelings.jsonl")
    appraisals = [row for row in rows if row["kind"] == "appraisal"]
    felt = [row for row in appraisals if row["feeling"]]
    choices = {row["tick"]: row for row in rows if row["kind"] == "choice"}
    counts = Counter(row["feeling"] for row in felt)

    asked = [row for row in felt if not row.get("carried")]
    grounded = sum(any(thing.replace("_", " ") in row["why"].lower() for thing in row["visible"]) for row in asked)
    # Did the feeling move more on ticks where something had just happened than on ticks where nothing had?
    moved, still = [0, 0], [0, 0]
    for previous, current in zip(felt, felt[1:]):
        action = choices.get(previous["tick"], {}).get("action") or {}
        eventful = set(previous["visible"]) != set(current["visible"]) or action.get("type", "wait") != "wait"
        bucket = moved if eventful else still
        bucket[0] += previous["feeling"] != current["feeling"]
        bucket[1] += 1
    by_feeling = {}
    for row in felt:
        action = (choices.get(row["tick"]) or {}).get("action") or {}
        if choices.get(row["tick"], {}).get("decided"):
            by_feeling.setdefault(row["feeling"], Counter())[action.get("type", "invalid")] += 1
    return {"appraisals": len(appraisals), "changes_noticed": sum(1 for row in appraisals if row.get("change")), "invalid": len(appraisals) - len(felt), "distinct_feelings": len(counts),
            "top_feeling_share": round(counts.most_common(1)[0][1] / len(felt), 3) if felt else None, "feelings": dict(counts),
            "intensity_mean": round(mean(row["intensity"] for row in felt), 3) if felt else None,
            "intensity_spread": round(pstdev(row["intensity"] for row in felt), 3) if felt else None,
            "why_names_something_in_view": _rate(grounded, len(asked)),
            "feeling_changed_after_something_happened": _rate(*moved), "feeling_changed_after_nothing_happened": _rate(*still),
            "actions_by_feeling": {name: dict(actions) for name, actions in by_feeling.items()}}


def _with_feeling(rows, tick, feeling):
    """The rows the agent had when it decided at this tick, with the latest appraisal swapped for the given feeling."""
    before = [row for row in rows if row["tick"] < tick or (row["tick"] == tick and row["kind"] == "appraisal")]
    latest = len(before) - 1
    return before[:latest] + [{**before[latest], **feeling, "why": WHY, "carried": False}]


def flip(folder, inner):
    folder = Path(folder)
    rows = read_rows(folder / "feelings.jsonl")
    inputs = {event["tick"]: event["data"] for event in _events(folder) if event["kind"] == "agent_input"}
    decided = [row for row in rows if row["kind"] == "choice" and row.get("decided")]
    trials = []
    for row in decided:
        data = inputs[row["tick"]]
        images = [str(folder / path) for path in data["images"]]
        visible = next(item["visible"] for item in rows if item["kind"] == "appraisal" and item["tick"] == row["tick"])
        answers = {}
        for name, feeling in (("calm", CALM), ("placebo", PLACEBO), ("strong", STRONG)):
            prompt = decision_prompt(data["prompt"], _with_feeling(rows, row["tick"], feeling))
            answers[name] = parse_action(inner.decide(Ask(prompt, images, visible, row["t"], row["tick"])), visible)
        trials.append({"tick": row["tick"], **answers})
    # An invalid answer isn't a choice, so two of them mustn't count as "the feeling changed nothing".
    valid = [trial for trial in trials if trial["calm"] and trial["strong"] and trial["placebo"]]
    total = len(valid)
    strong = _rate(sum(trial["calm"] != trial["strong"] for trial in valid), total)
    placebo = _rate(sum(trial["calm"] != trial["placebo"] for trial in valid), total)
    return {"decisions": len(trials), "valid_decisions": total, "strong_changed_action": strong, "placebo_changed_action": placebo,
            "verdict": verdict(strong, placebo), "trials": trials}


def verdict(strong, placebo):
    if strong["total"] < MIN_FLIP_DECISIONS:
        return f"too few decisions to say; needs {MIN_FLIP_DECISIONS}"
    if strong["rate"] - placebo["rate"] >= MIN_FLIP_GAP:
        return "the feeling changes the action more than a near-synonym does"
    return "no clear effect of the feeling on the action"


def replay(folder, inner):
    """Re-ask a run's real decisions, with the moments it actually lived, through whichever model inner is.

    Every model sees identical inputs, unlike two separate runs, which stop being comparable once their actions differ.
    The base model should reproduce its own run at temperature 0. If it doesn't, the rebuilt prompts are wrong.
    """
    folder = Path(folder)
    rows = read_rows(folder / "feelings.jsonl")
    inputs = {event["tick"]: event["data"] for event in _events(folder) if event["kind"] == "agent_input"}
    trials = []
    for row in rows:
        if row["kind"] != "choice" or not row.get("decided"):
            continue
        felt = next(item for item in rows if item["kind"] == "appraisal" and item["tick"] == row["tick"])
        before = [item for item in rows if item["tick"] < row["tick"]] + [felt]
        data = inputs[row["tick"]]
        prompt = decision_prompt(data["prompt"], before, felt["point"])
        raw = inner.decide(Ask(prompt, [str(folder / path) for path in data["images"]], felt["visible"], row["t"], row["tick"]))
        action = parse_action(raw, felt["visible"])
        trials.append({"tick": row["tick"], "recorded": row["action"], "action": action, "raw": raw if action is None else None})
    total = len(trials)
    valid = [trial for trial in trials if trial["action"] is not None]
    return {"decisions": total, "valid": _rate(len(valid), total),
            "changed_action": _rate(sum(trial["action"] != trial["recorded"] for trial in valid), len(valid)),
            "action_types": dict(Counter(trial["action"]["type"] for trial in valid)),
            "recorded_action_types": dict(Counter(trial["recorded"].get("type") for trial in trials)), "trials": trials}


def compare(base, other):
    """Two separate runs side by side. Only comparable if nothing but the weights differed, so that gets checked first."""
    configs = [json.loads((Path(folder) / "config.json").read_text()) for folder in (base, other)]
    differs = [key for key in configs[0] if key != "agent_weights" and configs[0][key] != configs[1].get(key)]
    timelines = [timeline(Path(folder) / "feelings.jsonl") for folder in (base, other)]
    pairs = list(zip(*timelines))
    return {"seed": configs[0].get("seed"), "weights": [config.get("agent_weights") for config in configs], "settings_that_differ": differs,
            "first_tick_acting_differently": next((a["tick"] for a, b in pairs if a["action"] != b["action"]), None),
            "ticks_compared": len(pairs), "base": stats(base), "other": stats(other)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--flip", action="store_true")
    parser.add_argument("--replay", action="store_true", help="re-ask this run's decisions through the model in --weights")
    parser.add_argument("--compare", type=Path, metavar="OTHER_RUN", help="another run with the same settings and different weights")
    parser.add_argument("--weights", help="a folder of full Qwen weights, such as a training run's fused/")
    args = parser.parse_args()
    label = Path(args.weights).parent.name if args.weights else "base"
    report = {"weights": args.weights, "stats": stats(args.folder)}
    name = "mind_check"
    if args.flip or args.replay:
        from kokopelli.loop.run_mind import measured_qwen
        inner = measured_qwen(args.weights)
        if args.flip:
            report["flip"], name = flip(args.folder, inner), f"mind_flip_{label}"
        if args.replay:
            report["replay"], name = replay(args.folder, inner), f"mind_replay_{label}" if not args.flip else f"mind_flip_replay_{label}"
    if args.compare:
        report["compare"], name = compare(args.folder, args.compare), f"mind_compare_{args.compare.name}"
    (args.folder / f"{name}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
