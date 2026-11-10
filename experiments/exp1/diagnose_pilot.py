"""How much of each night's update came from one transition: the stop rule set before the T = 8 pilot.

The run kept only its final adapter, so this rebuilds the nights on the logged rows from a seeded start (see diagnose_d2), at
the run's own choice temperature. Each step is split by transition in Adam's own scaling, u_i = clip * g_i / denom:
    share_i = <u_i, U> / <U, U>,  U = sum_i u_i
so the shares of a step add up to 1. Momentum from earlier steps isn't counted; this is about what each night newly adds.

The rule trips if, on any night, one penalty (advantage < 0) on a choice with pi under LOW_PI when it was made is more than
STOP_SHARE of the update, averaged over the night's steps.
"""
import gc
import json
import math
import sys

import mlx.core as mx

from experiments.exp1.diagnose_d2 import REBUILD_SEED, Rebuild, _flat, _log, _unflat, split_grad
from experiments.exp1.learn import Sleeper
from experiments.exp1.run import POLITE_GB, QWEN_WEIGHTS, ROOT

LOW_PI = 0.5
STOP_SHARE = 0.5


class TemperedRebuild(Rebuild):
    def load(self):
        from experiments.exp1.policy import QwenPolicy
        mx.random.seed(REBUILD_SEED)
        self.policy = QwenPolicy(self.config.get("model_weights") or QWEN_WEIGHTS, self.config["lora"]["rank"], self.config["lora"]["alpha"],
                                 temperature=self.config["choice_temperature"])
        self.sleeper = Sleeper(self.policy, self.settings)


def shares_step(sleeper, rows):
    """One Adam step on these rows, returning each transition's share of what the step newly adds."""
    model, settings, optimizer = sleeper.policy.model, sleeper.settings, sleeper.optimizer
    _, b2 = optimizer.betas
    scale = 1.0 / len(rows)
    parts, total = [], None
    for row in rows:
        g_pg, g_kl, pg, kl, weight = split_grad(sleeper, row, scale)
        parts.append((row, g_pg, g_kl, weight))
        whole = {k: g_pg[k] + g_kl[k] for k in g_pg}
        total = whole if total is None else {k: total[k] + whole[k] for k in total}
        mx.eval(total)
    norm = math.sqrt(sum(float((g * g).sum()) for g in total.values()))
    clip = min(settings["max_grad_norm"] / (norm + 1e-6), 1.0)
    state = _flat(optimizer.state)
    denom = {k: mx.sqrt(b2 * state[f"{k}.v"] + (1 - b2) * mx.square(clip * total[k])) + optimizer.eps for k in total}
    mx.eval(denom)

    def against_net(tree):
        return sum(float((clip * total[k] / denom[k] * (clip * tree[k] / denom[k])).sum()) for k in total)

    net = against_net(total) or 1.0
    transitions = [{"day": row["day"], "decision": row["decision"], "choice": row["choice"], "outcome": row["outcome_label"], "advantage": row["advantage"],
                    "pi_then": row["pi"][row["choice"]], "weight": round(weight, 4), "share_pg": against_net(g_pg) / net, "share_kl": against_net(g_kl) / net}
                   for row, g_pg, g_kl, weight in parts]
    optimizer.update(model, _unflat({k: clip * g for k, g in total.items()}))
    mx.eval(model.trainable_parameters(), optimizer.state)
    sleeper.steps_taken += 1
    del parts, total, denom
    gc.collect()
    return {"grad_norm": norm, "clip": clip, "transitions": transitions}


def night_summary(steps):
    """The night's largest single penalties, each transition's share averaged over the steps."""
    mean = [t | {"share_pg": sum(s["transitions"][i]["share_pg"] for s in steps) / len(steps),
                 "share_kl": sum(s["transitions"][i]["share_kl"] for s in steps) / len(steps)} for i, t in enumerate(steps[0]["transitions"])]
    penalties = [t for t in mean if t["advantage"] < 0]
    low = [t for t in penalties if t["pi_then"] < LOW_PI]
    top_low = max(low, key=lambda t: t["share_pg"], default=None)
    return {"transitions": mean, "top_low_pi_penalty": top_low, "top_penalty": max(penalties, key=lambda t: t["share_pg"], default=None),
            "top_any": max(mean, key=lambda t: abs(t["share_pg"]), default=None),
            "tripped": bool(top_low and top_low["share_pg"] > STOP_SHARE)}


def main(run, out):
    sys.path.insert(0, str(ROOT))
    from kokopelli.ops import ram_share
    guard = ram_share.Guard(f"{run.name}_pilot_check", POLITE_GB, log=_log)
    job = TemperedRebuild(run, out)
    target = out / "pilot_check.json"
    free = [i for i in sorted(job.nights) if job.nights[i]["phase"] == "free"]
    results = json.loads(target.read_text()) if target.exists() else {
        "model_weights": job.config.get("model_weights") or str(QWEN_WEIGHTS), "rebuild_seed": REBUILD_SEED, "choice_temperature": job.config["choice_temperature"],
        "low_pi": LOW_PI, "stop_share": STOP_SHARE, "nights": []}
    guard.before()
    job.load()
    if results["nights"]:
        adapters, optimizer, extra = job.files("latest")
        job.restore(adapters, optimizer, extra["lora_step"])
    for night in free[len(results["nights"]):]:
        rows = job.rows_for(night, "normal")
        steps = [shares_step(job.sleeper, rows) for _ in range(job.settings["steps"])]
        logged = job.nights[night]
        results["nights"].append({"night": night, "day": logged["day"], "samples": len(rows), "steps": steps, **night_summary(steps),
                                  "probes": job.probe_pis(), "logged_probes": logged["probes_after"]})
        results["tripped"] = any(n["tripped"] for n in results["nights"])
        job.save("latest", {"night": night})
        target.write_text(json.dumps(results, indent=1))
        top = results["nights"][-1]["top_low_pi_penalty"]
        _log(f"night {night}: top low-pi penalty share {top['share_pg'] if top else 0:.3f}")
    _log("done")
