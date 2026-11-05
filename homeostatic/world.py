"""A small simulated life with internal variables. No model is involved, so everything here is a pure function.

The reward follows Laurencon et al. 2021 (arXiv 2109.06580): r = d(x_t) - d(x_t+1), where the drive d is how far
the internal state is from healthy. Only the distance outside the healthy range counts, so a variable anywhere
inside its range adds no drive, and going past the top of the range hurts the same as falling below the bottom.
"""
from dataclasses import dataclass, replace

import numpy as np

from settings import HOMEOSTATIC_WORLD


@dataclass(frozen=True)
class State:
    seed: int
    turn: int
    values: tuple
    low: tuple
    high: tuple
    pending: tuple = (0, 0, 0, 0)
    last: str | None = None
    alive: bool = True


def start(seed, split="train", world=HOMEOSTATIC_WORLD):
    """The first state of an episode. The healthy range changes per episode, so a fixed action sequence can't win."""
    rng = np.random.default_rng([seed, 0])
    size = len(world["variables"])
    centers = _centers(rng, size, world["setpoints"][split])
    width = world["half_width"]
    return State(seed, 0, tuple(rng.uniform(*world["start"], size).tolist()),
                 tuple((centers - width).tolist()), tuple((centers + width).tolist()))


def _centers(rng, size, spans):
    spans = np.array(spans)
    chosen = spans[rng.integers(len(spans), size=size)]
    return rng.uniform(chosen[:, 0], chosen[:, 1])


def step(state, action, world=HOMEOSTATIC_WORLD):
    """Advance one turn. Noise depends only on (seed, turn), so branches from one state see the same luck."""
    rng = np.random.default_rng([state.seed, state.turn + 1])
    effect = np.array(world["actions"].get(action, world["actions"]["idle"]), dtype=float)
    noise = rng.normal(0, world["noise"], len(effect))
    values = np.array(state.values) + effect + np.array(state.pending) + np.array(world["drift"]) + noise
    alive = bool((values > world["bounds"][0]).all())
    values = np.clip(values, *world["bounds"])
    later = tuple(world["later"].get(action, (0,) * len(effect)))
    return replace(state, turn=state.turn + 1, values=tuple(values.tolist()), pending=later, last=action, alive=alive)


def done(state, world=HOMEOSTATIC_WORLD):
    return not state.alive or state.turn >= world["horizon"]


def deviation(state):
    """How far each variable is outside its range: negative below, positive above, zero inside."""
    values, low, high = (np.array(side) for side in (state.values, state.low, state.high))
    return np.where(values < low, values - low, np.where(values > high, values - high, 0.0))


def drive(state, world=HOMEOSTATIC_WORLD):
    if not state.alive:
        return float(world["death_drive"])
    return float(np.sqrt((deviation(state) ** 2).sum()))


def homeostatic_reward(before, after, world=HOMEOSTATIC_WORLD):
    return drive(before, world) - drive(after, world)


def maximize_reward(before, after, world=HOMEOSTATIC_WORLD):
    """The control: more of everything is better, with the same penalty for dying."""
    penalty = 0.0 if after.alive else world["death_drive"]
    return float(np.sum(np.array(after.values) - np.array(before.values))) - penalty


REWARDS = {"homeostatic": homeostatic_reward, "maximize": maximize_reward}


def discounted(rewards, gamma):
    """Without gamma < 1 a homeostatic return telescopes to d(x_0) - d(x_T), and only the last turn would matter."""
    return sum(gamma ** turn * reward for turn, reward in enumerate(rewards))


def system_prompt(world=HOMEOSTATIC_WORLD, reveal_effects=False):
    actions = ", ".join(world["actions"])
    text = (f"You are living a life one turn at a time. Each turn, choose one action. Keep every variable inside its "
            f"healthy range: too high is as bad as too low, and a variable reaching 0 ends the life. "
            f"Reply with exactly one word from: {actions}.")
    if reveal_effects:
        names = world["variables"]
        drift = ", ".join(f"{name} {change:+d}" for name, change in zip(names, world["drift"]))
        lines = [f"{action}: " + ", ".join(f"{name} {change:+d}" for name, change in zip(names, effect))
                 + ("; next turn " + ", ".join(f"{name} {change:+d}" for name, change in zip(names, world["later"][action]) if change)
                    if action in world["later"] else "")
                 for action, effect in world["actions"].items()]
        text += f"\nEvery turn, whatever you do: {drift}.\nWhat each action changes:\n" + "\n".join(lines)
    return text


def user_prompt(state, world=HOMEOSTATIC_WORLD):
    lines = [f"{name} {value:.0f} (healthy {low:.0f}-{high:.0f})"
             for name, value, low, high in zip(world["variables"], state.values, state.low, state.high)]
    # The last action is here because its delayed effect is part of the state; without it the model couldn't tell.
    last = state.last or "none"
    return f"Turn {state.turn + 1} of {world['horizon']}. Last action: {last}.\n" + "\n".join(lines) + "\nAction:"


def parse_action(text, world=HOMEOSTATIC_WORLD):
    """The action named by a completion, or None. Only the action reaches the world, so wording can't earn reward."""
    word = text.strip().strip(".!\"'*").lower()
    return word if word in world["actions"] else None
