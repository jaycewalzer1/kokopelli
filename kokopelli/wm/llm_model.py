"""Utility functions for calling the LLM. The first call loads it; later calls reuse it."""
import gc
from functools import lru_cache

import mlx.core as mx
from mlx_vlm import generate, load  # pyright: ignore[reportPrivateImportUsage]  # mlx_vlm doesn't declare its re-exports
from mlx_vlm.prompt_utils import apply_chat_template

from kokopelli.settings import LLM_MODEL_WEIGHTS


@lru_cache(maxsize=1)
def load_llm():
    return load(str(LLM_MODEL_WEIGHTS))


def ask(prompt, images=(), max_tokens=512, temperature=0.0):
    """Return the model's answer to a prompt, optionally about image paths."""
    model, processor = load_llm()
    images = [str(image) for image in images]
    formatted = apply_chat_template(processor, model.config, prompt, num_images=len(images))
    result = generate(model, processor, formatted, image=images or None,  # pyright: ignore[reportArgumentType]  # mlx_vlm's annotations are narrower than what it accepts
                      max_tokens=max_tokens, temperature=temperature)
    return result.text.strip()


def chat(system, user, max_tokens=512, temperature=0.7, seed=None):
    """Return the whole result, with its timings and token counts, for a system and user message."""
    model, processor = load_llm()
    if seed is not None:
        mx.random.seed(seed)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    formatted = apply_chat_template(processor, model.config, messages)
    return generate(model, processor, formatted, max_tokens=max_tokens, temperature=temperature)  # pyright: ignore[reportArgumentType]  # mlx_vlm's annotations are narrower than what it accepts


def unload():
    """Free the model's memory. Do this before the world model runs; together they barely fit in 36 GB."""
    load_llm.cache_clear()
    gc.collect()
    mx.clear_cache()
