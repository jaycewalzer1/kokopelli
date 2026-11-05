"""The training layer, on a tiny random model with the real tokenizer. It takes seconds and loads no real weights."""
import itertools
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import mlx.core as mx
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten
from mlx_vlm.generate import generate_step
from mlx_vlm.models.qwen3_vl import Model, ModelConfig
from mlx_vlm.trainer.api import Trainer
from mlx_vlm.trainer.peft.utils import apply_lora_layers, get_peft_model
from mlx_vlm.trainer.vlm.grpo.loss import completion_logps
from mlx_vlm.utils import load_processor

from homeostatic.benchmark import planner_policy, run_episode
from homeostatic.grpo import Actor, branch_return, make_homeostatic_task, training_args
from homeostatic.world import homeostatic_reward, start
from settings import HOMEOSTATIC_TRAIN, HOMEOSTATIC_WORLD as WORLD, LLM_MODEL_WEIGHTS


def tiny_model():
    config = json.loads((LLM_MODEL_WEIGHTS / "config.json").read_text())
    config["skip_vision"] = True
    config["text_config"] |= {"hidden_size": 32, "num_hidden_layers": 2, "intermediate_size": 64, "num_attention_heads": 2,
                              "num_key_value_heads": 2, "head_dim": 16, "max_position_embeddings": 2048}
    model = Model(ModelConfig.from_dict(config))
    mx.eval(model.parameters())
    return model


def setup(group_size=4, **overrides):
    temp = tempfile.TemporaryDirectory()
    mx.random.seed(0)
    model = get_peft_model(tiny_model(), rank=2, alpha=4, dropout=0.0, verbose=False)
    processor = load_processor(LLM_MODEL_WEIGHTS)
    args = training_args(Path(temp.name) / "adapters.safetensors", group_size=group_size, **overrides)
    return temp, model, processor, args, Actor(model, processor, args)


class ActorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp, cls.model, cls.processor, cls.args, cls.actor = setup()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_prompt_carries_the_system_message_and_the_state(self):
        text = self.actor.tokenizer.decode(self.actor.row(start(1))["inputs"]["input_ids"].tolist())
        self.assertIn("Keep every variable inside", text)
        self.assertIn("security", text)
        self.assertTrue(text.rstrip().endswith("assistant"))

    def test_temperature_zero_replies_are_repeatable(self):
        self.assertEqual(self.actor.reply(start(1), temperature=0.0), self.actor.reply(start(1), temperature=0.0))

    def test_scoring_gives_the_same_probabilities_generation_used(self):
        # The loss must score each reply under the distribution that produced it, or the update points the wrong way.
        # Generation steps through a cache and scoring does one full pass, so this is where they could quietly disagree.
        self.model.eval()
        forced = [1234, 77, 900, 151645]
        for seed in (1, 2):
            row = self.actor.row(start(seed))
            prompt = row["inputs"]["input_ids"]
            tokens = iter(forced + [0])  # generation samples one token past the last one it yields
            sampler = lambda logits: mx.array([next(tokens)])
            stream = generate_step(prompt[None, :], self.model, None, mx.ones_like(prompt)[None, :], max_tokens=len(forced), sampler=sampler)
            generated = []
            for (token, logprobs), expected in zip(stream, forced):
                self.assertEqual(int(token), expected)
                generated.append(float(logprobs.reshape(-1)[expected]))
            stream.close()
            ids = mx.concatenate([prompt, mx.array(forced, dtype=mx.int32)])[None, :]
            scored = completion_logps(self.model, dict(row["inputs"], input_ids=ids, attention_mask=mx.ones_like(ids)), prompt.size - 1)
            self.assertTrue(np.allclose(generated, np.array(scored[0]), atol=1e-3), f"{generated} vs {np.array(scored[0])}")
        self.model.train()


class RewardTest(unittest.TestCase):
    def test_a_group_shares_one_state_and_scores_only_the_action(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        state = start(4)
        score = lambda reply: branch_return(actor, state, reply, homeostatic_reward, 0.9, 1, 5.0)
        self.assertEqual(score("rest"), score(" Rest."))
        self.assertNotEqual(score("rest"), score("work"))
        self.assertEqual(score("reward me"), score("idle") - 5.0)

    def test_lookahead_keeps_playing_from_the_branch(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        one = branch_return(actor, start(4), "risk", homeostatic_reward, 0.9, 1, 0.0)
        mx.random.seed(1)
        three = branch_return(actor, start(4), "risk", homeostatic_reward, 0.9, 3, 0.0)
        self.assertNotEqual(one, three)


class TrainingTest(unittest.TestCase):
    def train(self, reward="homeostatic", iters=2):
        temp, model, processor, args, actor = setup(iters=iters)
        self.addCleanup(temp.cleanup)
        settings = HOMEOSTATIC_TRAIN | {"states_per_update": 1, "lookahead": 2}
        task = make_homeostatic_task(actor, processor, args, reward, settings)
        before = {name: np.array(value) for name, value in tree_flatten(model.trainable_parameters())}
        trainer = Trainer(model, args, task=task, train_dataset=list(range(5)), optimizer=optim.Adam(learning_rate=1e-3))
        trainer.train()
        return model, processor, args, before, trainer

    def test_identical_rewards_teach_nothing(self):
        # A random model's replies are all invalid, so a group ties. This is the failure to watch for in real runs.
        model, processor, args, before, trainer = self.train()
        self.assertEqual(trainer.log_history[-1]["train_grouped_reward_std"], 0)
        for name, value in tree_flatten(model.trainable_parameters()):
            self.assertTrue(np.array_equal(before[name], np.array(value)), name)

    def test_a_group_with_different_rewards_moves_only_the_adapter(self):
        # A random model never names an action, so this stands in replies that do differ.
        actions = itertools.cycle(WORLD["actions"])
        with patch("homeostatic.grpo.parse_action", side_effect=lambda text, world=None: next(actions)):
            model, processor, args, before, trainer = self.train()
        self.assertGreater(trainer.log_history[-1]["train_grouped_reward_std"], 0)
        after = dict(tree_flatten(model.trainable_parameters()))
        self.assertTrue(after)
        self.assertTrue(all("lora" in name for name in after))
        self.assertTrue(any(not np.array_equal(before[name], np.array(value)) for name, value in after.items()))
        self.assertTrue(all(np.isfinite(np.array(value)).all() for value in after.values()))

    def test_an_update_makes_better_replies_likelier_and_worse_ones_less_likely(self):
        # The sign of the whole method. If this flips, training would steadily teach the opposite of the reward.
        temp, model, processor, args, actor = setup(iters=5)
        self.addCleanup(temp.cleanup)
        row = actor.row(start(1))
        prompt = row["inputs"]["input_ids"]

        def sample(token, advantage):
            ids = mx.concatenate([prompt, mx.array([token, 151645], dtype=mx.int32)])[None, :]
            return {"batch": dict(row["inputs"], input_ids=ids, attention_mask=mx.ones_like(ids)), "start": prompt.size - 1,
                    "advantage": mx.array([advantage], dtype=mx.float32)}

        good, bad = sample(1234, 1.0), sample(77, -1.0)
        log_probability = lambda part: float(completion_logps(model, part["batch"], part["start"]).sum())
        model.eval()
        good_before, bad_before = log_probability(good), log_probability(bad)
        task = replace(make_homeostatic_task(actor, processor, args), batches=lambda *a, **k: iter(
            [{"samples": [good, bad], "reward_metrics": {"reward_mean": mx.array(0.0)}}] * 5))
        Trainer(model, args, task=task, train_dataset=[0], optimizer=optim.Adam(learning_rate=1e-3)).train()
        model.eval()
        self.assertGreater(log_probability(good), good_before)
        self.assertLess(log_probability(bad), bad_before)

    def test_the_metrics_report_replies_and_rewards(self):
        _, _, _, _, trainer = self.train(iters=1)
        for name in ("train_reward_mean", "train_invalid_rate", "train_distinct_actions"):
            self.assertIn(name, trainer.log_history[-1])

    def test_shuffling_keeps_each_groups_scores_but_breaks_their_assignment(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        settings = HOMEOSTATIC_TRAIN | {"states_per_update": 1, "lookahead": 1}
        captured = []
        with patch("homeostatic.grpo.prepare_rollout", side_effect=lambda m, t, rows, a, funcs, w: captured.append(funcs[0]) or
                   {"samples": [], "reward_metrics": {}}), patch("homeostatic.grpo.reply_metrics", return_value={}):
            task = make_homeostatic_task(actor, processor, args, "shuffled", settings)
            next(task.batches([0], train=True))
        replies = ["rest", "work", "risk", "save"]
        row = {"state": start(1)}
        honest = [branch_return(actor, row["state"], reply, homeostatic_reward, settings["gamma"], 1, 5.0) for reply in replies]
        shuffled = [captured[0](completions=replies, metadata=[row] * 4) for _ in range(5)]
        for scores in shuffled:
            self.assertEqual(sorted(scores), sorted(honest))
        self.assertTrue(any(scores != honest for scores in shuffled))

    def test_replies_naming_the_same_action_get_exactly_the_same_score(self):
        # Exact ties are what make a group's advantage zero when nothing distinguishes its replies.
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        captured = []
        with patch("homeostatic.grpo.prepare_rollout", side_effect=lambda m, t, rows, a, funcs, w: captured.append(funcs[0]) or
                   {"samples": [], "reward_metrics": {}}), patch("homeostatic.grpo.reply_metrics", return_value={}):
            next(make_homeostatic_task(actor, processor, args).batches([0], train=True))
        calls = patch("homeostatic.grpo.branch_return", side_effect=lambda *a, **k: float(np.random.random()))
        with calls as mocked:
            scores = captured[0](completions=["rest", " Rest.", "work", "rest"], metadata=[{"state": start(1)}] * 4)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(scores[0], scores[1])
        self.assertEqual(scores[0], scores[3])
        self.assertNotEqual(scores[0], scores[2])

    def test_each_scored_group_is_reported_with_its_state(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        reported, captured = [], []
        with patch("homeostatic.grpo.prepare_rollout", side_effect=lambda m, t, rows, a, funcs, w: captured.append(funcs[0]) or
                   {"samples": [], "reward_metrics": {}}), patch("homeostatic.grpo.reply_metrics", return_value={}):
            task = make_homeostatic_task(actor, processor, args, on_group=lambda *group: reported.append(group))
            next(task.batches([0], train=True))
        states = [start(1)] * 4 + [start(2)] * 4
        scores = captured[0](completions=["rest", "work", "rest", "save"] * 2, metadata=[{"state": state} for state in states])
        self.assertEqual([group[0] for group in reported], [start(1), start(2)])
        self.assertEqual(reported[1][1], ["rest", "work", "rest", "save"])
        self.assertEqual(reported[0][2] + reported[1][2], scores)

    def test_the_maximize_control_runs(self):
        self.train("maximize", iters=1)

    def test_a_saved_adapter_restores_the_same_replies(self):
        with patch("homeostatic.grpo.branch_return", side_effect=lambda *a, **k: float(np.random.random())):
            model, processor, args, _, trainer = self.train(iters=1)
        states = [start(seed) for seed in range(3)]
        trained = [Actor(model, processor, args).reply(state, temperature=0.0) for state in states]
        mx.random.seed(0)
        restored = apply_lora_layers(tiny_model(), args.adapter_file)
        saved = dict(tree_flatten(model.trainable_parameters()))
        loaded = dict(tree_flatten(restored.trainable_parameters()))
        self.assertEqual(saved.keys(), loaded.keys())
        for name in saved:
            self.assertTrue(np.array_equal(np.array(saved[name]), np.array(loaded[name])), name)
        self.assertEqual(trained, [Actor(restored, processor, args).reply(state, temperature=0.0) for state in states])


class BenchmarkTest(unittest.TestCase):
    def test_a_model_can_be_scored_like_any_other_policy(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        result = run_episode(actor.policy(), 200000)
        self.assertEqual(result["seed"], 200000)
        self.assertGreater(len(result["actions"]), 0)

    def test_the_planner_beats_the_greedy_policy_because_effects_are_delayed(self):
        seeds = range(200000, 200100)
        greedy = np.mean([run_episode(planner_policy(1), seed)["mean_drive"] for seed in seeds])
        planner = np.mean([run_episode(planner_policy(3), seed)["mean_drive"] for seed in seeds])
        self.assertLess(planner, greedy - 1)


if __name__ == "__main__":
    unittest.main()
