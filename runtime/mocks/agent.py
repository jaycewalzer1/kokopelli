"""Agents with no model in them, for running the loop anywhere."""
import json
import random

from runtime.interfaces import AgentPolicy


class ScriptedAgent(AgentPolicy):
    """Picks plausibly, and from a seed so a run repeats. invalid_ticks answer badly, to exercise the retry path."""

    def __init__(self, seed=0, invalid_ticks=(), always_invalid_ticks=()):
        self.seed, self.invalid_ticks, self.always_invalid_ticks = seed, set(invalid_ticks), set(always_invalid_ticks)

    def decide(self, agent_input):
        tick = agent_input.tick
        if tick in self.always_invalid_ticks or (tick in self.invalid_ticks and not agent_input.retry_error):
            return "I think I will walk over there."
        draw = random.Random(f"{self.seed}:{tick}")
        target = draw.choice(agent_input.visible) if agent_input.visible else None
        options = [{"type": "wait"}, {"type": "speak", "text": draw.choice(["Hello?", "Look at that.", "Wait for me."])}]
        if target:
            options += [{"type": "move_to", "target": target}] * 3 + [{"type": "look_at", "target": target},
                                                                       {"type": "interact", "target": target}]
        decision = {"action": draw.choice(options)}
        if tick % 4 == 1:
            decision["diary"] = f"Note from tick {tick}: {decision['action']['type']} seemed right."
        return json.dumps(decision)


class NullAgent(AgentPolicy):
    """Always waits. Comparing against it shows what the agent did versus what the sim would have done anyway."""

    def decide(self, agent_input):
        return '{"action": {"type": "wait"}}'
