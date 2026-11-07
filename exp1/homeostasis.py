"""Homeostatic state, drive, reward, and felt-text for the wellness-center scenario.

Reward = drive reduction (Keramati & Gutkin 2014), deficit-only by default.
Only the OUTCOME step produces reward. Passive depletion between decisions is
choice-independent and is excluded so the agent isn't paid for waiting.
"""
from __future__ import annotations
import numpy as np

NEEDS = ("comfort", "calm", "connection")
SETPOINT = np.array([0.7, 0.7, 0.7])
WEIGHTS = np.array([1.0, 1.0, 1.0])
START_MEAN = SETPOINT - 0.25   # headroom so outcomes rarely hit the cap
START_SD = 0.05
DEPLETE = 0.15        # each need drops this much between decisions (needs decay; outcomes refill)
DEFICIT_ONLY = True   # overshoot costs nothing (no built-in satiation)
EXPONENT = 1.0        # 1 = linear deficit (EV-preserving below setpoint); 2 = quadratic (state-dependent risk aversion)

# option -> list of (prob, delta[comfort, calm, connection], label)
# "rare_scale" multiplies the rare branch; tuned by balance() so every option
# has equal expected reward. The unscaled splits are design choices; edit freely.
# Splits sum to (points x 0.05) from the scenario spec, so EV = 3 points = 0.15 units
# for every option. Rare-good is spread across needs so it stays under the cap.
D1 = {
    "middle_lawn": [(1.0, [0.05, 0.05, 0.05], "normal")],                                    # +3
    "under_oak":   [(0.9, [0.15, 0.05, 0.00], "common"), (0.1, [-0.20, -0.10, 0.00], "rare")],  # +4 / -6
    "front_row":   [(0.9, [-0.05, 0.05, 0.10], "common"), (0.1, [0.15, 0.20, 0.25], "rare")],  # +2 / +12
    "by_path":     [(0.5, [0.05, 0.20, 0.00], "quiet"), (0.5, [0.00, -0.05, 0.10], "busy")],    # +5 / +1
}
D2 = {
    "paved_path":   [(1.0, [0.05, 0.10, 0.00], "normal")],                                   # +3
    "lawn":         [(0.9, [0.05, 0.15, 0.00], "common"), (0.1, [-0.25, -0.05, 0.00], "rare")],  # +4 / -6
    "garden_trail": [(0.9, [0.05, -0.05, 0.10], "common"), (0.1, [0.15, 0.15, 0.30], "rare")],  # +2 / +12
    "side_gate":    [(0.5, [0.05, 0.20, 0.00], "empty"), (0.5, [0.00, 0.05, 0.00], "jammed")],  # +5 / +1
}
SAFE = {"D1": "middle_lawn", "D2": "paved_path"}


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
    for name, v in zip(NEEDS, h):
        for cut, phrase in FELT[name]:
            if v < cut:
                parts.append(phrase)
                break
    return "You feel " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


# ---------- balance check / solver ----------
MAJORITY = ("common", "quiet", "empty")   # branch the solver scales


def scaled(delta, label, scale):
    return np.asarray(delta) * (scale if label in MAJORITY else 1.0)


def expected_reward(table, option, states, scale=1.0) -> float:
    tot = 0.0
    for p, d, label in table[option]:
        d = scaled(d, label, scale)
        tot += p * np.mean([apply(h, d)[1] for h in states])
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
        f = lambda s: expected_reward(table, opt, states, s) - target
        a, b = lo, hi
        if f(a) * f(b) > 0:
            scales[opt] = None  # can't balance by scaling this branch alone
            continue
        for _ in range(iters):
            m = (a + b) / 2
            a, b = (m, b) if f(a) * f(m) > 0 else (a, m)
        scales[opt] = round((a + b) / 2, 3)
    return scales


def d2_states(rng, n, d1_scales):
    """State distribution at D2 under a uniform-random D1 policy."""
    out = []
    opts = list(D1)
    for _ in range(n):
        h = start_state(rng)
        o = opts[rng.integers(len(opts))]
        p, d, label = draw(D1, o, rng)
        d = scaled(d, label, d1_scales.get(o) or 1.0)
        h, _ = apply(h, d)
        out.append(relax(h))
    return out
