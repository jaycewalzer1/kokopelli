"""A pretend model, for testing the whole pipeline on any machine in seconds.

An arm's behavior can be tilted two ways: `mock.risk_tilt` in its config, or a fake adapter folder whose
adapter_config.json holds {"fake": true, "risk_tilt": 0.5}. The second goes through the same path a real adapter
will take, including hashing, which is how planted-effect tests prove the stats can see an effect.
"""
import random
import time

from benchmarks.backends.base import Backend, GenResult, adapter_hash, read_fake_marker
from benchmarks.core import stable_int

MALFORMED = ("I'm not sure about this one.", '{"choices": ["A", "B"', "Well, it depends on your goals.", "")


class MockBackend(Backend):
    name = "mock"
    is_real = False

    def __init__(self):
        self.arm_name, self.risk_tilt, self.malformed_rate = "", 0.0, 0.0

    def prepare_arm(self, arm, seed):
        adapter = arm.adapter_for(seed) or arm.weights_for(seed)
        fake = read_fake_marker(adapter) or {}
        settings = arm.mock or {}
        self.arm_name = arm.name
        self.risk_tilt = fake.get("risk_tilt", settings.get("risk_tilt", 0.0))
        self.malformed_rate = settings.get("malformed_rate", 0.0)
        return {"model_id": arm.model, "adapter_path": adapter, "adapter_hash": adapter_hash(adapter)}

    def generate_batch(self, requests):
        results = []
        for request in requests:
            started = time.perf_counter()
            # The arm is in this seed, or two identical arms would give identical answers and any test would be trivial.
            rng = random.Random(stable_int("mock", self.arm_name, request.seed))
            context = request.mock_context
            if rng.random() < self.malformed_rate:
                text = rng.choice(MALFORMED)
            else:
                text = context["instrument"].mock_answer(context["item"], context["order"], rng, self.risk_tilt)
            results.append(GenResult(text, time.perf_counter() - started))
        return results

    def openai_endpoint(self, arm):
        return ("mock://", arm.name)
