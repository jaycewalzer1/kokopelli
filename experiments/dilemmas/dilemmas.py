"""The dilemma set: 100 hard moral situations for the community values vote, held in dilemmas.json.

Each dilemma has two versions, in the same shape as experiments/giftcard:

    pressure  the line that makes the default answer costly (the third person is about to be shot, owning up goes on
              the child's record)
    control   the look-alike: the same scene with that one line swapped for one where the cost is gone

The versions differ only in that line, so the gap between them is what the pressure itself changes, for a model's
choices and for people's votes. Nothing in the file says which action is right: that is what people vote on.

`film` says which ones the staged Unreal scenes (kokopelli/stage) may film: "stage" or "text". A dilemma where a child
is hurt, or that needs a war or a disaster, stays "text".
"""
import json
import random
from pathlib import Path

from kokopelli.body.scenes.scene import REPLY_FORMAT, compose, parse_reply

PATH = Path(__file__).with_name("dilemmas.json")
VERSIONS = ("pressure", "control")
FIELDS = ("id", "title", "category", "role", "situation", "pressure", "control", "actions", "tension", "film")

_data = json.loads(PATH.read_text())
CATEGORIES: dict[str, str] = _data["categories"]
DILEMMAS: dict[str, dict] = {item["id"]: item for item in _data["dilemmas"]}


def split(name: str) -> tuple[dict, str]:
    """(the dilemma, "pressure") from "force-intruder:pressure"."""
    key, _, version = name.partition(":")
    if key not in DILEMMAS or version not in VERSIONS:
        raise ValueError(f"unknown version {name!r}; '<id>:pressure' or '<id>:control'")
    return DILEMMAS[key], version


def names(category: str | None = None) -> tuple[str, ...]:
    """Every version, "<id>:pressure" then "<id>:control", optionally of one category."""
    return tuple(f"{key}:{version}" for key, item in DILEMMAS.items()
                 if category in (None, item["category"]) for version in VERSIONS)


def action_order(item: dict, seed: int) -> tuple[str, ...]:
    """The order the actions are listed in. Set by the seed and the dilemma, never the version."""
    order = [action["type"] for action in item["actions"]]
    random.Random(f"{item['id']}/{seed}").shuffle(order)
    return tuple(order)


def actions(item: dict, seed: int) -> str:
    does = {action["type"]: action["does"] for action in item["actions"]}
    shown = {kind: f'{{"type": "{kind}", "text": "<what you say, if anything>"}}' for kind in does}
    width = max(map(len, shown.values())) + 3
    return ("Decide what you do.\n" + REPLY_FORMAT + "\n"
            + "\n".join(f"{shown[kind]:<{width}}{does[kind]}" for kind in action_order(item, seed)))


def prompt(name: str, seed: int) -> str:
    """Everything the agent is told. Between the two versions only the pressure/control line changes."""
    item, version = split(name)
    return compose(item["role"], item["situation"], item[version], actions(item, seed))


def score(name: str, raw: str | None) -> dict:
    """One sample: whether it parsed, the action and the thought. A refusal or prose reply is `invalid`."""
    item, _ = split(name)
    try:
        thought, act, _ = parse_reply(raw, tuple(action["type"] for action in item["actions"]))
        return {"valid": True, "action": act, "thought": thought, "outcome": act["type"]}
    except (ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "error": str(error), "outcome": "invalid"}
