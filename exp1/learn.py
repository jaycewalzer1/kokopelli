"""The learning rule, separate from any model: a running baseline per decision, and a sleep update at the end of each day.

Awake, each decision is one lived sample. Its advantage is reward minus that decision's running baseline, and the
baseline then moves a fifth of the way toward the reward. Forced exploration choices move the baseline but are never
trained on, since the policy didn't pick them.

Asleep, the policy takes 1-4 gradient steps on
    loss = mean_i[ -w_i * A_i * log pi_now(a_i | s_i) ]  +  beta * mean_i[ KL(pi_now(.|s_i) || pi_base(.|s_i)) ]
over today's free decisions plus those of the last few days (replay). w_i = pi_now(a_i) / pi_then(a_i), clipped to
[0.8, 1.2] and held constant: a correction for samples drawn by an older policy, clipped so one stale sample can't swing the
update. Today's samples start at w = 1. The KL is exact, over the offered options, against the untrained model's
probabilities saved at decision time (the base model never changes, so they stay valid).

A policy here is anything with:
    model                          an mlx nn.Module whose trainable parameters are the ones to update
    log_probs(row) -> mx.array     log pi over row["shown"], differentiable, for a trajectory row
"""
import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten, tree_map, tree_unflatten

BASELINE_WEIGHT = 0.2
DEFAULTS = {"lr": 5e-5, "beta": 0.05, "steps": 2, "replay_days": 5, "clip": (0.8, 1.2), "max_grad_norm": 1.0}


class Baseline:
    """A running mean of reward per decision type."""

    def __init__(self, decisions, values=None):
        self.values = dict(values) if values else {decision: 0.0 for decision in decisions}

    def advantage(self, decision, reward):
        """(baseline before this reward, advantage). Then the baseline moves toward the reward."""
        before = self.values[decision]
        self.values[decision] = before + BASELINE_WEIGHT * (reward - before)
        return before, reward - before


def replay_rows(trajectory, day, replay_days):
    """Free, trainable decisions from today and the replay_days before it."""
    return [row for row in trajectory if not row["forced"] and row["day"] is not None and day - replay_days <= row["day"] <= day]


def _kl(logp_now, logp_base):
    return (mx.exp(logp_now) * (logp_now - logp_base)).sum()


class Sleeper:
    """Owns the optimizer, so its moment estimates carry from night to night."""

    def __init__(self, policy, settings=None):
        self.policy = policy
        self.settings = DEFAULTS | (settings or {})
        self.optimizer = optim.Adam(learning_rate=self.settings["lr"])
        self.optimizer.init(policy.model.trainable_parameters())
        self.steps_taken = 0

    def _sample_loss(self, model, row, scale):
        logp = self.policy.log_probs(row)
        chosen = logp[row["shown"].index(row["choice"])]
        low, high = self.settings["clip"]
        weight = mx.stop_gradient(mx.clip(mx.exp(chosen - float(np.log(row["pi"][row["choice"]]))), low, high))
        pg = -weight * row["advantage"] * chosen
        kl = _kl(logp, mx.array(row["base_logp"], dtype=mx.float32))
        return (pg + self.settings["beta"] * kl) * scale, (pg * scale, kl * scale, weight)

    def sleep(self, rows):
        """Gradient steps on these rows. Returns what the panel's training view shows for the night."""
        if not rows:
            return {"steps": 0, "samples": 0}
        model, settings = self.policy.model, self.settings
        grad_fn = nn.value_and_grad(model, self._sample_loss)
        scale = 1.0 / len(rows)
        per_step = []
        for _ in range(settings["steps"]):
            total_pg, total_kl, grads, weights = 0.0, 0.0, None, []
            for row in rows:
                (_, (pg, kl, weight)), grad = grad_fn(model, row, scale)
                grads = grad if grads is None else tree_map(lambda a, b: a + b, grads, grad)
                mx.eval(grads, pg, kl, weight)   # release this sample's graph before the next
                total_pg += float(pg)
                total_kl += float(kl)
                weights.append(float(weight))
            grads, norm = optim.clip_grad_norm(grads, settings["max_grad_norm"])
            self.optimizer.update(model, grads)
            mx.eval(model.trainable_parameters(), self.optimizer.state)
            self.steps_taken += 1
            per_step.append({"loss_pg": total_pg, "kl": total_kl, "loss_kl": settings["beta"] * total_kl,
                             "grad_norm": float(norm), "weight_mean": float(np.mean(weights)),
                             "weights_clipped": int(sum(not settings["clip"][0] < w < settings["clip"][1] for w in weights))})
        first, last = per_step[0], per_step[-1]
        return {"steps": len(per_step), "samples": len(rows), "lr": settings["lr"], "beta": settings["beta"],
                "loss_pg": first["loss_pg"], "loss_kl": first["loss_kl"], "kl": first["kl"], "grad_norm": first["grad_norm"],
                "kl_after_last_step_start": last["kl"], "per_step": per_step, "lora_step": self.steps_taken}

    # ----- checkpoints -----
    def optimizer_state(self):
        flat = dict(tree_flatten(self.optimizer.state))
        return {key: value for key, value in flat.items() if isinstance(value, mx.array)}

    def load_optimizer_state(self, arrays, steps_taken):
        self.optimizer.state = tree_unflatten(list(arrays.items()))
        self.steps_taken = steps_taken
