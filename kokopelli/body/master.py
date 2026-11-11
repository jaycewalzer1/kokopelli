"""The game master for the body: the agent says what it tries to do, the world says what happened.

    body, outcome, reason = resolve(body, "give")

The agent only ever attempts. Whether an egg moves, and what that does to the body, is decided here by the rules in
kokopelli/body/state.py, never by the model's say-so. The idea is Concordia's game master, which turns an attempted
action into an event (vendor/concordia_patterns/SOURCE.md). Theirs asks a language model whether the attempt
succeeds and why; ours looks it up in a table, so the same attempt on the same body always ends the same way.
"""
from typing import Literal

from kokopelli.body import state
from kokopelli.body.state import Body

Outcome = Literal["done", "refused", "no_rule"]
DONE: Outcome = "done"          # the world applied the action; the body returned is the new one
REFUSED: Outcome = "refused"    # the world said no; the body is unchanged and reason says why, in words for the agent
NO_RULE: Outcome = "no_rule"    # not a body action (say, wait, walk): nothing here changes, the loop handles it


def resolve(body: Body, action: str) -> tuple[Body, Outcome, str | None]:
    """What the world makes of one attempted action. Never raises for an action it doesn't know or can't allow."""
    if action not in state.ACTIONS:
        return body, NO_RULE, None
    try:
        return state.act(body, action), DONE, None
    except state.CantDoThat as refused:
        return body, REFUSED, str(refused)
