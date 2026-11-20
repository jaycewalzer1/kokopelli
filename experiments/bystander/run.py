"""Run the armed-bystander scene: one decision per seed, for each version of the scene.

A real run loads Qwen (about 18 GB), so it goes through the GPU queue, which doesn't recognize this module as a model job:

    python3 kokopelli/ops/gpu.py run --name evals_bystander_text --priority 40 --max-hours 0.5 --gb 20 --cwd $K \
      --about "Armed-bystander text scene on models/Qwen3-VL-8B-Instruct: ..." --output out/bystander/NAME -- \
      .venv/bin/python -u -m experiments.bystander.run --out out/bystander/NAME

`--mock` needs no model: it cycles scene.MOCK, for the tests and for checking the files a run writes.

Seed k is used for both versions: it sets the model's sampling and the order the actions are listed in, so the two
versions differ only in what the agent saw. Writes results.jsonl (one row per decision, with its prompt and the whole
reply), run.json (the model, the sampling, who the agent is told it is) and summary.json (counts of each outcome per
version). The dev panel's /bystander page reads them (kokopelli/life/bystander.py).
"""
import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from experiments.bystander import scene
from kokopelli.settings import LLM_MODEL, LLM_MODEL_WEIGHTS, ROOT

TEMPERATURE = 0.7   # the checkpoint's own default. At 0.0 the model is greedy and every seed gives the same answer
MAX_TOKENS = 300


def mock_model():
    def ask(system, user, seed):
        return scene.MOCK[seed % len(scene.MOCK)]
    return ask, {"model": "mock", "weights": None}


def qwen_model(temperature, max_tokens):
    from kokopelli.wm import llm_model  # Imported here because mlx only exists on Apple silicon.
    config = json.loads((LLM_MODEL_WEIGHTS / "config.json").read_text())
    checkpoint = json.loads((LLM_MODEL_WEIGHTS / "generation_config.json").read_text())
    llm_model.load_llm()   # before any seed: building the model's layers uses up random numbers

    def ask(system, user, seed):
        return llm_model.chat(system, user, max_tokens=max_tokens, temperature=temperature, seed=seed).text.strip()

    return ask, {"model": LLM_MODEL, "weights": str(LLM_MODEL_WEIGHTS.relative_to(ROOT)), "quantization": config.get("quantization"),
                 "runtime": "mlx_vlm, text only (no images)", "temperature": temperature, "max_tokens": max_tokens,
                 # chat() can't set these; mlx-vlm reads them from the checkpoint's generation_config.json.
                 "top_p": checkpoint.get("top_p"), "top_k": checkpoint.get("top_k"),
                 "seed_method": "mx.random.seed(seed) before each call, after the model is loaded"}


def _git_commit():
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() or None


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
    record = {"experiment": "bystander", **model, "scenes": list(scenes), "seeds": seeds, "commit": _git_commit(),
              "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "system": scene.WHO,
              "prompts_at_seed_0": {name: scene.prompt(name, 0) for name in scenes}}
    (out / "run.json").write_text(json.dumps(record, indent=2))
    rows = []
    with (out / "results.jsonl").open("w") as results:
        for seed in range(seeds):
            for name in scenes:
                started, prompt = time.perf_counter(), scene.prompt(name, seed)
                raw = ask(scene.WHO, prompt, seed)
                # The prompt and the whole reply are kept, so the panel's page (/bystander) can show a decision in full.
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
    parser.add_argument("--out", required=True, help="a new folder, such as out/bystander/qwen_text_20")
    parser.add_argument("--scenes", nargs="+", default=list(scene.SCENES), choices=scene.SCENES)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--mock", action="store_true", help="canned replies, no model")
    args = parser.parse_args()
    run(args.out, args.scenes, args.seeds, args.mock, args.temperature, args.max_tokens)


if __name__ == "__main__":
    main()
