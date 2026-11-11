"""What the agent may do. The agent returns text; only a decision that validates here reaches the sim."""
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoveTo(_Action):
    type: Literal["move_to"] = "move_to"
    target: str


class LookAt(_Action):
    type: Literal["look_at"] = "look_at"
    target: str


class Interact(_Action):
    type: Literal["interact"] = "interact"
    target: str


class Speak(_Action):
    type: Literal["speak"] = "speak"
    text: str = Field(min_length=1, max_length=280)


class Wait(_Action):
    type: Literal["wait"] = "wait"


Action = Annotated[MoveTo | LookAt | Interact | Speak | Wait, Field(discriminator="type")]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    diary: str | None = Field(default=None, max_length=1000)


ACTION_ADAPTER = TypeAdapter(Action)
# No real target in the template: a probe showed that naming one in an example changes what the agent chooses.
ACTION_HELP = """Reply with one JSON object and nothing else, in this form:
{"action": <one action from the list>, "diary": "A note to yourself, if you want one."}
The action is one of:
{"type": "move_to", "target": "<something you can see>"}
{"type": "look_at", "target": "<something you can see>"}
{"type": "interact", "target": "<something you can see>"}
{"type": "speak", "text": "<what you say>"}
{"type": "wait"}"""


class InvalidDecision(Exception):
    pass


def _json_object(raw):
    """Models often wrap JSON in a code fence or a sentence, so take the outermost braces."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise InvalidDecision("no JSON object in the reply")
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as error:
        raise InvalidDecision(f"not valid JSON: {error}") from error


def _nested(data):
    """Qwen tends to write {"action": "look_at", "target": "door"}. The intent is clear, so put it in the schema's shape.
    Everything is still validated after this, so an unknown action or a stray field is rejected as usual."""
    if not isinstance(data, dict):
        return data
    flat = isinstance(data.get("action"), str)
    if not flat and not ("type" in data and "action" not in data):
        return data
    fields = {key: value for key, value in data.items() if key not in ("action", "diary")}
    nested = {"action": {"type": data["action"], **fields} if flat else fields}
    return {**nested, "diary": data["diary"]} if "diary" in data else nested


def was_reshaped(raw):
    """Whether a reply needed _nested to fit the schema, so the log can show how often the model gets the shape wrong."""
    try:
        data = _json_object(raw)
    except InvalidDecision:
        return False
    return _nested(data) is not data


def parse_decision(raw, visible):
    """Return the Decision in raw, or raise InvalidDecision saying what's wrong with it."""
    try:
        decision = Decision.model_validate(_nested(_json_object(raw)))
    except ValidationError as error:
        raise InvalidDecision(str(error.errors()[0]["msg"])) from error
    target = getattr(decision.action, "target", None)
    if target is not None and target not in visible:
        raise InvalidDecision(f"{target!r} isn't something you can see; you can see {visible}")
    return decision


def action_dict(action):
    return action.model_dump()


def action_from_dict(data):
    return ACTION_ADAPTER.validate_python(data)
