"""Backends turn a prompt into text. get_backend imports lazily, so using one doesn't need the others' packages."""


def get_backend(name, **options):
    if name == "mock":
        from benchmarks.backends.mock import MockBackend
        return MockBackend()
    if name == "llm_model":
        from benchmarks.backends.llm_model_backend import LLMModelBackend
        return LLMModelBackend()
    if name == "api":
        from benchmarks.backends.api import APIBackend
        return APIBackend(base_url=options.get("base_url"))
    if name == "vllm":
        from benchmarks.backends.vllm import VLLMBackend
        return VLLMBackend(model=options.get("model"), max_lora_slots=options.get("max_lora_slots", 8))
    raise ValueError(f"Unknown backend: {name}")
