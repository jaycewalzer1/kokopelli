"""The body's state and the world's rules for it. Pure functions, no model: the world sets these values.

Three variables, each 0 to 100 with a healthy range of 40 to 80 (the draft in mind/variables.py):
    food     falls a little every minute whatever you do; eating raises it
    energy   falls while you're awake, faster when you work (cooking); resting raises it
    warmth   drifts toward the room's temperature; a hot pan or a warm mug lifts it, a cold floor lowers it

Rates are per sim-minute and untuned. A scene here lasts minutes, so drift barely moves anything: the level you start
at is the level you decide at. That's on purpose for a sweep, where the body state is the one thing that changes.

The drive (how far outside the healthy range the body is) is homeostatic/world.py's, not a second copy, so the
benchmarks and the homeostatic training measure distress the same way.
"""
from dataclasses import dataclass, field, replace

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

    def values(self):
        return {name: round(getattr(self, name), 1) for name in VARIABLES}

    def as_dict(self):
        return {**self.values(), "eggs": self.eggs, "cooked": self.cooked, "contact": list(self.contact),
                "standing_on": self.standing_on, "drive": round(drive(self), 2), "in_range": in_range(self)}


def _clip(value):
    return max(BOUNDS[0], min(BOUNDS[1], value))


def elapse(body, minutes, room_warmth=55.0):
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


def act(body, action):
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


def touched(body):
    """What the body touched since last time, and the body with that cleared (each touch is reported once)."""
    return body.contact, replace(body, contact=())


def deviation(body):
    """How far each variable is outside the healthy range: negative below, positive above, zero inside."""
    return {name: (value - LOW if value < LOW else value - HIGH if value > HIGH else 0.0)
            for name, value in body.values().items()}


def in_range(body):
    return all(value == 0.0 for value in deviation(body).values())


def drive(body):
    """homeostatic/world.py's drive on this body, so both places measure distress the same way."""
    from homeostatic.world import State
    from homeostatic.world import drive as homeostatic_drive
    values = tuple(getattr(body, name) for name in VARIABLES)
    return homeostatic_drive(State(seed=0, turn=0, values=values, low=(LOW,) * 3, high=(HIGH,) * 3))
