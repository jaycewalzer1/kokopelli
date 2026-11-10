"""Cheap pre-GPU check: a tabular softmax agent using the SAME update rule planned for
the LoRA (on-policy REINFORCE, running baseline, one lived outcome per decision).
Does experience alone push it toward rare-bad and away from rare-good (Hertwig)?

Ported to the 3-decision scenario: it lives through exp1.world.Life, so the gate, the schedule, depletion and the
forced exploration mornings are the real ones. Forced choices update the baseline but never the logits. A gated
option keeps its logit; the softmax runs over what's offered. D2 shares are reported on gate-open mornings, where
all four options compete, and on gate-closed ones separately.

    python -m experiments.exp1.tabular_check            # the table for lr 1, 4, 8, 2000 lives per arm
"""
import argparse
import json

import numpy as np

from experiments.exp1.world import ARMS, Life
from kokopelli.life import scenario

BASELINE_WEIGHT = 0.2


def run(seed, arm="lived", days=25, lr=2.0, scales=None):
    life = Life(seed, arm, days, scales=scales)
    rng = np.random.default_rng([seed, 99])
    logits = {decision: {option.id: 0.0 for option in options} for decision, options in scenario.DECISIONS.items()}
    base = {decision: 0.0 for decision in logits}
    picks = []
    while not life.finished:
        pending = life.pending()
        shown, decision = pending.shown, pending.decision
        z = np.array([logits[decision][o] for o in shown])
        p = np.exp(z - z.max()); p /= p.sum()
        a = shown.index(pending.forced) if pending.forced else rng.choice(len(shown), p=p)
        r = life.choose(shown[a])["reward"]
        adv = r - base[decision]; base[decision] += BASELINE_WEIGHT * (r - base[decision])
        if not pending.forced:
            g = -p; g[a] += 1.0                      # grad of log pi(a) wrt the offered logits
            for o, step in zip(shown, lr * adv * g):
                logits[decision][o] += step
            if pending.day > days // 2:
                picks.append((decision, pending.gate_open, shown[a]))
    return {"picks": picks, "explore_complete": life.explore_complete, "explore_days": life.explore_days}


def shares(results):
    """Second-half pick share per option, per decision. D2 is split by whether the front gap was offered."""
    groups = {"D1": None, "D2 gate open": True, "D2 gate closed": False, "D3": None}
    out = {}
    for name, gate in groups.items():
        decision = name[:2]
        options = [o.id for o in scenario.DECISIONS[decision] if not (gate is False and o.id == scenario.FRONT_GAP)]
        per_life = []
        for result in results:
            chosen = [choice for d, open_, choice in result["picks"] if d == decision and (gate is None or open_ == gate)]
            if chosen:
                per_life.append([chosen.count(o) / len(chosen) for o in options])
        out[name] = {"options": dict(zip(options, np.mean(per_life, axis=0).round(4).tolist())), "lives": len(per_life),
                     "chance": round(1 / len(options), 4)}
    return out


def by_role(table):
    """Rare-bad and rare-good shares, averaged over the decisions where both compete (D1, D2 gate open, D3)."""
    roles = {}
    for name in ("D1", "D2 gate open", "D3"):
        for option, share in table[name]["options"].items():
            roles.setdefault(scenario.BY_ID[option].role, []).append(share)
    return {role: round(float(np.mean(values)), 4) for role, values in roles.items()}


def summarize(arm, lr, lives=2000, days=25, scales=None):
    results = [run(seed, arm, days, lr, scales) for seed in range(lives)]
    table = shares(results)
    return {"arm": arm, "lr": lr, "lives": lives, "days": days, "scales": scales, "shares": table, "roles": by_role(table),
            "explore_days_mean": float(np.mean([r["explore_days"] for r in results])),
            "explore_incomplete": sum(not r["explore_complete"] for r in results)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lives", type=int, default=2000)
    parser.add_argument("--lr", type=float, nargs="+", default=[1.0, 4.0, 8.0])
    parser.add_argument("--json", help="also write every summary to this file")
    parser.add_argument("--balanced", action="store_true", help="play the balance solver's scaled need changes (experiments/exp1/balance.py)")
    options = parser.parse_args()
    print(f"chance = 1/offered per option; second half of each 25-day life, {options.lives} lives")
    scales = None
    if options.balanced:
        from experiments.exp1.balance import solve
        scales = solve()["scales"]
        print(f"scaled need changes: {scales}")
    found = []
    for lr in options.lr:
        print(f"--- lr={lr}")
        for arm in ARMS:
            summary = summarize(arm, lr, options.lives, scales=scales)
            found.append(summary)
            print(f"{arm:9s} roles {summary['roles']}  forced mornings {summary['explore_days_mean']:.1f}")
            for name, row in summary["shares"].items():
                print(f"    {name:15s} {row['options']}")
    if options.json:
        with open(options.json, "w") as file:
            json.dump(found, file, indent=1)
