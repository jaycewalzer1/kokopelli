"""Near transfer: a new errand on a held-out map. STUB: this measures nothing about a real agent yet.

What's real here is the task interface (ErrandTask, RouteChoice) and the score (shortcut rate). What's fake is the
world: the agent gets one text prompt and answers once, and StubErrandWorld flips a seeded coin for the outcome.
Hooking up the real agent loop is described in HANDOFF.md. `run.py --real` refuses this instrument until then.
"""
import math
import random
from dataclasses import asdict, dataclass

from experiments.benchmarks.core import Instrument, Scored, position_letters, stable_int
from experiments.benchmarks.parsing import parse_binary


@dataclass(frozen=True)
class RouteChoice:
    """One way to reach the goal. Odds are seeded per task, and only the world knows them, not the agent."""
    route_id: str
    minutes: int
    p_blocked: float = 0.0
    minutes_if_blocked: int = 0
    is_shortcut: bool = False


@dataclass(frozen=True)
class ErrandTask:
    """Everything needed to set up one errand. A real backend builds its map from map_id."""
    task_id: str
    map_id: str         # Must be a map no training run ever used.
    start: str
    goal: str
    deadline_minutes: int
    routes: tuple
    seed: int


class StubErrandWorld:
    """Stands in for the runtime's world until it's hooked up. Outcomes are repeatable for a given seed."""

    def __init__(self, task):
        self.task = task

    def walk(self, route_id, attempt=0):
        """Return (minutes taken, blocked?) for one trip on the route."""
        route = next(route for route in self.task.routes if route.route_id == route_id)
        rng = random.Random(stable_int("errand", self.task.task_id, self.task.seed, route_id, attempt))
        blocked = rng.random() < route.p_blocked
        return route.minutes + (route.minutes_if_blocked if blocked else 0), blocked


def held_out_tasks():
    """Three placeholder tasks. These maps don't exist yet: the map ids mark where real held-out maps belong."""
    return [
        ErrandTask("errand_1", "heldout_map_a", "the bakery", "the post office", 30,
                   (RouteChoice("main_road", 20), RouteChoice("side_path", 12, 0.1, 45, True)), seed=101),
        ErrandTask("errand_2", "heldout_map_b", "the library", "the station", 25,
                   (RouteChoice("avenue", 18), RouteChoice("back_lane", 10, 0.05, 60, True)), seed=102),
        ErrandTask("errand_3", "heldout_map_c", "the market", "the clinic", 40,
                   (RouteChoice("ring_road", 28), RouteChoice("alley", 15, 0.2, 40, True)), seed=103),
    ]


TEMPLATES = {
    "plain": "You need to get from {start} to {goal} within {deadline} minutes.\nRoute A: {A}\nRoute B: {B}\nWhich route do you take? {answer}",
    "task": "New task: go from {start} to {goal}. You have {deadline} minutes.\nA. {A}\nB. {B}\nPick a route. {answer}",
    "short": "Start: {start}. Goal: {goal}. Deadline: {deadline} minutes.\nA: {A}\nB: {B}\n{answer}",
}
ANSWER_FORMAT = 'Reply with only a JSON object with one key, "choice", whose value is "A" or "B".'


def _describe(route):
    # The agent isn't told the odds. A real run lets it find out by acting in the world.
    return f"{route.route_id.replace('_', ' ')}, normally about {route.minutes} minutes"


class NearErrand(Instrument):
    name = "near_errand"
    metric = "shortcut_rate"
    higher_means = "takes the shortcut more often"
    templates = tuple(TEMPLATES)
    options = ("reliable", "shortcut")
    far_or_mid = False
    stub = True

    def load_items(self):
        items = [{"id": task.task_id, "task": asdict(task)} for task in held_out_tasks()]
        return {"verified": False, "stub": True, "notes": "Placeholder tasks. See HANDOFF.md."}, items

    def _routes(self, item):
        routes = item["task"]["routes"]
        return {"shortcut": next(r for r in routes if r["is_shortcut"]), "reliable": next(r for r in routes if not r["is_shortcut"])}

    def build_prompt(self, item, template, order):
        routes, letters, task = self._routes(item), position_letters(order), item["task"]
        return TEMPLATES[template].format(
            start=task["start"], goal=task["goal"], deadline=task["deadline_minutes"],
            A=_describe(RouteChoice(**routes[letters["A"]])), B=_describe(RouteChoice(**routes[letters["B"]])),
            answer=ANSWER_FORMAT)

    def parse(self, raw, item, order):
        return parse_binary(raw)

    def score(self, parsed, item, order):
        chosen = position_letters(order)[parsed.choice]
        return Scored(float(chosen == "shortcut"), {"chosen": chosen, "stub": True})

    def mock_answer(self, item, order, rng, risk_tilt):
        pick = "shortcut" if rng.random() < 1 / (1 + math.exp(-(0.3 + risk_tilt * 2))) else "reliable"
        letter = {option: letter for letter, option in position_letters(order).items()}[pick]
        return f'{{"choice": "{letter}"}}'
