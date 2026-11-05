"""The real base model on this Mac, called through the repo's llm_model.ask.

Always start it through the shared GPU queue (ops/gpu.py, see HANDOFF.md). The queue doesn't recognize this
process as a model job, so a run started directly would be invisible to it and could overlap another model.

What ask() lets us set, and what it doesn't:
  - temperature, max_tokens: passed directly.
  - top_p, top_k, repetition_penalty: ask() has no way to pass them, so mlx-vlm reads them from the checkpoint's
    generation_config.json. They are fixed in practice, as long as nobody changes that file, and each run records them.
  - seed: ask() has no seed argument. mlx-vlm's sampler draws from MLX's global random state, so calling
    mx.random.seed() just before ask() should make a draw repeatable. That's an implementation detail of the library,
    not a promise from ask(), so runs record it as `seed_method`.
  - temperature 0.0 means greedy: always the likeliest token, with no sampling at all.

There's no adapter support: ask() always uses the plain base model, so any arm with an adapter is refused.
"""
import json
import time

from benchmarks.backends.base import Backend, GenResult
from benchmarks.core import REPO


class LLMModelBackend(Backend):
    name = "llm_model"

    def __init__(self):
        import sys
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        import mlx.core as mx
        import llm_model
        from settings import LLM_MODEL_WEIGHTS
        self.mx, self.llm_model, self.weights = mx, llm_model, LLM_MODEL_WEIGHTS
        if not (self.weights / "config.json").exists():
            raise FileNotFoundError(f"No weights at {self.weights}. In a worktree, symlink models to the main checkout's models.")

    def effective_sampling(self, sampling):
        config = json.loads((self.weights / "generation_config.json").read_text())
        checkpoint = {key: config.get(key) for key in ("top_p", "top_k", "repetition_penalty")}
        for key in ("top_p", "top_k"):
            wanted = sampling.get(key)
            if wanted is not None and wanted != checkpoint[key]:
                raise ValueError(f"llm_model.ask can't set {key}. Asked for {wanted}, but the checkpoint fixes {checkpoint[key]}.")
        return {**sampling, **checkpoint, "fixed_by": "checkpoint generation_config.json (ask() can't set top_p, top_k or repetition_penalty)",
                "seed_method": "mx.random.seed() before each ask() call; relies on mlx-vlm drawing from the global random state"}

    def prepare_arm(self, arm, seed):
        if arm.adapter_for(seed):
            raise ValueError(f"Arm {arm.name} has an adapter, but llm_model.ask only runs the base model. Use the vllm or api backend.")
        return {"model_id": str(self.weights.name), "adapter_path": None, "adapter_hash": None}

    def generate_batch(self, requests):
        results = []
        for request in requests:
            # MLX seeds are 32-bit or 64-bit depending on version, so stay in the safe range.
            self.mx.random.seed(request.seed % (2**31))
            started = time.perf_counter()
            text = self.llm_model.ask(request.prompt, max_tokens=request.sampling["max_tokens"],
                                      temperature=request.sampling["temperature"])
            results.append(GenResult(text, time.perf_counter() - started))
        return results

    def close(self):
        self.llm_model.unload()
