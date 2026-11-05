"""Any OpenAI-compatible server, such as a local mlx_vlm.server or a hosted API.

Uses only `requests`, so there's no extra client package. The key comes from OPENAI_API_KEY if a server needs one.
An arm with an adapter uses the arm's `api_model` as the model name, because a server names its loaded adapters itself.
"""
import os
import time

import requests

from benchmarks.backends.base import Backend, GenResult, check_not_fake

DEFAULT_URL = "http://127.0.0.1:8000/v1"


def chat_once(prompt, model, base_url=None, temperature=0.0, max_tokens=256, top_p=None, seed=None, timeout=300):
    url = (base_url or os.environ.get("EVALS_API_BASE") or DEFAULT_URL).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"} if os.environ.get("OPENAI_API_KEY") else {}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens}
    if top_p is not None:
        body["top_p"] = top_p
    if seed is not None:
        body["seed"] = seed
    response = requests.post(url, json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


class APIBackend(Backend):
    name = "api"

    def __init__(self, base_url=None):
        self.base_url = base_url or os.environ.get("EVALS_API_BASE") or DEFAULT_URL
        self.model = None

    def prepare_arm(self, arm, seed):
        adapter = arm.adapter_for(seed)
        check_not_fake(adapter)
        if arm.is_trained and not arm.api_model:
            # Falling back to the base model's name would run the base model and label the results as this arm.
            raise ValueError(f"Arm {arm.name} has an adapter or weights but no api_model, so the server wouldn't know to apply it.")
        self.model = (arm.api_model or arm.model).format(seed=seed)
        from benchmarks.backends.base import adapter_hash
        return {"model_id": self.model, "adapter_path": adapter, "adapter_hash": adapter_hash(adapter)}

    def generate_batch(self, requests_):
        results = []
        for request in requests_:
            started = time.perf_counter()
            text = chat_once(request.prompt, self.model, self.base_url, request.sampling["temperature"],
                             request.sampling["max_tokens"], request.sampling.get("top_p"), request.seed % (2**31))
            results.append(GenResult(text, time.perf_counter() - started))
        return results

    def openai_endpoint(self, arm):
        return (self.base_url, self.model)
