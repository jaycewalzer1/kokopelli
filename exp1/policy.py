"""Policies the learner can train. Both score the offered options and give log pi over them; neither generates the choice.

QwenPolicy scores the tokens of `{"choice": "<option_id>"` after the observation, for each offered option, and takes a
softmax over those scores. That is the probability the model gives to starting its answer with each option, renormalized
over what's offered, so it's exact and costs one forward pass per option with no parsing. The choice is sampled from it
at temperature 1. A one-sentence reason is generated afterwards, for the logs only; it's never scored or rewarded.

TablePolicy is one logit per option, the tabular check's policy in mlx, so the learner can be tested without a model.
"""
from contextlib import contextmanager

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from life import scenario

CHOICE_PREFIX = '{"choice": "'
REASON_TOKENS = 48
REASON_TEMPERATURE = 0.7
CACHE_LIMIT_BYTES = 2 * 2 ** 30


def continuation(option_id):
    return f'{CHOICE_PREFIX}{option_id}"'


class _Logits(nn.Module):
    def __init__(self, size):
        super().__init__()
        self.logits = mx.zeros((size,))


class TablePolicy:
    """One logit per option. Base probabilities are uniform over what's offered."""

    def __init__(self):
        self.index = {option.id: k for k, option in enumerate(scenario.OPTIONS)}
        self.model = _Logits(len(self.index))

    def log_probs(self, row):
        z = self.model.logits[mx.array([self.index[o] for o in row["shown"]])]
        return z - mx.logsumexp(z)

    def base_log_probs(self, row):
        return np.full(len(row["shown"]), -np.log(len(row["shown"])))

    def reason(self, row, choice):
        return ""


class QwenPolicy:
    """Qwen3-VL with LoRA on the language model's q and v projections."""

    def __init__(self, weights, rank=16, alpha=32, adapter=None):
        from mlx_vlm import load
        from mlx_vlm.trainer.peft.utils import apply_lora_layers, get_peft_model
        self.weights = str(weights)
        mx.set_cache_limit(CACHE_LIMIT_BYTES)   # freed buffers go back to the system instead of piling up across a sleep
        self.model, self.processor = load(self.weights)
        self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        if adapter:
            apply_lora_layers(self.model, adapter)
        else:
            get_peft_model(self.model, linear_layers=["q_proj", "v_proj"], rank=rank, alpha=alpha, dropout=0.0, verbose=False)
        self.lora = [module for _, module in self.model.named_modules() if hasattr(module, "lora_a")]
        if not self.lora:
            raise RuntimeError("no LoRA layers were attached")
        self._cache = {}

    # ----- prompts -----
    def prompt_text(self, row):
        from mlx_vlm.prompt_utils import apply_chat_template
        messages = [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["observation"]}]
        return apply_chat_template(self.processor, self.model.config, messages)

    def _encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False)

    def _batch(self, row):
        """Right-padded ids for prompt + each option's continuation, and where each continuation's tokens are."""
        key = (row["observation"], tuple(row["shown"]))
        if key not in self._cache:
            prompt = self._encode(self.prompt_text(row))
            tails = [self._encode(continuation(o)) for o in row["shown"]]
            length = len(prompt) + max(map(len, tails))
            pad = self.tokenizer.pad_token_id or 0
            ids = np.full((len(tails), length), pad, dtype=np.int32)
            mask = np.zeros((len(tails), length), dtype=np.int32)
            targets = np.zeros((len(tails), length), dtype=np.int32)
            weight = np.zeros((len(tails), length), dtype=np.float32)
            for k, tail in enumerate(tails):
                seq = prompt + tail
                ids[k, :len(seq)] = seq
                mask[k, :len(seq)] = 1
                # logits at position t predict token t+1
                targets[k, len(prompt) - 1:len(seq) - 1] = tail
                weight[k, len(prompt) - 1:len(seq) - 1] = 1
            self._cache = {key: (mx.array(ids), mx.array(mask), mx.array(targets), mx.array(weight), len(prompt))}
        return self._cache[key]

    def _option_scores(self, row):
        ids, mask, targets, weight, prompt_length = self._batch(row)
        output = self.model(ids, None, mask)
        # Only the positions that predict a continuation token matter. Slicing before the float32 log-softmax keeps the
        # vocabulary-wide tensors to a few positions instead of the whole prompt, which is most of the memory in a sleep step.
        start = prompt_length - 1
        logits = getattr(output, "logits", output)[:, start:].astype(mx.float32)
        logp = nn.log_softmax(logits, axis=-1)
        token_logp = mx.take_along_axis(logp, targets[:, start:, None], axis=-1)[..., 0]
        return (token_logp * weight[:, start:]).sum(axis=1)

    def log_probs(self, row):
        scores = self._option_scores(row)
        return scores - mx.logsumexp(scores)

    @contextmanager
    def without_adapter(self):
        scales = [module.scale for module in self.lora]
        for module in self.lora:
            module.scale = 0.0
        try:
            yield
        finally:
            for module, scale in zip(self.lora, scales):
                module.scale = scale

    def base_log_probs(self, row):
        with self.without_adapter():
            logp = self.log_probs(row)
            mx.eval(logp)
        return np.array(logp, dtype=np.float64)

    def reason(self, row, choice, seed=0):
        """One sentence after the choice is already made. Logs only."""
        from mlx_vlm import generate
        mx.random.seed(seed)
        prompt = self.prompt_text(row) + continuation(choice) + ', "reason": "'
        text = generate(self.model, self.processor, prompt, max_tokens=REASON_TOKENS, temperature=REASON_TEMPERATURE, verbose=False).text
        return text.split('"')[0].strip()

    def save(self, path):
        from mlx_vlm.trainer.common.utils import save_trainable_weights
        save_trainable_weights(self.model, path)
