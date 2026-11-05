"""vLLM on a PACE GPU, with LoRA hot-swapping. Untested against real vLLM: there's no GPU or vllm package here.

What's LoRA hot-swapping? A LoRA adapter is a small set of weight changes added on top of a big frozen model.
Loading the 8B model takes minutes, but an adapter is small, so vLLM loads the base model once and applies a
different adapter per request. Every arm then runs on the identical base model in the same process, and switching
arms costs almost nothing. Without this, each arm would pay for a full model load.

Each request names its adapter with a LoRARequest. max_loras is how many adapters stay in GPU memory at once, and
others are swapped in when needed.

Known risk: adapters trained here with mlx-vlm are saved as `adapters.safetensors` in MLX's layout, while vLLM expects
PEFT's `adapter_model.safetensors` and `adapter_config.json`. They need converting first (see HANDOFF.md).
"""
import time
from pathlib import Path

from benchmarks.backends.base import Backend, GenResult, adapter_hash, check_not_fake
from benchmarks.core import stable_int


class VLLMBackend(Backend):
    name = "vllm"
    batch_size = 32

    def __init__(self, model=None, max_lora_slots=8):
        # Imported here so that everything else in this suite works on machines without vLLM.
        from vllm import LLM
        from transformers import AutoTokenizer
        self.model_name = model
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.llm = LLM(model=model, enable_lora=True, max_loras=max_lora_slots, seed=0,
                       limit_mm_per_prompt={"image": 0, "video": 0})
        self.lora = None

    def prepare_arm(self, arm, seed):
        adapter = arm.adapter_for(seed)
        check_not_fake(adapter)
        if adapter:
            if not (Path(adapter) / "adapter_config.json").exists():
                raise FileNotFoundError(f"{adapter} has no adapter_config.json. Is it converted from MLX to PEFT format?")
            from vllm.lora.request import LoRARequest
            # The id must be a positive whole number that stays the same for the same adapter.
            lora_id = stable_int("lora", adapter) % (2**31 - 1) + 1
            self.lora = LoRARequest(lora_name=f"{arm.name}_seed{seed}", lora_int_id=lora_id, lora_path=str(adapter))
        else:
            self.lora = None
        return {"model_id": self.model_name, "adapter_path": adapter, "adapter_hash": adapter_hash(adapter)}

    def generate_batch(self, requests):
        from vllm import SamplingParams
        prompts = [self.tokenizer.apply_chat_template([{"role": "user", "content": request.prompt}], tokenize=False,
                                                      add_generation_prompt=True) for request in requests]
        params = [SamplingParams(temperature=request.sampling["temperature"], top_p=request.sampling.get("top_p") or 1.0,
                                 top_k=request.sampling.get("top_k") or 0, max_tokens=request.sampling["max_tokens"],
                                 seed=request.seed % (2**31)) for request in requests]
        started = time.perf_counter()
        outputs = self.llm.generate(prompts, params, lora_request=self.lora, use_tqdm=False)
        latency = (time.perf_counter() - started) / max(len(requests), 1)  # A batch has one duration, so this is the average.
        return [GenResult(output.outputs[0].text.strip(), latency) for output in outputs]
