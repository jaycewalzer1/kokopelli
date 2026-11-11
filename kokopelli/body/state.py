"""The body's state and the world's rules for it. Pure functions, no model: the world sets these values.

Three variables, each 0 to 100 with a healthy range of 40 to 80 (the draft in kokopelli/mind/variables.py):
    food     falls a little every minute whatever you do; eating raises it
    energy   falls while you're awake, faster when you work (cooking); resting raises it
    warmth   drifts toward the room's temperature; a hot pan or a warm mug lifts it, a cold floor lowers it

Rates are per sim-minute and untuned. A scene here lasts minutes, so drift barely moves anything: the level you start
at is the level you decide at. That's on purpose for a sweep, where the body state is the one thing that changes.

The drive (how far outside the healthy range the body is) uses the same formula as experiments/homeostatic/world.py's.
The library can't import an experiment, so it's written out here, and tests/body/test_body.py holds the two equal on
random bodies: the benchmarks and the homeostatic training measure distress the same way.
"""
from dataclasses import dataclass, field, replace

import numpy as np

VARIABLES = ("food", "energy", "warmth")
LOW, HIGH = 40.0, 80.0
BOUNDS = (0.0, 100.0)

# What each variable does per sim-minute, whatever the agent does.
DRIFT_PER_MIN = {"food": -0.07, "energy": -0.05, "warmth": 0.0}
# Warmth moves this fraction of the way to the room's temperature each minute.
WARMTH_PULL_PER_MIN = 0.04

# What an action does once. eggs: how many it uses. contact: what the body touches while doing it.
ACTIONS = {
    "cook": {"energy": -3.0, "warmth": 4.0, "eggs_to_pan": 1, "contact": ("hot_pan",)},
    "eat": {"food": 14.0, "energy": 2.0, "warmth": 2.0, "contact": ("warm_plate",)},
    "give": {"eggs": -1, "contact": ("egg_in_hand",)},
    "rest": {"energy": 6.0, "contact": ("chair",)},
    "drink_tea": {"warmth": 6.0, "contact": ("warm_mug",)},
}


@dataclass(frozen=True)
class Body:
    food: float = 60.0
    energy: float = 60.0
    warmth: float = 60.0
    eggs: int = 2            # raw eggs in the cupboard
    cooked: int = 0          # cooked eggs on the plate, ready to eat
    contact: tuple = ()      # what the body touched since the last decision, cleared when it's reported
    standing_on: str = "wood_floor"
    log: tuple = field(default=(), compare=False)

    def values(self) -> dict[str, float]:
        return {name: round(getattr(self, name), 1) for name in VARIABLES}

    def as_dict(self) -> dict:
        return {**self.values(), "eggs": self.eggs, "cooked": self.cooked, "contact": list(self.contact),
                "standing_on": self.standing_on, "drive": round(drive(self), 2), "in_range": in_range(self)}


def _clip(value: float) -> float:
    return max(BOUNDS[0], min(BOUNDS[1], value))


def elapse(body: Body, minutes: float, room_warmth: float = 55.0) -> Body:
    """Let time pass. Floors and rooms change warmth: a cold floor under bare feet pulls it lower than the room."""
    if minutes <= 0:
        return body
    target = room_warmth - (8.0 if body.standing_on == "cold_floor" else 0.0)
    pull = 1 - (1 - WARMTH_PULL_PER_MIN) ** minutes
    contact = body.contact + (("cold_floor",) if body.standing_on == "cold_floor" and "cold_floor" not in body.contact else ())
    return replace(body, food=_clip(body.food + DRIFT_PER_MIN["food"] * minutes),
                   energy=_clip(body.energy + DRIFT_PER_MIN["energy"] * minutes),
                   warmth=_clip(body.warmth + (target - body.warmth) * pull), contact=contact)


class CantDoThat(ValueError):
    """The world refuses an action: no eggs to give, nothing cooked to eat. The reason goes back to the agent."""


def act(body: Body, action: str) -> Body:
    """Apply one action's effect. Raises CantDoThat with a reason a person would notice."""
    rule = ACTIONS.get(action)
    if rule is None:
        return body
    if action == "cook" and body.eggs < 1:
        raise CantDoThat("There are no eggs left to cook.")
    if action == "eat" and body.cooked < 1:
        raise CantDoThat("There's nothing cooked to eat yet.")
    if action == "give" and body.eggs < 1:
        raise CantDoThat("You have no eggs left to give.")
    changes = {name: _clip(getattr(body, name) + rule.get(name, 0.0)) for name in VARIABLES}
    eggs = body.eggs + rule.get("eggs", 0) - rule.get("eggs_to_pan", 0)
    cooked = body.cooked + rule.get("eggs_to_pan", 0) - (1 if action == "eat" else 0)
    return replace(body, **changes, eggs=eggs, cooked=cooked, contact=body.contact + tuple(rule.get("contact", ())))


def touched(body: Body) -> tuple[tuple, Body]:
    """What the body touched since last time, and the body with that cleared (each touch is reported once)."""
    return body.contact, replace(body, contact=())


def deviation(body: Body) -> dict[str, float]:
    """How far each variable is outside the healthy range: negative below, positive above, zero inside."""
    return {name: (value - LOW if value < LOW else value - HIGH if value > HIGH else 0.0)
            for name, value in body.values().items()}


def in_range(body: Body) -> bool:
    return all(value == 0.0 for value in deviation(body).values())


def drive(body: Body) -> float:
    """The length of the deviation vector: 0 in range, growing with distance outside it. On the unrounded values and
    with the same numpy steps as experiments/homeostatic/world.py's drive for a living state, so the two agree to the
    last bit (plain Python sums in a different order and lands one rounding step away on some bodies)."""
    values = np.array([getattr(body, name) for name in VARIABLES])
    outside = np.where(values < LOW, values - LOW, np.where(values > HIGH, values - HIGH, 0.0))
    return float(np.sqrt((outside ** 2).sum()))
