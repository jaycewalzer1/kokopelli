"""Sensation sweeps: one scene, one body state at several levels, three ways of telling the agent about it.

    python -m experiments.sensation.sweep run --sweep hunger_egg --backend mock --samples 30 --out out/sensation/try
    python -m experiments.sensation.sweep report out/sensation/try

Real models only through the GPU queue (the queue can't see this process otherwise):
    python3 kokopelli/ops/gpu.py run --name evals_hunger_egg --priority 40 --max-hours 2 --cwd $K \
      --about "Hunger sweep: egg scene at full/half/starving x cue/label/none, base Qwen3-VL-8B-Instruct full weights, text only" \
      --output out/sensation/hunger_egg_base -- \
      .venv/bin/python -m experiments.sensation.sweep run --sweep hunger_egg --backend llm_model --samples 30 \
      --out out/sensation/hunger_egg_base
`--arm base` is the benchmarks' base arm: the full-precision weights. `--arm base_4bit` (arms/ in this folder) is the 4-bit
weights the egg videos decide with. run.json records which folder answered and its quantization.

The design, and why each part is there:
  levels      at least three points (full, half, starving), so a curve shows and not just a difference
  arms        cue (felt text), label ("you are hungry"), none: tells reacting to the state from reacting to the word
  paraphrase  three wordings of each cue, so a result can't hang on one sentence
  samples     30 or more per cell; one answer is noise
  pairing     sample k uses the same random seed at every level, so the levels differ only in the body block. Comparing
              like with like removes the sampling luck the levels share, which narrows the interval for free.
  anchors     anchors.yaml: what people do (flat, for hunger and sharing) and what people predict (stingier)

Text only: no picture, no sim. Minutes per sweep. The closed-loop video run (kokopelli/agents/egg_wm.py) is one honest
sample of the same scene with eyes; this is the benchmark.

Writes <out>/results.jsonl (one line per sample, resumable by key), run.json (model, sampling, prompts' hashes),
report.md and report.json.
"""
import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from experiments.benchmarks.core import REPO, stable_int
from kokopelli.body import cues, egg

HERE = Path(__file__).resolve().parent
ANCHORS = HERE / "anchors.yaml"
ARMS = HERE / "arms"   # this experiment's own arm configs, looked up before the benchmarks' (experiments/benchmarks/configs/arms)


@dataclass(frozen=True)
class Sweep:
    name: str
    variable: str
    levels: tuple
    prompt: object        # (level, arm, paraphrase) -> prompt text
    score: object         # raw reply -> {"valid", "outcome", "gave", "shared", ...}
    paraphrases: int
    anchor: str
    outcome: str = "gave"


SWEEPS = {
    "hunger_egg": Sweep("hunger_egg", "food", ("full", "half", "starving"), egg.text_prompt, egg.score, 3, "hunger_sharing"),
}


def seed_for(sweep, arm, paraphrase, sample):
    """No level in the seed: sample k sees the same luck at every level (pairing)."""
    return stable_int("sensation", sweep, arm, paraphrase, sample) % (2**31)


def key(row):
    return (row["level"], row["arm"], row["paraphrase"], row["sample"])


def cells(sweep, arms, samples):
    for level in sweep.levels:
        for arm in arms:
            for paraphrase in range(sweep.paraphrases):
                for sample in range(samples):
                    yield level, arm, paraphrase, sample


class MockSweepModel:
    """For the mock backend: answers the egg scene like a model that holds the lay belief, scaled by risk_tilt.

    It only "knows" the level when the prompt tells it something (cue or label arm), as a real model would. With tilt 0
    it gives at the same rate at every level (the real-behaviour pattern); with tilt > 0 it gives less as hunger grows.
    """

    def mock_answer(self, item, order, rng, tilt):
        p_give = 0.6 - tilt * item["told_hunger"] / 2
        if rng.random() < p_give:
            return '{"thought": "He needs it more than I do right now.", "action": {"type": "give", "target": "teo", "object": "egg"}}'
        if rng.random() < 0.5:
            return '{"thought": "I need these myself.", "action": {"type": "say", "text": "Sorry, I only have two left."}}'
        return '{"thought": "Breakfast first.", "action": {"type": "cook", "object": "egg"}}'


def _weights(backend, model_meta):
    """Which folder of weights answered, and how it is quantized (None for full precision or when there is no folder)."""
    folder = (model_meta or {}).get("adapter_path") or getattr(backend, "weights", None)
    if not folder:
        return {"weights": None, "quantization": None}
    try:
        quantization = json.loads((Path(folder) / "config.json").read_text()).get("quantization")
    except (OSError, ValueError):
        quantization = None
    return {"weights": str(folder), "quantization": quantization}


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(sweep_name, backend_name="mock", arm_name="base", arms=cues.ARMS, samples=30, out=None, base_url=None,
        mock_tilt=None, batch=8):
    from experiments.benchmarks.backends import get_backend
    from experiments.benchmarks.backends.base import GenRequest
    from experiments.benchmarks.registry import load_arm, load_sampling

    sweep = SWEEPS[sweep_name]
    out = Path(out or REPO / "out" / "sensation" / sweep_name)
    out.mkdir(parents=True, exist_ok=True)
    backend = get_backend(backend_name, base_url=base_url)
    arm = load_arm(arm_name, arm_dirs=[ARMS])
    if mock_tilt is not None:
        arm.mock = {**arm.mock, "risk_tilt": mock_tilt}
    model_meta = backend.prepare_arm(arm, arm.seed)
    # The shared sampling (Qwen's own temperature, top_p and top_k), with room for a thought plus the JSON: at the
    # shared 128 tokens, replies with a sentence of thought got cut off before the action. live.py uses 300 too.
    sampling = {**load_sampling(), "max_tokens": 300}
    results_path = out / "results.jsonl"
    done = {key(row) for row in _rows(results_path)}
    prompts = {(level, a, p): sweep.prompt(level, a, p) for level in sweep.levels for a in arms for p in range(sweep.paraphrases)}
    record = {"sweep": sweep_name, "variable": sweep.variable, "levels": list(sweep.levels), "arms": list(arms),
              "paraphrases": sweep.paraphrases, "samples": samples, "backend": backend_name, "arm": arm_name,
              "model": model_meta, **_weights(backend, model_meta), "sampling": backend.effective_sampling(sampling),
              "git_commit": _git_commit(),
              "level_values": {level: egg.LEVELS.get(level) for level in sweep.levels} if sweep.variable == "food" else None,
              "prompt_sha256": {f"{l}|{a}|{p}": hashlib.sha256(text.encode()).hexdigest()[:16] for (l, a, p), text in prompts.items()},
              "real": backend.is_real}
    old = out / "run.json"
    if old.exists():
        previous = json.loads(old.read_text())
        for field in ("sweep", "backend", "arm", "sampling", "prompt_sha256"):
            if previous.get(field) != record[field]:
                raise SystemExit(f"{out} already holds a run with a different {field}; use a new --out to change it.")
    old.write_text(json.dumps(record, indent=1))
    todo = [cell for cell in cells(sweep, arms, samples) if cell not in done]
    print(f"{sweep_name}: {len(done)} done, {len(todo)} to go", flush=True)
    mock = MockSweepModel()
    with results_path.open("a") as file:
        for start in range(0, len(todo), batch):
            chunk = todo[start:start + batch]
            requests = [GenRequest(prompt=prompts[(level, a, p)], sampling=sampling, seed=seed_for(sweep_name, a, p, s),
                                   mock_context={"instrument": mock, "order": None,
                                                 "item": {"told_hunger": 0 if a == "none" else sweep.levels.index(level)}})
                        for level, a, p, s in chunk]
            for (level, a, p, s), request, result in zip(chunk, requests, backend.generate_batch(requests), strict=True):
                row = {"sweep": sweep_name, "level": level, "arm": a, "paraphrase": p, "sample": s, "seed": request.seed,
                       "raw": result.text, "latency_s": round(result.latency_s, 3), **sweep.score(result.text)}
                file.write(json.dumps(row) + "\n")
            file.flush()
            print(f"  {min(start + batch, len(todo))}/{len(todo)}", flush=True)
    if hasattr(backend, "close"):
        backend.close()
    return out


def _rows(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- analysis

def bootstrap(values, n_boot=4000, seed=0):
    """Mean and a 95% interval by redrawing the samples with replacement (experiments/benchmarks/stats.py explains the idea)."""
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return {"mean": None, "low": None, "high": None, "n": 0}
    draws = np.random.default_rng(seed).integers(0, len(values), size=(n_boot, len(values)))
    means = values[draws].mean(axis=1)
    return {"mean": round(float(values.mean()), 3), "low": round(float(np.percentile(means, 2.5)), 3),
            "high": round(float(np.percentile(means, 97.5)), 3), "n": int(len(values))}


def paired_change(rows, arm, low, high, outcome):
    """outcome at `high` minus at `low`, matched sample by sample (same paraphrase and seed), so only the level differs."""
    def by_key(level):
        return {(r["paraphrase"], r["sample"]): r[outcome] for r in rows
                if r["arm"] == arm and r["level"] == level and r["valid"]}
    a, b = by_key(low), by_key(high)
    return [b[k] - a[k] for k in sorted(set(a) & set(b))]


def verdict(change, margin):
    """Which anchor a change from full to starving matches. Needs the whole interval on one side to say anything."""
    if change["n"] == 0:
        return "no data"
    low, high = change["low"], change["high"]
    if -margin <= low and high <= margin:
        return "flat: matches what people do"
    if high < -margin:
        return "falls with hunger: matches what people predict, not what they do"
    if low > margin:
        return "rises with hunger: matches neither"
    return "unclear: the interval is too wide to tell (more samples)"


def analyse(out):
    out = Path(out)
    record = json.loads((out / "run.json").read_text())
    rows = _rows(out / "results.jsonl")
    sweep = SWEEPS[record["sweep"]]
    anchors = yaml.safe_load(ANCHORS.read_text())
    margin, anchor = anchors["flat_margin"], anchors[sweep.anchor]
    first, last = sweep.levels[0], sweep.levels[-1]
    cells_out, arms_out = [], {}
    for arm in record["arms"]:
        for level in sweep.levels:
            mine = [r for r in rows if r["arm"] == arm and r["level"] == level]
            valid = [r for r in mine if r["valid"]]
            counts = {}
            for r in valid:
                counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
            cells_out.append({"arm": arm, "level": level, "n": len(mine), "invalid": len(mine) - len(valid),
                              "gave": bootstrap([r["gave"] for r in valid]), "shared": bootstrap([r["shared"] for r in valid]),
                              "outcomes": counts,
                              "examples": [{"outcome": r["outcome"], "thought": r.get("thought", "")[:200],
                                            "action": r.get("action")} for r in valid[:3]]})
        change = bootstrap(paired_change(rows, arm, first, last, sweep.outcome))
        change_shared = bootstrap(paired_change(rows, arm, first, last, "shared"))
        arms_out[arm] = {"change": change, "change_shared": change_shared, "verdict": verdict(change, margin),
                         "verdict_shared": verdict(change_shared, margin)}
    gap = None
    if "cue" in arms_out and "label" in arms_out:
        cue = paired_change(rows, "cue", first, last, sweep.outcome)
        label = paired_change(rows, "label", first, last, sweep.outcome)
        n = min(len(cue), len(label))
        gap = bootstrap(np.array(cue[:n]) - np.array(label[:n])) if n else bootstrap([])
    return {"run": out.name, "record": {k: record[k] for k in ("sweep", "variable", "levels", "arms", "samples", "backend", "arm",
                                                              "model", "real", "level_values")},
            "anchor": {"name": sweep.anchor, "source": anchor["source"], "real": anchor["real"]["summary"],
                       "lay": anchor["lay_prediction"]["summary"], "limits": anchor["limits"], "margin": margin},
            "cells": cells_out, "arms": arms_out, "cue_minus_label": gap, "outcome": sweep.outcome,
            "change_from": first, "change_to": last}


def _pct(stat):
    if stat["mean"] is None:
        return "n/a"
    return f"{stat['mean'] * 100:.0f}% [{stat['low'] * 100:.0f}, {stat['high'] * 100:.0f}]"


def _pts(stat):
    if stat["mean"] is None:
        return "n/a"
    return f"{stat['mean'] * 100:+.0f} pts [{stat['low'] * 100:+.0f}, {stat['high'] * 100:+.0f}]"


def report(out):
    out = Path(out)
    result = analyse(out)
    rec, anchor = result["record"], result["anchor"]
    lines = [f"# Sensation sweep: {rec['sweep']}", "",
             f"Backend `{rec['backend']}`, arm `{rec['arm']}`, model `{(rec['model'] or {}).get('model_id')}`. "
             f"{rec['samples']} samples x 3 wordings per cell." + ("" if rec["real"] else " **Not a real model.**"), "",
             f"Levels ({rec['variable']}): " + ", ".join(f"{level} {value:g}" for level, value in (rec["level_values"] or {}).items()), "",
             "## Giving rate by level", "",
             "Primary score: a `give` action to Teo. In brackets, the 95% interval.", "",
             "| Arm | " + " | ".join(rec["levels"]) + " |", "|---|" + "---|" * len(rec["levels"])]
    for arm in rec["arms"]:
        row = [_pct(c["gave"]) for level in rec["levels"] for c in result["cells"] if c["arm"] == arm and c["level"] == level]
        lines.append(f"| {arm} | " + " | ".join(row) + " |")
    lines += ["", f"## Change from {result['change_from']} to {result['change_to']}, and which anchor it matches", "",
              f"Flat means the whole interval sits inside +/- {anchor['margin'] * 100:.0f} points.", "",
              "| Arm | Change in giving | Verdict | Change counting a spoken yes | Verdict |", "|---|---|---|---|---|"]
    for arm, a in result["arms"].items():
        lines.append(f"| {arm} | {_pts(a['change'])} | {a['verdict']} | {_pts(a['change_shared'])} | {a['verdict_shared']} |")
    if "none" in result["arms"]:
        lines += ["", "`none` is a check on the pipeline, not a finding: its prompt and seeds are the same at every level, "
                  "so it must come out exactly flat. If it doesn't, something is leaking the level into the prompt."]
    if result["cue_minus_label"]:
        lines += ["", f"Cue minus label (difference in that change): {_pts(result['cue_minus_label'])}. "
                  "Near zero means the felt cue moves the agent as much as being told the word."]
    lines += ["", "## The anchors", "", f"**What people do:** {anchor['real']}", "",
              f"**What people predict:** {anchor['lay']}", "", f"**Limits:** {anchor['limits']}", "",
              f"Source: {anchor['source']}", "", "## Outcomes and examples", ""]
    for c in result["cells"]:
        lines.append(f"- **{c['arm']}, {c['level']}**: {c['outcomes']}" + (f", {c['invalid']} invalid" if c["invalid"] else ""))
        for ex in c["examples"][:2]:
            lines.append(f"  - {ex['outcome']}: \"{ex['thought']}\"")
    (out / "report.md").write_text("\n".join(lines) + "\n")
    (out / "report.json").write_text(json.dumps(result, indent=1))
    return out / "report.md"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sweep", default="hunger_egg", choices=sorted(SWEEPS))
    r.add_argument("--backend", default="mock", choices=("mock", "llm_model", "api", "vllm"))
    r.add_argument("--arm", default="base", help="an arm config from arms/ here or experiments/benchmarks/configs/arms: which model weights answer")
    r.add_argument("--arms", default=",".join(cues.ARMS), help="delivery arms, comma separated: cue,label,none")
    r.add_argument("--samples", type=int, default=30)
    r.add_argument("--out")
    r.add_argument("--base-url")
    r.add_argument("--mock-tilt", type=float, help="mock only: 0 gives the flat pattern, 0.5 the lay-belief one")
    r.add_argument("--no-report", action="store_true")
    p = sub.add_parser("report")
    p.add_argument("out")
    args = ap.parse_args()
    if args.command == "run":
        out = run(args.sweep, args.backend, args.arm, tuple(args.arms.split(",")), args.samples, args.out, args.base_url, args.mock_tilt)
        if not args.no_report:
            print(report(out))
    else:
        print(report(args.out))


if __name__ == "__main__":
    main()
