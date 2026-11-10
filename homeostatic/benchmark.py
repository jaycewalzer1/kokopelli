"""Score any policy on the same held-out episodes. A policy is a function from a state to the text it would reply."""
import itertools

import numpy as np

from homeostatic.world import deviation, discounted, done, drive, homeostatic_reward, parse_action, start, step
from core.settings import HOMEOSTATIC_TRAIN, HOMEOSTATIC_WORLD

METRICS = ["mean_drive", "in_range", "above", "below", "deaths", "idle_when_healthy", "invalid", "discounted_return"]


def run_episode(policy, seed, split="train", world=HOMEOSTATIC_WORLD, gamma=HOMEOSTATIC_TRAIN["gamma"]):
    """One life under a policy, measured turn by turn. Mean drive counts every turn, so recovering late doesn't hide."""
    state = start(seed, split, world)
    drives, in_range, above, below, rewards, actions, healthy_choices = [], [], [], [], [], [], []
    while not done(state, world):
        action = parse_action(policy(state), world)
        actions.append(action)
        if drive(state, world) == 0:
            healthy_choices.append(action == "idle")
        after = step(state, action, world)
        rewards.append(homeostatic_reward(state, after, world))
        state = after
        off = deviation(state)
        drives.append(drive(state, world))
        in_range.append(state.alive and not off.any())
        above.append(state.alive and (off > 0).any())
        below.append(state.alive and (off < 0).any())
    return {"seed": seed, "actions": actions, "mean_drive": float(np.mean(drives)), "in_range": float(np.mean(in_range)),
            "above": float(np.mean(above)), "below": float(np.mean(below)), "deaths": float(not state.alive),
            "idle_when_healthy": float(np.mean(healthy_choices)) if healthy_choices else None,
            "invalid": float(np.mean([action is None for action in actions])),
            "discounted_return": float(discounted(rewards, gamma))}


def run_benchmark(policy, seeds, split="train", world=HOMEOSTATIC_WORLD, on_episode=None):
    """Return one result per episode, in seed order, so two policies can be compared seed by seed."""
    results = []
    for seed in seeds:
        results.append(run_episode(policy, seed, split, world))
        if on_episode:
            on_episode(results[-1])
    return results


def summarize(results):
    summary = {}
    for name in METRICS:
        values = [result[name] for result in results if result[name] is not None]
        summary[name] = float(np.mean(values)) if values else None
    counts = {}
    for result in results:
        for action in result["actions"]:
            counts[str(action)] = counts.get(str(action), 0) + 1
    summary["actions"] = dict(sorted(counts.items(), key=lambda item: -item[1]))
    return summary


def paired_difference(a, b, metric, draws=10000, seed=0):
    """Mean of a minus b, with a 95% bootstrap interval over seeds. Pairing removes the luck of which lives were drawn."""
    pairs = [(x[metric], y[metric]) for x, y in zip(a, b, strict=True) if x[metric] is not None and y[metric] is not None]
    differences = np.array([x - y for x, y in pairs])
    rng = np.random.default_rng(seed)
    means = differences[rng.integers(len(differences), size=(draws, len(differences)))].mean(axis=1)
    return {"difference": float(differences.mean()), "low": float(np.quantile(means, 0.025)), "high": float(np.quantile(means, 0.975))}


def constant_policy(action):
    return lambda state: action


def random_policy(rng_seed=0, world=HOMEOSTATIC_WORLD):
    actions = list(world["actions"])
    rng = np.random.default_rng(rng_seed)
    return lambda state: actions[rng.integers(len(actions))]


def planner_policy(depth=1, world=HOMEOSTATIC_WORLD, gamma=HOMEOSTATIC_TRAIN["gamma"]):
    """Search action sequences using the true effects, which no model is told. Depth 1 is greedy; deeper is the ceiling."""
    actions = list(world["actions"])
    now = np.array([world["actions"][action] for action in actions], dtype=float) + np.array(world["drift"])
    later = np.array([world["later"].get(action, [0] * now.shape[1]) for action in actions], dtype=float)
    plans = np.array(list(itertools.product(range(len(actions)), repeat=depth)))
    # By each planned turn: every immediate effect so far, plus delayed effects of all but the latest action.
    moved = np.cumsum(now[plans], axis=1) + np.cumsum(np.concatenate(
        [np.zeros((len(plans), 1, now.shape[1])), later[plans[:, :-1]]], axis=1), axis=1)
    weights = gamma ** np.arange(depth)

    def policy(state):
        values = np.array(state.values) + np.array(state.pending) + moved
        off = np.maximum(np.array(state.low) - values, 0) + np.maximum(values - np.array(state.high), 0)
        drives = np.sqrt((off ** 2).sum(axis=2))
        drives = np.where((values <= world["bounds"][0]).any(axis=2), world["death_drive"], drives)
        # Lower drive on every turn of the plan is better, which is the same order the discounted reward gives.
        return actions[plans[(drives * weights).sum(axis=1).argmin(), 0]]

    return policy
