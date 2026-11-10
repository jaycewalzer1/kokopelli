"""Qwen3-VL-8B as the agent: on MLX through llm_model.py, or from any OpenAI-style server such as vLLM on a GPU node."""
import base64
import json
import urllib.request
from pathlib import Path

from runtime.interfaces import AgentPolicy

MAX_TOKENS = 300


def _with_retry_note(agent_input):
    if not agent_input.retry_error:
        return agent_input.prompt
    return f"{agent_input.prompt}\n\nYour last reply was rejected: {agent_input.retry_error}\nReply with only the JSON object."


class MlxQwenAgent(AgentPolicy):
    def __init__(self, weights=None):
        self.weights = weights

    def decide(self, agent_input):
        from core import llm_model  # Imported here because mlx only exists on Apple silicon.
        if self.weights:
            llm_model.LLM_MODEL_WEIGHTS = self.weights
        ask = llm_model.ask
        return ask(_with_retry_note(agent_input), agent_input.images, max_tokens=MAX_TOKENS)

    def release(self):
        # On 36 GB, Qwen and Cosmos can't be loaded together. See README.md.
        from core.llm_model import unload
        unload()


class ServerQwenAgent(AgentPolicy):
    """Not yet run against a real server. vLLM speaks the OpenAI chat API, which is what this sends."""

    def __init__(self, url, model):
        self.url, self.model = url.rstrip("/"), model

    def decide(self, agent_input):
        images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()}}
                  for path in agent_input.images]
        body = {"model": self.model, "temperature": 0, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": [*images, {"type": "text", "text": _with_retry_note(agent_input)}]}]}
        request = urllib.request.Request(f"{self.url}/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)["choices"][0]["message"]["content"]
