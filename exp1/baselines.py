"""What a trained result has to beat, computed on the CPU from the same world.

    random       picks uniformly among what's offered, every free decision
    always_safe  takes each decision's safe option. The scenario has no do-nothing option (every choice is a way of getting
                 to class), so this is the nearest thing: the dull default, not idling. It's labeled that way on the panel.
    tabular      the tabular check's REINFORCE agent at lr 8: the band a learner that only sees rewards should land in.

Shares are second-half free-day pick shares, as in tabular_check. Bands are the 10th to 90th percentile across lives.
Forced exploration mornings are played the same way in every baseline, since they aren't choices.
"""
import numpy as np

from exp1 import tabular_check
from exp1.world import Life
from life import scenario

GROUPS = {"D1": ("D1", None), "D2 gate open": ("D2", True), "D2 gate closed": ("D2", False), "D3": ("D3", None)}
PAIRS = {"D1": ("run_main", "check_desk"), "D2 gate open": ("front_gap", "wait_for_break"), "D3": ("leave_early", "stay_and_chat")}
SAFE = {decision: next(o.id for o in options if o.role == "safe") for decision, options in scenario.DECISIONS.items()}


def group_of(row):
    for name, (decision, gate) in GROUPS.items():
        if row["decision"] == decision and (gate is None or row["gate_open"] == gate):
            return name


def group_options(name):
    decision, gate = GROUPS[name]
    return [o.id for o in scenario.DECISIONS[decision] if not (gate is False and o.id == scenario.FRONT_GAP)]


def summarize_rows(rows, days):
    """Shares in the second half of the free days and mean reward over all free days, from trajectory-like rows."""
    free = [row for row in rows if row["phase"] == "free"]
    late = [row for row in free if row["day"] > days // 2]
    shares = {}
    for name in GROUPS:
        picked = [row["choice"] for row in late if group_of(row) == name]
        shares[name] = {"n": len(picked), "options": {o: (picked.count(o) / len(picked) if picked else None) for o in group_options(name)}}
    mean = lambda values: float(np.mean(values)) if values else None
    for name in GROUPS:
        # The untrained model's average probability for each option over the same picks: what it would do with no training.
        base = [row["base_pi"] for row in late if group_of(row) == name and "base_pi" in row]
        shares[name]["base_pi"] = {o: mean([b[o] for b in base if o in b]) for o in group_options(name)} if base else None
    rewards = {d: mean([row["reward"] for row in free if row["decision"] == d]) for d in scenario.DECISIONS}
    rewards["all"] = mean([row["reward"] for row in free])
    return {"shares": shares, "mean_reward": rewards}


def play(seed, arm, days, rule):
    life, rng = Life(seed, arm, days), np.random.default_rng([seed, 5])
    while not life.finished:
        pending = life.pending()
        if pending.forced:
            life.choose(pending.forced)
        elif rule == "random":
            life.choose(pending.shown[rng.integers(len(pending.shown))])
        else:
            life.choose(SAFE[pending.decision])
    return life.records


def band(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"mean": round(float(np.mean(values)), 4), "p10": round(float(np.percentile(values, 10)), 4),
            "p90": round(float(np.percentile(values, 90)), 4)}


def _bands(per_life):
    out = {"mean_reward": {}, "shares": {}}
    for key in per_life[0]["mean_reward"]:
        out["mean_reward"][key] = band([life["mean_reward"][key] for life in per_life])
    for name in GROUPS:
        out["shares"][name] = {o: band([life["shares"][name]["options"][o] for life in per_life]) for o in group_options(name)}
    return out


def reference(seed, arm, days=25, lives=200, lr=8.0):
    """Everything the panel puts beside one trained life: this seed's random and safe lives, and bands across lives."""
    out = {"seed": seed, "arm": arm, "days": days, "lives": lives, "do_nothing": "not available: every option is a way of getting to class"}
    for rule in ("random", "always_safe"):
        out[rule] = {"this_seed": summarize_rows(play(seed, arm, days, rule), days),
                     "across_lives": _bands([summarize_rows(play(s, arm, days, rule), days) for s in range(1000, 1000 + lives)])}
    tab = []
    for s in range(2000, 2000 + lives):
        result = tabular_check.run(s, arm, days, lr)
        rows = [{"phase": "free", "day": days, "decision": d, "gate_open": g, "choice": c, "reward": 0.0} for d, g, c in result["picks"]]
        tab.append(summarize_rows(rows, days))
    out["tabular"] = {"lr": lr, "shares": _bands(tab)["shares"]}
    return out


def direction(arm, shares):
    """The predicted direction for each rare-bad / rare-good pair, and whether these shares show it.

    lived keeps rare-bad over rare-good, flipped the reverse, shuffled neither (within 0.1). D2 compares within gate-open
    mornings only. With one life a decision has a dozen picks at most, so this is a reading, not a test."""
    out = {}
    for name, (bad, good) in PAIRS.items():
        b, g = shares[name]["options"].get(bad), shares[name]["options"].get(good)
        # Neither option picked (the policy sat on a third one) says nothing about the pair, so it's no reading, not a fail.
        if b is None or g is None or b == g == 0:
            out[name] = {"predicted": None, "observed": None, "pass": None, "n": shares[name]["n"]}
            continue
        predicted = {"lived": f"{bad} > {good}", "flipped": f"{good} > {bad}", "shuffled": "about equal"}[arm]
        ok = b > g if arm == "lived" else g > b if arm == "flipped" else abs(b - g) <= 0.1
        out[name] = {"predicted": predicted, "observed": {bad: round(b, 3), good: round(g, 3)}, "pass": bool(ok), "n": shares[name]["n"]}
    return out
