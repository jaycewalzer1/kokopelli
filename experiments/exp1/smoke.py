"""Before a long Qwen run: does scoring agree with what the model writes, and does a full-size sleep fit and how long does it take?

    python -m experiments.exp1.smoke out/exp1/smoke

For each probe it prints pi over the options and the model's own greedy reply, which should start with {"choice": and name
the option pi ranks first. Then it times one sleep step on as many rows as a full replay window holds (6 days x 3) and
records peak memory. Writes smoke.json.
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

from experiments.exp1 import observe
from experiments.exp1.learn import Sleeper
from experiments.exp1.policy import QwenPolicy
from experiments.exp1.run import QWEN_WEIGHTS, _pi, probes


def main(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {"model_weights": str(QWEN_WEIGHTS)}
    started = time.time()
    policy = QwenPolicy(QWEN_WEIGHTS)
    out["load_s"] = round(time.time() - started, 1)
    rows = [p | {"system": observe.SYSTEM} for p in probes(0)]
    out["probes"] = []
    from mlx_vlm import generate
    for row in rows:
        t = time.time()
        pi = _pi(policy, row)
        score_s = time.time() - t
        t = time.time()
        reply = generate(policy.model, policy.processor, policy.prompt_text(row), max_tokens=40, temperature=0.0, verbose=False).text
        reply_s = time.time() - t
        top = max(pi, key=pi.get)
        named = next((o for o in row["shown"] if reply.strip().startswith(f'{{"choice": "{o}"')), None)
        t = time.time()
        reason = policy.reason(row, top)
        out["probes"].append({"probe": row["probe"], "pi": pi, "greedy_reply": reply, "reply_names": named, "agrees": named == top,
                              "reason": reason, "score_s": round(score_s, 2), "reply_s": round(reply_s, 2), "reason_s": round(time.time() - t, 2),
                              "prompt_tokens": int(policy._batch(row)[4])})
        print(json.dumps(out["probes"][-1]), flush=True)
    # A full replay window: 6 days x 3 decisions, made from the probes with made-up choices and advantages.
    rng = np.random.default_rng(0)
    batch = []
    for k in range(18):
        row = dict(rows[k % len(rows)])
        row["choice"] = row["shown"][rng.integers(len(row["shown"]))]
        row["advantage"] = float(rng.normal(0, 0.1))
        row["pi"] = _pi(policy, row)
        row["base_logp"] = policy.base_log_probs(row).tolist()
        batch.append(row)
    mx.reset_peak_memory()
    sleeper = Sleeper(policy, {"lr": 5e-5, "steps": 1})
    t = time.time()
    stats = sleeper.sleep(batch)
    out["sleep"] = {"rows": len(batch), "step_s": round(time.time() - t, 1), "peak_memory_gb": round(mx.get_peak_memory() / 2 ** 30, 1),
                    "kl": stats["kl"], "grad_norm": stats["grad_norm"]}
    after = [_pi(policy, row) for row in rows]
    out["sleep"]["max_prob_change"] = max(abs(a[o] - p["pi"][o]) for a, p in zip(after, out["probes"], strict=False) for o in a)
    print(json.dumps(out["sleep"]), flush=True)
    (folder / "smoke.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
