"""Homeostatic GRPO on top of mlx-vlm's trainer. The loss, sampler and training loop are all mlx-vlm's.

Its own GRPO scores one reply to a fixed prompt. A life is several turns, so two pieces change: batches() draws the
prompts from states the current model actually reaches, and the reward callback scores a reply by branching the
simulator from that state and playing on for a few turns. Every reply in a group starts from the same state and sees
the same noise, so comparing them measures the choice and not the luck.
"""
from dataclasses import asdict, replace
from types import SimpleNamespace

import mlx.core as mx
import numpy as np
from mlx_vlm.trainer.vlm.grpo import GRPOTrainingArgs, GRPOVisionDataset
from mlx_vlm.trainer.vlm.grpo.trainer import generate_grpo, make_task, prepare_rollout

from homeostatic.world import REWARDS, discounted, done, parse_action, start, step, system_prompt, user_prompt
from settings import HOMEOSTATIC_TRAIN, HOMEOSTATIC_WORLD

# Reward kinds to train with. Shuffled is the null control: same rewards, assigned to the wrong replies.
REWARD_KINDS = [*REWARDS, "shuffled"]


def training_args(adapter_file, settings=HOMEOSTATIC_TRAIN, **overrides):
    """Sampling isn't truncated, so any action can still be tried however unlikely the model finds it."""
    settings = settings | overrides
    return GRPOTrainingArgs(
        iters=settings["iters"], steps_per_report=settings["steps_per_report"], adapter_file=str(adapter_file),
        steps_per_eval=None, steps_per_save=10 ** 9, group_size=settings["group_size"],
        max_completion_length=settings["max_completion_length"], temperature=settings["temperature"],
        top_p=1.0, top_k=0, beta=0.0, clear_cache_threshold=2 * 10 ** 9)


class Actor:
    """Turns states into prompts and prompts into replies, for one model."""

    def __init__(self, model, processor, args, world=HOMEOSTATIC_WORLD, reveal_effects=False):
        self.model, self.args, self.world = model, args, world
        self.tokenizer = getattr(processor, "tokenizer", processor)
        self.system = system_prompt(world, reveal_effects)
        config = SimpleNamespace(**asdict(args))
        self.dataset = GRPOVisionDataset([], model.config, processor, config=config)

    def row(self, state):
        return self.dataset.process({"system": self.system, "prompt": user_prompt(state, self.world), "state": state})

    def reply(self, state, temperature=None):
        """One reply to a state. Temperature 0 always takes the likeliest token."""
        temperature = self.args.temperature if temperature is None else temperature
        args = replace(self.args, group_size=1, temperature=temperature)
        return generate_grpo(self.model, self.tokenizer, [self.row(state)], args)[1][0]

    def policy(self, temperature=0.0):
        return lambda state: self.reply(state, temperature)


def branch_return(actor, state, first_reply, reward_fn, gamma, lookahead, invalid_penalty):
    """The discounted reward of giving this reply here, then taking the model's likeliest action for the rest of the lookahead.

    Later turns are greedy so that a good reply isn't blamed for a random later one.
    """
    world = actor.world
    rewards, reply = [], first_reply
    for _ in range(lookahead):
        action = parse_action(reply, world)
        after = step(state, action, world)
        rewards.append(reward_fn(state, after, world) - (invalid_penalty if action is None else 0.0))
        state = after
        if done(state, world):
            break
        reply = actor.reply(state, temperature=0.0)
    return discounted(rewards, gamma)


def make_homeostatic_task(actor, processor, args, reward="homeostatic", settings=HOMEOSTATIC_TRAIN, rng_seed=0, on_group=None):
    """Return mlx-vlm's GRPO task with its prompts and rewards replaced. on_group is told each group as it's scored."""
    world, group_size = actor.world, args.group_size
    rng = np.random.default_rng(rng_seed)
    reward_fn = REWARDS["homeostatic" if reward == "shuffled" else reward]

    def score(completions, metadata, **_):
        # The same action from the same state plays out identically, so each is only simulated once.
        known = {}

        def branch(reply, row):
            key = (row["state"], parse_action(reply, world))
            if key not in known:
                known[key] = branch_return(actor, row["state"], reply, reward_fn, settings["gamma"], settings["lookahead"],
                                           settings["invalid_penalty"])
            return known[key]

        scores = [branch(reply, row) for reply, row in zip(completions, metadata)]
        if reward == "shuffled":
            for begin in range(0, len(scores), group_size):
                scores[begin:begin + group_size] = rng.permutation(scores[begin:begin + group_size]).tolist()
        if on_group:
            for begin in range(0, len(scores), group_size):
                on_group(metadata[begin]["state"], completions[begin:begin + group_size], scores[begin:begin + group_size])
        return scores

    def visit(seed):
        """Live part of a life as the model would, to reach a state worth training on."""
        state = start(int(seed), "train", world)
        for _ in range(rng.integers(world["horizon"])):
            after = step(state, parse_action(actor.reply(state), world), world)
            if done(after, world):
                break
            state = after
        return state

    def batches(dataset, train=False, seed=None):
        while True:
            rows = [actor.row(visit(rng.choice(dataset))) for _ in range(settings["states_per_update"])]
            rollout = prepare_rollout(actor.model, actor.tokenizer, rows, args, [score], None)
            rollout["reward_metrics"] |= reply_metrics(rollout, actor)
            yield rollout
            if not train:
                return

    return replace(make_task(actor.model, args, processor, reward_funcs=[score]), batches=batches, prepare_dataset=None)


def reply_metrics(rollout, actor):
    """Whether replies are valid, and whether groups disagree at all. A group of identical replies teaches nothing."""
    replies = [actor.tokenizer.decode(sample["batch"]["input_ids"][0, sample["start"] + 1:].tolist(), skip_special_tokens=True)
               for sample in rollout["samples"]]
    actions = [parse_action(reply, actor.world) for reply in replies]
    size = actor.args.group_size
    distinct = [len(set(actions[begin:begin + size])) for begin in range(0, len(actions), size)]
    return {"invalid_rate": mx.array(float(np.mean([action is None for action in actions]))),
            "distinct_actions": mx.array(float(np.mean(distinct)))}
