"""Diagnostics on a finished run. Nothing here changes how a run behaves.

    python -m experiments.exp1.diagnose temperature RUN   offline: how pi would look at other choice temperatures, from saved log-probs
    python -m experiments.exp1.diagnose d2 RUN            GPU: rebuild the adapter before the D2 shift, replay those nights three ways,
                                              attribute the update to each replayed transition, re-measure the D2 probe
    python -m experiments.exp1.diagnose pilot RUN         GPU: rebuild a pilot's nights and split each night's update by transition (the stop rule)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from experiments.exp1 import homeostasis as H
from experiments.exp1.world import Life

TEMPERATURES = (1, 2, 3, 5)
ABOVE_THE_GRID = (8, 10)   # for reference only
GROUP = 8
GROUPS_PER_ROW = 2000
SPREAD_SHARE = 0.7


def _rows(run):
    return [json.loads(line) for line in Path(run, "trajectory.jsonl").read_text().splitlines()]


def _outcomes(life, decision, option):
    """(probability, delta) per outcome of this option, as the lived arm draws them, with the world's scaling."""
    out = []
    for p, delta, key in H.TABLES[decision][option]:
        scale = life.scales.get(option)
        out.append((p, H.scaled(delta, key, scale) if scale else np.asarray(delta)))
    return out


def temperature(run, logp_field="logp", seed=0, temperatures=TEMPERATURES):
    config = json.loads(Path(run, "config.json").read_text())
    life = Life(config["seed"], config["arm"], config["days"])
    rng = np.random.default_rng(seed)
    table = {}
    for row in _rows(run):
        decision = row["decision"]
        logp1 = np.array(row[logp_field])
        h = np.array(row["h_pre"])
        rewards = [[(p, H.apply(h, delta)[1]) for p, delta in _outcomes(life, decision, o)] for o in row["shown"]]
        for t in temperatures:
            z = logp1 / t
            pi = np.exp(z - z.max())
            pi /= pi.sum()
            entropy = -(pi * np.log(np.where(pi > 0, pi, 1))).sum() / np.log(len(pi))
            # 8-sample groups: options from pi_T, outcomes from each option's own odds, reward from this morning's needs
            options = rng.choice(len(pi), size=(GROUPS_PER_ROW, GROUP), p=pi)
            reward = np.empty(options.shape)
            for k, branches in enumerate(rewards):
                mask = options == k
                which = rng.choice(len(branches), size=mask.sum(), p=[p for p, _ in branches])
                reward[mask] = np.array([r for _, r in branches])[which]
            distinct = np.array([len(set(g)) for g in options]) >= 2
            spread = reward.max(axis=1) - reward.min(axis=1) > 1e-9
            cell = table.setdefault(decision, {}).setdefault(t, {"top": [], "entropy": [], "spread": []})
            cell["top"].append(pi.max())
            cell["entropy"].append(entropy)
            cell["spread"].append((distinct & spread).mean())
    summary = {d: {t: {k: float(np.mean(v)) for k, v in cells.items()} | {"n": len(cells["top"])} for t, cells in by_t.items()}
               for d, by_t in sorted(table.items())}
    chosen = next((t for t in temperatures if all(summary[d][t]["spread"] >= SPREAD_SHARE for d in summary)), None)
    return {"logp": logp_field, "group": GROUP, "groups_per_row": GROUPS_PER_ROW, "threshold": SPREAD_SHARE,
            "table": summary, "lowest_passing": chosen}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["temperature", "d2", "pilot"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args(argv)
    out = args.run / "diagnostics"
    out.mkdir(exist_ok=True)
    if args.what == "temperature":
        found = {field: temperature(args.run, field) for field in ("logp", "base_logp")}
        found |= {f"{field}_above_the_grid": temperature(args.run, field, temperatures=ABOVE_THE_GRID) for field in ("logp", "base_logp")}
        (out / "temperature.json").write_text(json.dumps(found, indent=1))
        for field, result in found.items():
            print(f"\n{field}: lowest T with >= {SPREAD_SHARE:.0%} spread groups in every decision: {result['lowest_passing']}")
            for d, by_t in result["table"].items():
                for t, c in by_t.items():
                    print(f"  {d} T={t}: top {c['top']:.3f}  entropy {c['entropy']:.3f}  spread {c['spread']:.3f}  (n {c['n']})")
    elif args.what == "d2":
        from experiments.exp1 import diagnose_d2
        diagnose_d2.main(args.run, out)
    else:
        from experiments.exp1 import diagnose_pilot
        diagnose_pilot.main(args.run, out)


if __name__ == "__main__":
    sys.exit(main())
