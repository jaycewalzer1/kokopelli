"""Homeostatic post-training on top of mlx-vlm's trainer. The training loop is mlx-vlm's; the groups and the loss aren't.

Its own GRPO samples replies and compares them, which only teaches while they disagree. Learning one habit is much
easier than learning to respond to the state, so the model settles on a habit, replies stop disagreeing and the signal
ends. Here a simulator can try every action from a state instead, so a group always holds all of them. Each is scored
by branching from that state with the same noise, so comparing them measures the choice and not the luck.

The first token of a reply is then trained toward softmax(score / temperature). Those weights are never negative, so
nothing is pushed toward a probability of zero, and training has a point it settles at. Every action starts with its own
token, so one forward pass per state covers all of them.

The simulator also picks the states and plays out the turns after each action, with no model calls. That's what makes
updates cheap enough to learn from, and its cost: the model is taught from what the reward says about each state, and
never sees where its own choices lead.
"""
from dataclasses import asdict, replace
from types import SimpleNamespace

import mlx.core as mx
import mlx.nn as nn
import numpy as np
from mlx.utils import tree_map
from mlx_vlm.trainer.vlm.grpo import GRPOTrainingArgs, GRPOVisionDataset
from mlx_vlm.trainer.vlm.grpo.trainer import generate_grpo, make_task
from mlx_vlm.trainer.vlm.sft.runtime import forward_vlm_logits

from experiments.homeostatic.world import REWARDS, discounted, done, start, step, system_prompt, user_prompt
from kokopelli.settings import HOMEOSTATIC_TRAIN, HOMEOSTATIC_WORLD

# Reward kinds to train with. Shuffled is the null control: same scores, assigned to the wrong actions.
REWARD_KINDS = [*REWARDS, "shuffled"]


def training_args(adapter_file, settings=HOMEOSTATIC_TRAIN, **overrides):
    settings = settings | overrides
    return GRPOTrainingArgs(
        iters=settings["iters"], steps_per_report=settings["steps_per_report"], adapter_file=str(adapter_file),
        steps_per_eval=None, steps_per_save=10 ** 9, group_size=len(HOMEOSTATIC_WORLD["actions"]),
        max_completion_length=settings["max_completion_length"], temperature=0.0,
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


def greedy_action(state, reward_fn, world=HOMEOSTATIC_WORLD):
    return max(world["actions"], key=lambda action: reward_fn(state, step(state, action, world), world))


def branch_return(state, action, reward_fn, gamma, lookahead, world=HOMEOSTATIC_WORLD):
    """The discounted reward of this action here, then the best immediate action for the rest of the lookahead.

    Later turns are greedy so that an action isn't blamed for a random choice after it.
    """
    rewards = []
    for _ in range(lookahead):
        after = step(state, action, world)
        rewards.append(reward_fn(state, after, world))
        state = after
        if done(state, world):
            break
        action = greedy_action(state, reward_fn, world)
    return discounted(rewards, gamma)


def targets(scores, temperature):
    """How much to train toward each action. Equal scores give equal weight, which is why ties can't cause a collapse."""
    scores = np.asarray(scores, dtype=float)
    weights = np.exp((scores - scores.max()) / temperature)
    return weights / weights.sum()


def score_actions(state, reward_fn, settings, world=HOMEOSTATIC_WORLD):
    return [branch_return(state, action, reward_fn, settings["gamma"], settings["lookahead"], world) for action in world["actions"]]


def visit(seed, rng, reward_fn, settings, world=HOMEOSTATIC_WORLD):
    """Live part of a life, mixing good and random choices so that both healthy and badly off states come up."""
    state = start(int(seed), "train", world)
    actions = list(world["actions"])
    for _ in range(rng.integers(world["horizon"])):
        explore = rng.random() < settings["visit_random"]
        after = step(state, actions[rng.integers(len(actions))] if explore else greedy_action(state, reward_fn, world), world)
        if done(after, world):
            break
        state = after
    return state


def state_loss(policy, sample):
    """Cross-entropy from the target weights to the first token, plus finishing one sampled action cleanly."""
    ids, begin = sample["batch"]["input_ids"], sample["start"]
    logits = forward_vlm_logits(policy, ids[:, :-1], sample["batch"]["attention_mask"][:, :-1], sample["batch"])
    logps = nn.log_softmax(logits[0, begin:], axis=-1)
    loss = -(sample["weights"] * logps[0][sample["first_tokens"]]).sum()
    after = ids[0, begin + 2:]
    loss = loss - mx.take_along_axis(logps[1:], after[:, None], axis=-1).mean()
    return loss, mx.stop_gradient(logps[0])


def make_homeostatic_task(actor, processor, args, reward="homeostatic", settings=HOMEOSTATIC_TRAIN, rng_seed=0, on_group=None):
    """Return mlx-vlm's GRPO task with its batches and loss replaced. on_group is told each group as it's trained on."""
    world = actor.world
    rng = np.random.default_rng(rng_seed)
    reward_fn = REWARDS["homeostatic" if reward == "shuffled" else reward]
    actions = list(world["actions"])
    end = actor.tokenizer.eos_token_id
    encoded = {action: actor.tokenizer.encode(action, add_special_tokens=False) + [end] for action in actions}
    first_tokens = mx.array([encoded[action][0] for action in actions])
    if len({encoded[action][0] for action in actions}) < len(actions):
        raise ValueError("Every action needs its own first token.")

    def sample_for(state, trained_scores):
        row = actor.row(state)
        prompt = row["inputs"]["input_ids"]
        weights = targets(trained_scores, settings["target_temperature"])
        finish = actions[rng.choice(len(actions), p=weights)]
        ids = mx.concatenate([prompt, mx.array(encoded[finish], dtype=mx.int32)])[None, :]
        return {"batch": dict(row["inputs"], input_ids=ids, attention_mask=mx.ones_like(ids)), "start": prompt.size - 1,
                "weights": mx.array(weights, dtype=mx.float32), "first_tokens": first_tokens}

    def batches(dataset, train=False, seed=None):
        while True:
            samples = []
            for _ in range(settings["states_per_update"]):
                state = visit(rng.choice(dataset), rng, reward_fn, settings, world)
                scores = score_actions(state, reward_fn, settings, world)
                trained_scores = rng.permutation(scores).tolist() if reward == "shuffled" else scores
                samples.append(sample_for(state, trained_scores) | {"state": state, "scores": scores})
            yield {"samples": samples}
            if not train:
                return

    def report(sample, first):
        """How the model's likeliest first token did here. Any token that starts no action counts as invalid."""
        token = int(mx.argmax(first))
        choice = next((action for action in actions if encoded[action][0] == token), None)
        if on_group:
            on_group(sample["state"], actions, sample["scores"], choice)
        return choice, sample["scores"]

    def value_and_grad_factory(policy, compiled):
        compute = nn.value_and_grad(policy, state_loss)

        def update(policy, batch):
            training = policy.training
            total, gradients, chosen, all_scores = mx.array(0.0), None, [], []
            share = 1 / len(batch["samples"])
            try:
                policy.train()
                for sample in batch["samples"]:
                    (loss, first), grad = compute(policy, sample)
                    grad = tree_map(lambda g: g * share, grad)
                    gradients = grad if gradients is None else tree_map(lambda a, b: a + b, gradients, grad)
                    total = total + loss * share
                    # Release this state's graph before building the next one.
                    mx.eval(total, gradients, first)
                    choice, scores = report(sample, first)
                    chosen.append(choice)
                    all_scores.append(scores)
            finally:
                policy.train(training)
            return (total, choice_metrics(all_scores, chosen, actions)), gradients

        return update

    return replace(make_task(actor.model, args, processor, reward_funcs=[lambda **_: []]), batches=batches, prepare_dataset=None,
                   value_and_grad_factory=value_and_grad_factory)


def choice_metrics(all_scores, chosen, actions):
    """How the model's own likeliest choices did on these states. Regret is how much better the best action was."""
    # An invalid reply plays out as idling, so that's the score it earned.
    values = [scores[actions.index(choice or "idle")] for scores, choice in zip(all_scores, chosen, strict=False)]
    regrets = [max(scores) - value for scores, value in zip(all_scores, values, strict=False)]
    named = [choice for choice in chosen if choice]
    return {"reward_mean": mx.array(float(np.mean(values))), "regret": mx.array(float(np.mean(regrets))),
            "invalid_rate": mx.array(float(np.mean([choice is None for choice in chosen]))),
            "distinct_actions": mx.array(float(len(set(named))))}
