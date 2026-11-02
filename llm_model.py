"""Utility functions for calling the LLM. The first call loads it; later calls reuse it."""
import gc
from functools import lru_cache

import mlx.core as mx
from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template

from settings import LLM_MODEL_WEIGHTS


@lru_cache(maxsize=1)
def load_llm():
    return load(str(LLM_MODEL_WEIGHTS))


def ask(prompt, images=(), max_tokens=512, temperature=0.0):
    """Return the model's answer to a prompt, optionally about image paths."""
    model, processor = load_llm()
    images = [str(image) for image in images]
    formatted = apply_chat_template(processor, model.config, prompt, num_images=len(images))
    result = generate(model, processor, formatted, image=images or None,
                      max_tokens=max_tokens, temperature=temperature)
    return result.text.strip()


def unload():
    """Free the model's memory. Do this before the world model runs; together they barely fit in 36 GB."""
    load_llm.cache_clear()
    gc.collect()
    mx.clear_cache()
