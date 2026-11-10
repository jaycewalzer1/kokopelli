"""Homeostatic rewards. Everything here sees one agent's private numbers, never the lake or anyone else's welfare."""
import math

KEYS = ("energy", "warmth", "security", "belonging")


def start_state():
    return {"energy": 1.0, "warmth": 1.0, "security": 0.5, "belonging": 0.5}


def clip(value, low, high):
    return max(low, min(high, value))


def horizon(cfg):
    return cfg["horizon_R1"] if cfg["mode"] == "R1" else cfg["horizon_R2"]


def security(fish, fuel, game, cfg):
    """Reserves against the needs of the next few seasons. More than enough is simply enough, so this saturates at 1."""
    seasons = horizon(cfg)
    return 0.5 * min(1.0, fish / (seasons * game["eat_need"])) + 0.5 * min(1.0, fuel / (seasons * game["burn_need"]))


def next_state(h, eaten, burned, fish, fuel, messages, others, trades, game, cfg):
    """The body after a season: food and fuel at exactly the need hold energy and warmth where they were."""
    target = cfg["belonging_message_weight"] * (messages / others if others else 0.0) + cfg["belonging_trade_weight"] * min(trades, 2)
    smooth = cfg["belonging_smoothing"]
    return {"energy": clip(h["energy"] - 0.5 + 0.5 * eaten / game["eat_need"], 0.0, 1.5),
            "warmth": clip(h["warmth"] - 0.5 + 0.5 * burned / game["burn_need"], 0.0, 1.5),
            "security": security(fish, fuel, game, cfg),
            "belonging": clip(smooth * h["belonging"] + (1 - smooth) * target, 0.0, 1.0)}


def drive(h, cfg):
    """D(h) = (sum_i w_i * |setpoint_i - h_i|^n)^(1/m). With n > m, the worst-off need dominates."""
    total = sum(cfg["weights"][k] * abs(cfg["setpoints"][k] - h[k]) ** cfg["n"] for k in KEYS)
    return total ** (1 / cfg["m"])


def reward(before, after, invested_before, invested_after, cfg):
    """R1 and R2 are drive reduction (they differ in the security horizon); R3 adds progress on the personal project."""
    value = drive(before, cfg) - drive(after, cfg)
    if cfg["mode"] == "R3":
        value += cfg["lambda"] * (math.log1p(invested_after) - math.log1p(invested_before))
    return value
