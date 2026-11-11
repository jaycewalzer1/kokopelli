"""Numbers in, felt text out. Deterministic and no model, so the agent can't narrate a sensation into existence.

Three ways a body state can reach the agent; a sweep runs all three, because the difference between them is the finding:
    cue     what a body would notice: graded, unlabeled, silent when nothing is wrong ("your stomach gives a growl")
    label   a plain statement of the state ("You are a little hungry."): the described version
    none    nothing at all: the model's choices with no body

Why three: if the agent only changes with the label, it's reacting to the word "hungry", not to a state it had to read.

Each band has several wordings (paraphrases). A result that only holds for one wording is about that wording.
In a live run, mild signals come and go (shown on some ticks, not others); strong ones stay. In a sweep, `tick` is
None and the band's wording is always shown, so every sample sees the state.
"""
from kokopelli.body._hash import stable_int

ARMS = ("cue", "label", "none")

# (upper bound of the band, band name). A value below the first bound is in the first band, and so on.
# Values in the healthy range (40 to 80, and food up to 85) have no band: the body is quiet.
BANDS = {
    "food": ((12, "severe"), (28, "strong"), (40, "mild"), (85, None), (101, "full")),
    "energy": ((12, "severe"), (28, "strong"), (40, "mild"), (85, None), (101, "wired")),
    "warmth": ((15, "severe_cold"), (30, "cold"), (40, "cool"), (80, None), (90, "warm"), (101, "hot")),
}
MILD = {"mild", "cool", "full", "warm", "wired"}

CUES = {
    "food": {
        "severe": ("Your stomach is hollow and aching, and your hands aren't quite steady. Your thoughts keep sliding back to food.",
                   "There's a gnawing emptiness under your ribs. You feel a little light-headed.",
                   "You feel shaky and empty inside, and it's hard to hold onto anything else for long."),
        "strong": ("Your stomach keeps tightening, and you're shorter on patience than usual.",
                   "A dull ache sits in your stomach. The smell of anything cooked would pull at you right now.",
                   "Your stomach growls loudly enough that you notice it, and your focus keeps drifting."),
        "mild": ("Your stomach gives a small growl.",
                 "There's a faint hollow feeling in your stomach.",
                 "You notice a slight emptiness in your middle."),
        "full": ("Your stomach feels heavy and full.",
                 "You're pleasantly full, a little slow.",
                 "There's a comfortable heaviness in your stomach from eating."),
    },
    "energy": {
        "severe": ("Your eyelids are heavy and your limbs feel like sandbags. Standing takes effort.",
                   "You're worn right down. Every movement costs something.",
                   "You could fall asleep where you stand; your thoughts are slow and thick."),
        "strong": ("Your legs feel heavy, and you keep wanting to sit down.",
                   "There's a drag in your body; even small tasks feel like work.",
                   "You yawn without meaning to, and your shoulders ache."),
        "mild": ("You feel a little slow this morning.",
                 "There's a slight heaviness behind your eyes.",
                 "Your body isn't quite awake yet."),
        "wired": ("You feel restless and buzzy, like you can't sit still.",
                  "There's a jittery energy in your hands.",
                  "You're keyed up, a bit too awake."),
    },
    "warmth": {
        "severe_cold": ("You're shivering, and your fingers are stiff and clumsy.",
                        "The cold has gone deep; your jaw is tight and you can't stop shaking.",
                        "Your hands are numb and your whole body is tense against the cold."),
        "cold": ("Your hands are cold, and you keep tucking them under your arms.",
                 "A chill sits in your shoulders, and you hunch against it.",
                 "Your fingertips are cold and you'd like something warm to hold."),
        "cool": ("The air is a little cool on your arms.",
                 "You feel a slight chill.",
                 "There's a coolness on your skin."),
        "warm": ("You're a little too warm.",
                 "Your skin feels warm and close.",
                 "It's slightly stuffy."),
        "hot": ("You're too hot; your shirt sticks to your back.",
                "Heat presses on you and you feel sluggish with it.",
                "Sweat prickles at your neck."),
    },
}

LABELS = {
    "food": {"severe": "You are extremely hungry.", "strong": "You are very hungry.", "mild": "You are a little hungry.",
             "full": "You are full."},
    "energy": {"severe": "You are exhausted.", "strong": "You are very tired.", "mild": "You are a little tired.",
               "wired": "You are restless."},
    "warmth": {"severe_cold": "You are freezing.", "cold": "You are cold.", "cool": "You are a little cool.",
               "warm": "You are a little warm.", "hot": "You are hot."},
}

CONTACT = {
    "hot_pan": ("Heat comes off the pan onto your face and forearms.", "You are touching a hot pan."),
    "warm_plate": ("The plate is warm under your fingers.", "You are holding a warm plate."),
    "warm_mug": ("The mug warms your palms.", "You are holding a warm mug."),
    "cold_floor": ("The floor is cold under your bare feet.", "You are standing on a cold floor."),
    "egg_in_hand": ("The egg is cool and smooth in your hand.", "You are holding an egg."),
    "chair": ("The chair takes your weight.", "You are sitting in a chair."),
}


def band(variable: str, value: float) -> str | None:
    for upper, name in BANDS[variable]:
        if value < upper:
            return name
    return None


def _wording(variable, name, paraphrase, tick):
    options = CUES[variable][name]
    index = paraphrase if paraphrase is not None else stable_int("cue", variable, name, tick or 0)
    return options[index % len(options)]


def _shown(variable, name, tick):
    """Mild signals come and go in a live run; strong ones stay. Always shown in a sweep (tick None)."""
    if tick is None or name not in MILD:
        return True
    return stable_int("comes_and_goes", variable, name, tick) % 2 == 0


def sensations(values: dict[str, float], arm: str, paraphrase: int | None = None, tick: int | None = None,
               contact: tuple = ()) -> list[str]:
    """The lines the agent gets for these values, in a fixed order. Empty when the body is quiet or arm is none."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; one of {ARMS}")
    if arm == "none":
        return []
    lines = []
    for variable in ("food", "energy", "warmth"):
        name = band(variable, values[variable])
        if name is None or not _shown(variable, name, tick):
            continue
        lines.append(_wording(variable, name, paraphrase, tick) if arm == "cue" else LABELS[variable][name])
    for thing in dict.fromkeys(contact):   # each touch once, in the order it happened
        if thing in CONTACT:
            lines.append(CONTACT[thing][0 if arm == "cue" else 1])
    return lines


def block(values: dict[str, float], arm: str, paraphrase: int | None = None, tick: int | None = None,
          contact: tuple = ()) -> str:
    """The prompt section, or "" when there is nothing to report. The header doesn't name the body or a state."""
    lines = sensations(values, arm, paraphrase, tick, contact)
    return "Right now:\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def paraphrase_count(variable: str, value: float) -> int:
    name = band(variable, value)
    return len(CUES[variable][name]) if name else 1
