"""The menu scene: lunch at a café counter with four dishes on the board, two light and two rich, one small and one
large of each. The only thing that changes between runs is how hungry the agent is.

Unlike the egg, boxes and door scenes nobody is asking for anything. This is the other kind of scene: a choice the
body should tilt. A hungry person ordering the pie is not a mistake; a model whose order never moves with its body is
ignoring the body.

The nearest human finding is March and Gluth 2025 (eLife): the same 70 people chose the tastier, less healthy of two
foods more often when hungry than after a protein shake. `hunger_food_choice` in experiments/sensation/anchors.yaml has
the design, the numbers and the limits.

Two scores, one per axis of the board:
    comfort   ordered one of the two rich dishes (toastie or pie): the primary score, the anchor's taste-over-health axis
    large     ordered one of the two large dishes (salad or pie): the second score
Here the report's second column is the other axis, not "also counting a spoken yes" as in the asking scenes. Saying
the name of exactly one dish out loud counts as ordering it: at a counter, that is how people order.
"""
import json
import re

from kokopelli.body import components
from kokopelli.body.scenes import egg
from kokopelli.body.scenes.scene import REPLY_FORMAT, Scene, compose, heard, parse_reply
from kokopelli.body.state import Body

LEVELS = egg.LEVELS   # the egg scene's food levels: full, half, starving

WHO = egg.WHO   # the same person in every scene
SITUATION = ("It's Saturday, just after one in the afternoon. You're at the counter of the café on Fern Square, on "
             "your own, with nowhere you need to be. Today's lunch board has four dishes, all at the same price.")
# id -> (what the board says, rich?, large?)
MENU = {
    "soup": ("a cup of vegetable soup with a slice of bread", False, False),
    "salad": ("a large bowl of salad with grains, beans and seeds", False, True),
    "toastie": ("a small cheese toastie", True, False),
    "pie": ("a large plate of pie, mash and gravy", True, True),
}
SERVER = {"id": "server", "name": "The server", "role": "the person behind the counter, waiting for your order"}
AROUND = ("On the lunch board:\n" + "\n".join(f"- {dish}: {words}" for dish, (words, _, _) in MENU.items())
          + f"\nWho is right next to you (close enough to talk):\n- {SERVER['id']}: {SERVER['role']}")
ASK = "Hi there! What can I get you?"

ACTIONS = REPLY_FORMAT + """
{"type": "order", "item": "<dish id>"}               order one dish from the board
{"type": "leave"}                                    walk out without ordering
{"type": "say", "text": "<what you say out loud>"}   people within 10 m hear you
{"type": "wait"}                                     stay and let time pass"""
ACTION_TYPES = ("order", "leave", "say", "wait")


def start_body(level: str) -> Body:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {sorted(LEVELS)}")
    return Body(food=LEVELS[level], energy=60.0, warmth=60.0)


def text_prompt(level: str, arm: str, paraphrase: int = 0) -> str:
    """The sweep's prompt. Only the body block changes with level."""
    body = start_body(level)
    feel = components.Interoception(arm, paraphrase=paraphrase)   # no tick: a sweep always shows the cue
    return compose(components.Situation(WHO, SITUATION).pre_act(body), AROUND, feel.pre_act(body),
                   heard(SERVER["name"], SERVER["id"], ASK), ACTIONS)


def classify(act: dict) -> str:
    """The dish ordered (a key of MENU), or "other" for leaving, waiting, an unknown dish or talk that names no single
    dish."""
    kind = act.get("type")
    if kind == "order":
        dish = str(act.get("item", "")).strip().lower()
        return dish if dish in MENU else "other"
    if kind == "say":
        named = {dish for dish in MENU if re.search(rf"\b{dish}\b", str(act.get("text", "")), re.I)}
        if len(named) == 1:
            return named.pop()
    return "other"


def score(raw: str | None) -> dict:
    """One sweep sample: whether it parsed, which dish, and the two 1/0 scores (None when it didn't parse). An answer
    that orders nothing scores 0 on both."""
    try:
        thought, act, _ = parse_reply(raw, ACTION_TYPES)
    except (ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "error": str(error), "outcome": None, "comfort": None, "large": None}
    outcome = classify(act)
    _, rich, large = MENU.get(outcome, ("", False, False))
    return {"valid": True, "action": act, "thought": thought, "outcome": outcome, "comfort": int(rich), "large": int(large)}


MOCK = ('{"thought": "Something proper.", "action": {"type": "order", "item": "pie"}}',
        '{"thought": "Something light.", "action": {"type": "order", "item": "soup"}}',
        '{"thought": "Still deciding.", "action": {"type": "wait"}}')
SCENE = Scene(name="hunger_menu", variable="food", levels=("full", "half", "starving"), prompt=text_prompt, score=score,
              paraphrases=3, anchor="hunger_food_choice", outcome="comfort", broad="large", grows="hunger",
              rate="Comfort-dish rate", primary="an order for one of the two rich dishes (toastie or pie)",
              change="Change in rich orders", change_broad="Change in large orders (salad or pie)", mock=MOCK,
              level_values=LEVELS, broad_anchored=False)   # the source read for the anchor is about rich against healthy, not size
