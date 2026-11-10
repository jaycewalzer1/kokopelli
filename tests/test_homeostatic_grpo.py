"""The training layer, on a tiny random model with the real tokenizer. It takes seconds and loads no real weights."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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

from experiments.homeostatic.benchmark import planner_policy, run_episode
from experiments.homeostatic.grpo import Actor, branch_return, make_homeostatic_task, score_actions, targets, training_args, visit
from experiments.homeostatic.world import done, homeostatic_reward, start, step
from kokopelli.settings import HOMEOSTATIC_TRAIN, HOMEOSTATIC_WORLD as WORLD, LLM_MODEL_WEIGHTS


def tiny_model():
    config = json.loads((LLM_MODEL_WEIGHTS / "config.json").read_text())
    config["skip_vision"] = True
    config["text_config"] |= {"hidden_size": 32, "num_hidden_layers": 2, "intermediate_size": 64, "num_attention_heads": 2,
                              "num_key_value_heads": 2, "head_dim": 16, "max_position_embeddings": 2048}
    model = Model(ModelConfig.from_dict(config))
    mx.eval(model.parameters())
    return model


def setup(**overrides):
    temp = tempfile.TemporaryDirectory()
    mx.random.seed(0)
    model = get_peft_model(tiny_model(), rank=2, alpha=4, dropout=0.0, verbose=False)
    processor = load_processor(LLM_MODEL_WEIGHTS)
    args = training_args(Path(temp.name) / "adapters.safetensors", **overrides)
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


class ScoreTest(unittest.TestCase):
    def test_every_action_is_scored_and_lookahead_keeps_playing(self):
        one = score_actions(start(4), homeostatic_reward, HOMEOSTATIC_TRAIN | {"lookahead": 1})
        self.assertEqual(len(one), len(WORLD["actions"]))
        self.assertGreater(len(set(one)), 1)
        self.assertEqual(one, [homeostatic_reward(start(4), step(start(4), action)) for action in WORLD["actions"]])
        three = score_actions(start(4), homeostatic_reward, HOMEOSTATIC_TRAIN | {"lookahead": 3})
        self.assertNotEqual(one, three)

    def test_a_delayed_cost_only_shows_with_lookahead(self):
        state = replace(start(4), values=(49, 50, 30, 50), low=(40, 40, 40, 40), high=(60, 60, 60, 60))
        gamma = HOMEOSTATIC_TRAIN["gamma"]
        # With only idling to follow it, nothing can make up for the cost when it lands.
        world = WORLD | {"actions": {name: WORLD["actions"][name] for name in ("risk", "idle")}}
        now = branch_return(state, "risk", homeostatic_reward, gamma, 1, world)
        later = branch_return(state, "risk", homeostatic_reward, gamma, 2, world)
        self.assertGreater(now, 0)
        self.assertLess(later, now)

    def test_visits_reach_living_states_at_many_turns(self):
        rng = np.random.default_rng(0)
        states = [visit(seed, rng, homeostatic_reward, HOMEOSTATIC_TRAIN) for seed in range(40)]
        self.assertGreater(len({state.turn for state in states}), 3)
        self.assertFalse(any(done(state) for state in states))

    def test_targets_favor_better_scores_and_never_go_negative(self):
        weights = targets([1.0, 3.0, -5.0], 2.0)
        self.assertAlmostEqual(weights.sum(), 1.0)
        self.assertTrue((weights > 0).all())
        self.assertEqual(int(weights.argmax()), 1)
        self.assertGreater(weights[0], weights[2])

    def test_ties_ask_for_every_action_equally(self):
        self.assertTrue(np.allclose(targets([0.0, 0.0, 0.0], 2.0), 1 / 3))

    def test_scores_far_apart_dont_overflow(self):
        self.assertTrue(np.isfinite(targets([-5000.0, 5000.0], 0.01)).all())


class TrainingTest(unittest.TestCase):
    def train(self, reward="homeostatic", iters=2, on_group=None):
        temp, model, processor, args, actor = setup(iters=iters)
        self.addCleanup(temp.cleanup)
        settings = HOMEOSTATIC_TRAIN | {"states_per_update": 1}
        task = make_homeostatic_task(actor, processor, args, reward, settings, on_group=on_group)
        before = {name: np.array(value) for name, value in tree_flatten(model.trainable_parameters())}
        trainer = Trainer(model, args, task=task, train_dataset=list(range(5)), optimizer=optim.Adam(learning_rate=1e-3))
        trainer.train()
        return model, processor, args, before, trainer

    def test_a_random_model_still_learns_because_every_action_is_in_the_group(self):
        # Its replies are all invalid. Sampled groups would tie here and teach nothing.
        model, processor, args, before, trainer = self.train()
        after = dict(tree_flatten(model.trainable_parameters()))
        self.assertEqual(trainer.log_history[-1]["train_invalid_rate"], 1)
        self.assertTrue(after and all("lora" in name for name in after))
        self.assertTrue(any(not np.array_equal(before[name], np.array(value)) for name, value in after.items()))
        self.assertTrue(all(np.isfinite(np.array(value)).all() for value in after.values()))

    def test_repeated_updates_move_first_token_probabilities_toward_the_target(self):
        # The direction of the whole method. A flipped sign would steadily teach the opposite of the reward.
        temp, model, processor, args, actor = setup(iters=40)
        self.addCleanup(temp.cleanup)
        settings = HOMEOSTATIC_TRAIN | {"states_per_update": 1}
        task = make_homeostatic_task(actor, processor, args, settings=settings)
        actions = list(WORLD["actions"])
        tokens = mx.array([actor.tokenizer.encode(action, add_special_tokens=False)[0] for action in actions])
        wanted = np.array([0.7, 0.2] + [0.1 / 7] * 7)
        row = actor.row(start(1))
        prompt = row["inputs"]["input_ids"]
        ids = mx.concatenate([prompt, mx.array([int(tokens[0]), actor.tokenizer.eos_token_id], dtype=mx.int32)])[None, :]
        sample = {"batch": dict(row["inputs"], input_ids=ids, attention_mask=mx.ones_like(ids)), "start": prompt.size - 1,
                  "weights": mx.array(wanted, dtype=mx.float32), "first_tokens": tokens, "state": start(1), "scores": [0.0] * 9}
        task = replace(task, batches=lambda *a, **k: iter([{"samples": [sample]}] * 40))

        def action_chances():
            model.eval()
            logits = model(ids[:, :-1], None, mx.ones_like(ids[:, :-1])).logits[0, prompt.size - 1]
            return np.array(mx.softmax(logits)[tokens])

        before = action_chances()
        Trainer(model, args, task=task, train_dataset=[0], optimizer=optim.Adam(learning_rate=3e-3)).train()
        chances = action_chances()
        self.assertGreater(chances[0], chances[1])
        self.assertGreater(chances[1], chances[2:].max())
        self.assertGreater(chances.sum(), before.sum() * 2)

    def test_an_action_scored_best_is_the_one_the_model_finishes_cleanly(self):
        # Only the first token gets the soft target, so the rest of the word and the stop come from one sampled action.
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        batch = next(make_homeostatic_task(actor, processor, args, settings=HOMEOSTATIC_TRAIN | {"states_per_update": 1}).batches([0], train=True))
        sample = batch["samples"][0]
        finish = sample["batch"]["input_ids"][0, sample["start"] + 1:].tolist()
        self.assertEqual(finish[-1], actor.tokenizer.eos_token_id)
        self.assertIn(actor.tokenizer.decode(finish[:-1]), WORLD["actions"])

    def test_the_metrics_report_the_models_own_choices(self):
        _, _, _, _, trainer = self.train(iters=1)
        for name in ("train_reward_mean", "train_regret", "train_invalid_rate", "train_distinct_actions"):
            self.assertIn(name, trainer.log_history[-1])
        self.assertGreaterEqual(trainer.log_history[-1]["train_regret"], 0)

    def test_each_group_is_reported_with_its_real_scores_under_every_reward(self):
        for reward in ("homeostatic", "shuffled", "maximize"):
            reported = []
            self.train(reward, iters=1, on_group=lambda *group: reported.append(group))
            state, actions, scores, chosen = reported[0]
            self.assertEqual(actions, list(WORLD["actions"]))
            self.assertEqual(len(scores), len(actions))
            self.assertIsNone(chosen)

    def test_shuffling_changes_what_is_trained_toward_but_keeps_the_scores(self):
        temp, model, processor, args, actor = setup()
        self.addCleanup(temp.cleanup)
        settings = HOMEOSTATIC_TRAIN | {"states_per_update": 1, "lookahead": 1}
        honest = next(make_homeostatic_task(actor, processor, args, "homeostatic", settings).batches([0], train=True))
        shuffled = next(make_homeostatic_task(actor, processor, args, "shuffled", settings).batches([0], train=True))
        weights = lambda batch: np.array(batch["samples"][0]["weights"]).tolist()
        self.assertTrue(np.allclose(sorted(weights(honest)), sorted(weights(shuffled))))
        self.assertFalse(np.allclose(weights(honest), weights(shuffled)))

    def test_a_saved_adapter_restores_the_same_replies(self):
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
