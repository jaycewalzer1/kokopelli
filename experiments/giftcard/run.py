"""Run the gift-card scene: one decision per seed, for each age and each version.

A real run loads Qwen (about 18 GB), so it goes through the GPU queue, which doesn't recognize this module as a model job:

    python3 kokopelli/ops/gpu.py run --name evals_giftcard_text --priority 40 --max-hours 1 --gb 20 --cwd $K \
      --about "Gift-card text scene on models/Qwen3-VL-8B-Instruct: ..." --output out/giftcard/NAME -- \
      .venv/bin/python -u -m experiments.giftcard.run --out out/giftcard/NAME

The full run is 18 versions x 20 seeds = 360 decisions. `--mock` needs no model: it cycles scene.MOCK.

Seed k is used for every version: it sets the model's sampling and the order the actions are listed in, so versions
differ only in the child's age and what owning up costs. Writes results.jsonl, run.json and summary.json, in the same
shape as experiments/bystander, and the dev panel's /benchmarks page reads them (kokopelli/life/benchmarks.py).
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from experiments.bystander.run import MAX_TOKENS, TEMPERATURE, _git_commit, qwen_model
from experiments.giftcard import scene


def mock_model():
    def ask(system, user, seed):
        return scene.MOCK[seed % len(scene.MOCK)]
    return ask, {"model": "mock", "weights": None}


def summarize(rows):
    """Counts of each outcome per version, in scene.OUTCOMES order, leaving out the ones that never happened."""
    counts = {name: Counter(row["outcome"] for row in rows if row["scene"] == name) for name in scene.SCENES}
    return {name: {outcome: count[outcome] for outcome in scene.OUTCOMES if count[outcome]} for name, count in counts.items() if count}


def run(out, scenes=scene.SCENES, seeds=20, mock=False, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, log=print):
    out = Path(out)
    if (out / "results.jsonl").exists():
        raise SystemExit(f"{out} already holds a run; give a new --out")
    out.mkdir(parents=True, exist_ok=True)
    ask, model = mock_model() if mock else qwen_model(temperature, max_tokens)
    record = {"experiment": "giftcard", **model, "scenes": list(scenes), "seeds": seeds, "commit": _git_commit(),
              "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "system": scene.WHO,
              "prompts_at_seed_0": {name: scene.prompt(name, 0) for name in scenes}}
    (out / "run.json").write_text(json.dumps(record, indent=2))
    rows = []
    with (out / "results.jsonl").open("w") as results:
        for seed in range(seeds):
            for name in scenes:
                started, prompt = time.perf_counter(), scene.prompt(name, seed)
                raw = ask(scene.WHO, prompt, seed)
                row = {"scene": name, "seed": seed, "action_order": scene.action_order(seed), **scene.score(raw), "raw": raw,
                       "prompt": prompt, "seconds": round(time.perf_counter() - started, 2)}
                rows.append(row)
                results.write(json.dumps(row) + "\n")
                results.flush()
                log(f"{name} seed {seed}: {row['outcome']}  {json.dumps(row.get('action', raw[:80]))}")
    summary = summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "run.json").write_text(json.dumps({**record, "finished": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
    for name, counts in summary.items():
        log(f"{name}: " + ", ".join(f"{outcome} {count}/{seeds}" for outcome, count in counts.items()))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="a new folder, such as out/giftcard/qwen_text_20")
    parser.add_argument("--scenes", nargs="+", default=list(scene.SCENES), choices=scene.SCENES)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--mock", action="store_true", help="canned replies, no model")
    args = parser.parse_args()
    run(args.out, args.scenes, args.seeds, args.mock, args.temperature, args.max_tokens)


if __name__ == "__main__":
    main()
