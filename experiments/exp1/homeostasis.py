"""Homeostatic state, drive, reward, and felt-text for the wellness-center scenario.

Reward = drive reduction (Keramati & Gutkin 2014), deficit-only by default.
Only the OUTCOME step produces reward. Passive depletion between decisions is
choice-independent and is excluded so the agent isn't paid for waiting.
"""
from __future__ import annotations
import numpy as np

from kokopelli.life import scenario

NEEDS = ("comfort", "calm", "connection")
SETPOINT = np.array([0.7, 0.7, 0.7])
WEIGHTS = np.array([1.0, 1.0, 1.0])
START_MEAN = SETPOINT - 0.25   # headroom so outcomes rarely hit the cap
START_SD = 0.05
DEPLETE = 0.15        # each need drops this much between decisions (needs decay; outcomes refill)
DEFICIT_ONLY = True   # overshoot costs nothing (no built-in satiation)
EXPONENT = 1.0        # 1 = linear deficit (EV-preserving below setpoint); 2 = quadratic (state-dependent risk aversion)

# decision -> option -> list of (prob, delta[comfort, calm, connection], key), built from kokopelli/life/scenario.py, which owns the
# world: options, outcome odds, need deltas (points x 0.05) and the front-gap gate. This file owns only the reward math.
# The 2-decision draft's own D1/D2 tables were replaced by these.
assert scenario.NEEDS == NEEDS and scenario.SETPOINT == 0.7, "scenario.py's needs or setpoint changed; recheck this file"
TABLES = {decision: {option.id: [(outcome.p, list(outcome.delta), outcome.key) for outcome in option.outcomes] for option in options}
          for decision, options in scenario.DECISIONS.items()}
SAFE = {decision: next(option.id for option in options if option.role == "safe") for decision, options in scenario.DECISIONS.items()}


def start_state(rng) -> np.ndarray:
    return np.clip(START_MEAN + rng.normal(0, START_SD, 3), 0, 1)


def drive(h: np.ndarray) -> float:
    gap = SETPOINT - h
    if DEFICIT_ONLY:
        gap = np.maximum(gap, 0.0)
    return float(np.sum(WEIGHTS * gap ** EXPONENT))


def apply(h: np.ndarray, delta) -> tuple[np.ndarray, float]:
    """Apply an outcome. Returns (new_state, reward)."""
    h2 = np.clip(h + np.asarray(delta), 0, 1)
    return h2, drive(h) - drive(h2)


def relax(h: np.ndarray) -> np.ndarray:
    """Between decisions needs DEPLETE (like hunger growing). Choice-independent,
    so it is never rewarded. Name kept for compatibility."""
    return np.clip(h - DEPLETE, 0, 1)


def draw(table, option, rng):
    branches = table[option]
    i = rng.choice(len(branches), p=[b[0] for b in branches])
    return branches[i]


# ---------- felt text (the agent's interoception; never show numbers) ----------
FELT = {
    "comfort":    [(0.35, "grimy and uncomfortable"), (0.55, "a bit off physically"),
                   (0.80, "physically fine"), (1.01, "really comfortable")],
    "calm":       [(0.35, "rushed and on edge"), (0.55, "a little tense"),
                   (0.80, "settled"), (1.01, "completely at ease")],
    "connection": [(0.35, "lonely"), (0.55, "a bit disconnected"),
                   (0.80, "socially okay"), (1.01, "really connected to people")],
}


def felt_text(h: np.ndarray) -> str:
    parts = []
    for name, v in zip(NEEDS, h, strict=False):
        for cut, phrase in FELT[name]:
            if v < cut:
                parts.append(phrase)
                break
    return "You feel " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


# ---------- balance check / solver ----------
MAJORITY = ("common", "quiet", "early")   # branch the solver scales: the 90% branch, or the +5 side of a variance control


def scaled(delta, label, scale):
    return np.asarray(delta) * (scale if label in MAJORITY else 1.0)


def drives(states: np.ndarray) -> np.ndarray:
    """drive() for many states at once (one per row)."""
    gap = SETPOINT - states
    if DEFICIT_ONLY:
        gap = np.maximum(gap, 0.0)
    return np.sum(WEIGHTS * gap ** EXPONENT, axis=-1)


def expected_reward(table, option, states, scale=1.0) -> float:
    """Same as averaging apply(h, d)[1] over states, done for all states at once."""
    states = np.asarray(states, dtype=float)
    tot = 0.0
    for p, d, label in table[option]:
        d = scaled(d, label, scale)
        tot += p * float(np.mean(drives(states) - drives(np.clip(states + d, 0, 1))))
    return tot


def balance(table, safe, states, lo=0.0, hi=5.0, iters=60) -> dict:
    """Bisect a scale on each risky option's majority branch (common / quiet /
    empty) until its expected reward matches the safe option's. Scaling the rare
    branch can't work: deficit-only caps jackpots, and the oak's good days alone
    don't beat the safe spot. Returns {option: scale}."""
    target = expected_reward(table, safe, states)
    scales = {}
    for opt in table:
        if opt == safe:
            continue
        f = lambda s, opt=opt: expected_reward(table, opt, states, s) - target
        a, b = lo, hi
        if f(a) * f(b) > 0:
            scales[opt] = None  # can't balance by scaling this branch alone
            continue
        for _ in range(iters):
            m = (a + b) / 2
            a, b = (m, b) if f(a) * f(m) > 0 else (a, m)
        scales[opt] = round((a + b) / 2, 3)
    return scales


def entry_states(decision, rng, n, scales=None, gate=None):
    """States a decision sees under a uniform-random policy upstream: a fresh morning, then each earlier outcome and the
    depletion after it. gate=True keeps only mornings where the front gap is open at D2, gate=False only those where it's
    closed, None keeps all. scales are balance() results per option, applied to upstream outcomes as they would be in a run."""
    scales = scales or {}
    order = list(scenario.DECISIONS)
    out = []
    while len(out) < n:
        h = start_state(rng)
        arrival, on_time = None, False
        for upstream in order[:order.index(decision)]:
            shown = scenario.shown_options(upstream, arrival, on_time)
            option = shown[rng.integers(len(shown))]
            p, d, label = draw(TABLES[upstream], option, rng)
            h, _ = apply(h, scaled(d, label, scales.get(option) or 1.0))
            if upstream == "D1":
                outcome = scenario.outcome_of(option, label)
                arrival, on_time = outcome.arrival, outcome.on_time
            h = relax(h)
        if gate is not None and (scenario.FRONT_GAP in scenario.shown_options("D2", arrival, on_time)) != gate:
            continue
        out.append(h)
    return out
