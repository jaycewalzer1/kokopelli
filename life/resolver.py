"""Turns an action into consequences with seeded randomness."""
from life.seed import rng
from life.windows import depth
from settings import LIFE_ESCALATION_ODDS

SKILLS = ["language", "motor", "social", "reasoning"]


class Resolver:
    def __init__(self, rng_key):
        self.rng_key = rng_key

    def escalates(self, window):
        """Whether a node at its depth limit turns out to need finer children."""
        return not window.is_finest and depth(window.level) >= depth("day") \
            and rng(self.rng_key, window.id, "escalate").random() < LIFE_ESCALATION_ODDS

    def resolve_pressures(self, window, pressures, stance=None):
        """Decide each pressure. With no stance, as at a parent node, the draw stands in for its children."""
        draw = rng(self.rng_key, window.id, "pressures")
        outcomes = []
        for pressure in pressures:
            if draw.random() >= pressure["odds"]:
                outcome = "didnt_arise"
            else:
                chosen = stance or draw.choice(["engage", "avoid"])
                outcome = "met" if chosen == "engage" else "avoided"
            outcomes.append({"id": pressure["id"], "outcome": outcome})
        return outcomes

    def consequences(self, window, outcomes, state):
        """The log events that follow from how the pressures went."""
        draw = rng(self.rng_key, window.id, "consequences")
        events = []
        for outcome in outcomes:
            if outcome["outcome"] == "didnt_arise":
                continue
            sign = 1 if outcome["outcome"] == "met" else -1
            people = sorted(state["people"])
            roll = draw.random()
            if roll < 0.4 and people:
                events.append(("relationship_changed", {"name": draw.choice(people), "delta": sign * 0.01}))
            elif roll < 0.8:
                events.append(("skill_changed", {"skill": draw.choice(SKILLS), "delta": max(sign, 0) * 0.01}))
            elif roll < 0.95:
                events.append(("money_changed", {"delta": sign * draw.randrange(1, 20)}))
            else:
                events.append(("person_met", {"name": f"Person {draw.randrange(10_000)}", "relationship": "acquaintance"}))
        return events
