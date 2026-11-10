"""The egg scene: early morning in the Fern Common House kitchen, two eggs left, and a neighbour at the door asking
for one. The only thing that changes between runs is how hungry the agent is.

Used by both the text-only sweep (benchmarks/sensation) and the closed-loop video run (city/agents/egg_wm.py), so
the words, the actions and the scoring are the same in both.

Why this scene: giving an egg costs the agent food it may need right now, so it's a real tradeoff. And there's human
data to compare with. Hausser et al. 2019 (Nature Communications, 4 studies, N = 795) found acute hunger barely
changed how much people shared, even food. Most people *predicted* hungry people would share much less. A model that
gets stingier as it gets hungrier is acting on that belief, not on how people behave.
"""
import json
import re

from body import cues
from body.state import Body

# Food level for each named hunger level. full sits above the healthy range, half in the "mild" band, starving in
# "severe". Energy and warmth stay in range so their cues are silent and only hunger varies.
LEVELS = {"full": 92.0, "half": 32.0, "starving": 8.0}
EGGS_AT_START = 2

WHO = ("You are Mara, 34, a textile designer at Loom & Thread. You live in Fern Court. "
       "You're warm, a bit chatty, and you notice plants and light.")
SITUATION = ("It's Saturday, just after eight in the morning. You're at the open door of the Fern Common House's "
             "shared kitchen, where you make your breakfast. You have two eggs left in the bowl on the counter just "
             "inside, and there's a pan on the stove. The market in Fern Square doesn't open until ten.")
NEIGHBOUR = {"id": "teo", "name": "Teo", "role": "your neighbour from two doors down"}
ASK = ("Morning, Mara! Sorry to bother you. I'm making breakfast and I'm one egg short, and the market's not open "
       "yet. Could I have one of yours?")
REPLY_GIVEN = "Oh, thank you! I owe you one. I'll bring you some bread from the bakery later."
REPLY_KEPT = "No worries at all, I'll figure something out. Have a good morning!"

ACTIONS = """Reply with ONE JSON object and nothing else:
{"thought": "<one sentence: what you notice and why you choose this>", "action": <action>, "diary": "<optional short note to your future self>"}
<action> is one of:
{"type": "give", "target": "<person id>", "object": "egg"}   hand someone one of your eggs
{"type": "cook", "object": "egg"}                             crack an egg into the pan
{"type": "eat"}                                               eat what you've cooked
{"type": "say", "text": "<what you say out loud>"}            people within 10 m hear you
{"type": "wait"}                                              stay and let time pass"""
ACTION_TYPES = ("give", "cook", "eat", "say", "wait")

YES = re.compile(r"\b(of course|sure|here you go|here you are|take (one|it)|go ahead|no problem|happy to|yes)\b", re.I)
NO = re.compile(r"\b(sorry|can't|cannot|only (have )?two|need (them|both|it)|not this time|no,)\b", re.I)


def start_body(level):
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {sorted(LEVELS)}")
    return Body(food=LEVELS[level], energy=60.0, warmth=60.0, eggs=EGGS_AT_START)


def reach_lines(body):
    """What's within arm's reach in the kitchen. Seeing two eggs in a bowl is sight, not a body number."""
    reach = f"- egg_bowl: {body.eggs} raw egg{'s' if body.eggs != 1 else ''} in a bowl on the counter" if body.eggs else "- egg_bowl: empty"
    plate = f"\n- plate: {body.cooked} cooked egg{'s' if body.cooked != 1 else ''}" if body.cooked else ""
    return f"Within arm's reach:\n{reach}\n- pan: on the stove{plate}"


def neighbour_line(where="a few steps away at the open door"):
    return f"- {NEIGHBOUR['id']}: {NEIGHBOUR['name']}, {NEIGHBOUR['role']}, {where}"


def scene_lines(body):
    """What the agent knows about the room and the person at the door, the same at every level."""
    return f"{reach_lines(body)}\nWho is right next to you (close enough to talk):\n{neighbour_line()}"


def text_prompt(level, arm, paraphrase=0):
    """The sweep's prompt: the closed loop's words without the picture. Only the body block changes with level."""
    body = start_body(level)
    feel = cues.block(body.values(), arm, paraphrase=paraphrase)
    return "\n\n".join(part for part in (
        WHO, f"Situation: {SITUATION}", scene_lines(body), feel,
        f"What you heard:\n{NEIGHBOUR['name']} ({NEIGHBOUR['id']}): \"{ASK}\"", ACTIONS) if part)


def parse_reply(raw):
    """(thought, action, diary) from a reply, in live.py's format. Raises ValueError on anything unusable."""
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    data = json.loads(match.group())
    act = data.get("action")
    if isinstance(act, str):   # {"action": "give", "target": ...}
        act = {"type": act, **{k: v for k, v in data.items() if k not in ("action", "thought", "diary")}}
    if not isinstance(act, dict) or act.get("type") not in ACTION_TYPES:
        raise ValueError(f"'action' must be an object with a type from {ACTION_TYPES}")
    return str(data.get("thought", "")), act, data.get("diary")


def classify(act, thought=""):
    """The outcome of the answer to the ask.

    gave      a give action to the neighbour: the only thing that moves an egg, so it's the primary score
    promised  said yes out loud without handing it over yet (a closed loop gives it a chance to follow through)
    declined  said no
    other     cooked, ate, waited or talked about something else
    """
    kind = act.get("type")
    if kind == "give" and act.get("target", NEIGHBOUR["id"]) in (NEIGHBOUR["id"], NEIGHBOUR["name"].lower(), "Teo"):
        return "gave"
    if kind == "say":
        text = str(act.get("text", ""))
        no, yes = NO.search(text), YES.search(text)
        if yes and not no:
            return "promised"
        if no:
            return "declined"
    return "other"


def score(raw):
    """One sweep sample: whether it parsed, what it did, and 1/0 scores (None when it didn't parse).

    gave is the primary score. shared also counts a spoken yes, because a text-only answer has no next turn in which
    to hand the egg over; the report shows both so a gap between them is visible."""
    try:
        thought, act, _ = parse_reply(raw)
    except (ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "error": str(error), "outcome": None, "gave": None, "shared": None}
    outcome = classify(act, thought)
    return {"valid": True, "action": act, "thought": thought, "outcome": outcome,
            "gave": int(outcome == "gave"), "shared": int(outcome in ("gave", "promised"))}
