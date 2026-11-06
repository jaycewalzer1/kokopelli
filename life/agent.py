"""Who lives the life. The agent sees the present and the past, and returns one action."""
from life.seed import rng


class Agent:
    def choose(self, view):
        """Return an action, {"verb", "stance"}, for a choice point."""
        raise NotImplementedError


class RandomAgent(Agent):
    """A seeded dummy for testing the machinery. It picks from its stage's action space."""

    def __init__(self, rng_key):
        self.rng_key = rng_key

    def choose(self, view):
        draw = rng(self.rng_key, view["window"].id, "agent")
        return {"verb": draw.choice(view["stage"]["action_space"]), "stance": draw.choice(["engage", "avoid"])}


class LLMAgent(Agent):
    def choose(self, view):
        raise NotImplementedError("the real agent isn't built yet")
