"""The balance check, per decision: each option's expected reward against the safe option's.

Two views, because they disagree:
    mean state     reward at the average state a decision is entered with. With a linear drive and nothing crossing the
                   setpoint, reward is just the sum of the need changes, so this is equal by construction.
    distribution   averaged over every state a decision really sees (uniform-random play upstream). Here any gain that
                   pushes a need past 0.7 is wasted, so an option that piles its gain on one need loses some of it.
D2 is checked twice: on gate-open mornings (all four options) and gate-closed ones (no front gap).

solve() runs homeostasis.balance() on the distribution view: the scale on each option's majority branch that would make
its expected reward match the safe option's. It reports; nothing uses the scales unless they're passed to Life.

    python -m experiments.exp1.balance [--json PATH]
"""
import argparse
import json

import numpy as np

from experiments.exp1 import homeostasis as H
from kokopelli.life import scenario

TOLERANCE = 0.02
GROUPS = (("D1", None), ("D2 gate open", True), ("D2 gate closed", False), ("D3", None))


def _options(decision, gate):
    return [o for o in H.TABLES[decision] if not (gate is False and o == scenario.FRONT_GAP)]


def _view(decision, options, states, scales=None):
    scales = scales or {}
    ev = {o: H.expected_reward(H.TABLES[decision], o, states, scales.get(o) or 1.0) for o in options}
    safe = ev[H.SAFE[decision]]
    values = list(ev.values())
    spread = (max(values) - min(values)) / safe
    return {"expected_reward": {o: round(v, 5) for o, v in ev.items()},
            "vs_safe": {o: round(v / safe - 1, 4) for o, v in ev.items()},
            "spread": round(spread, 4), "within_2_percent": spread <= TOLERANCE}


def report(samples=20000, seed=0, scales=None):
    """Both views for every decision. States upstream are played with the same scales, if any."""
    rng = np.random.default_rng(seed)
    out = {}
    for name, gate in GROUPS:
        decision = name[:2]
        states = H.entry_states(decision, rng, samples, scales, gate)
        options = _options(decision, gate)
        out[name] = {"mean_state": [round(float(v), 4) for v in np.mean(states, axis=0)],
                     "at_mean_state": _view(decision, options, [np.mean(states, axis=0)], scales),
                     "over_distribution": _view(decision, options, states, scales)}
    return out


def solve(samples=20000, seed=0):
    """Scales, decision by decision so each one's states reflect the scales already chosen upstream. The front gap is
    solved on gate-open mornings only, since that's the only time it's offered."""
    rng = np.random.default_rng(seed)
    scales = {}
    for decision in scenario.DECISIONS:
        states = H.entry_states(decision, rng, samples, scales)
        found = H.balance(H.TABLES[decision], H.SAFE[decision], states)
        if decision == "D2":
            open_states = H.entry_states(decision, rng, samples, scales, gate=True)
            found[scenario.FRONT_GAP] = H.balance({o: H.TABLES[decision][o] for o in (H.SAFE[decision], scenario.FRONT_GAP)},
                                                  H.SAFE[decision], open_states)[scenario.FRONT_GAP]
        scales.update(found)
    return {"scales": scales, "unsolvable": [o for o, s in scales.items() if s is None]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json")
    options = parser.parse_args()
    raw = report()
    solved = solve()
    after = report(scales={o: s for o, s in solved["scales"].items() if s})
    for title, found in (("as written", raw), ("with solver scales", after)):
        print(f"--- {title}")
        for name, row in found.items():
            dist = row["over_distribution"]
            print(f"{name:15s} mean-state spread {row['at_mean_state']['spread']:+.2%}  distribution spread {dist['spread']:+.2%}  "
                  + "  ".join(f"{o} {v:+.1%}" for o, v in dist["vs_safe"].items()))
    print("scales", solved["scales"])
    if options.json:
        with open(options.json, "w") as file:
            json.dump({"as_written": raw, "solver": solved, "with_scales": after}, file, indent=1)
