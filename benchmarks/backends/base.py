"""The interface all backends share, plus adapter fingerprinting."""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GenRequest:
    prompt: str
    sampling: dict
    seed: int
    # Only the mock looks at this. Real backends must answer from the prompt alone.
    mock_context: dict = field(default_factory=dict)


@dataclass
class GenResult:
    text: str
    latency_s: float


def adapter_files(adapter_path):
    """Weight files in an adapter folder, in a fixed order."""
    folder = Path(adapter_path)
    return sorted(path for path in folder.rglob("*") if path.suffix == ".safetensors" and path.is_file())


def adapter_hash(adapter_path):
    """A hash over an adapter's weights, so each result says exactly which adapter produced it."""
    if not adapter_path:
        return None
    files = adapter_files(adapter_path)
    if not files:
        return None
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_fake_marker(adapter_path):
    """A fake adapter has {"fake": true} in adapter_config.json. Returns that config, or None for a real one."""
    if not adapter_path:
        return None
    config = Path(adapter_path) / "adapter_config.json"
    if not config.exists():
        return None
    data = json.loads(config.read_text())
    return data if data.get("fake") else None


class Backend:
    name = ""
    is_real = True          # Real backends are subject to the pre-registration guard.
    batch_size = 1

    def effective_sampling(self, sampling):
        """Everything really in force for generation, including values the caller can't change."""
        return dict(sampling)

    def prepare_arm(self, arm, seed):
        """Get ready to answer as this arm. Returns adapter details to store with each result."""
        raise NotImplementedError

    def generate_batch(self, requests):
        raise NotImplementedError

    def openai_endpoint(self, arm):
        """(base_url, model name) for tools that talk to an OpenAI-style server, such as the guardrail harness."""
        raise NotImplementedError(f"{self.name} has no OpenAI-style endpoint for outside tools.")

    def close(self):
        pass


def check_not_fake(adapter_path):
    if read_fake_marker(adapter_path):
        raise ValueError(f"{adapter_path} is a fake test adapter. Only the mock backend can use it.")
