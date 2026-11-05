"""Cosmos on NVIDIA GPUs, through the vLLM-Omni server. This follows the model README but hasn't run on a real GPU yet.

The README's rollout conditions each chunk on one frame, the last of the chunk before, so a run on this backend uses
cond_frames=1. That also changes what a re-anchor does: it replaces the only conditioning frame instead of the oldest of
five, so the next chunk starts directly from the sim's picture. Expect a stronger pull back, and a more visible jump.
"""
import json
import mimetypes
from pathlib import Path

from runtime.interfaces import WorldModel

FPS = 24
GUIDANCE = 6.0
FLOW_SHIFT = 10.0
MAX_PROMPT_TOKENS = 4096
TIMEOUT_SECONDS = 3600


class CosmosServerWorldModel(WorldModel):
    def __init__(self, url, size, steps, negative_prompt=None):
        self.url, self.size, self.steps, self.negative_prompt = url.rstrip("/"), size, steps, negative_prompt

    def form(self, request):
        data = {"prompt": request.prompt, "size": self.size, "num_frames": str(request.frames), "fps": str(FPS),
                "num_inference_steps": str(self.steps), "guidance_scale": str(GUIDANCE), "flow_shift": str(FLOW_SHIFT),
                "max_sequence_length": str(MAX_PROMPT_TOKENS), "seed": str(request.seed),
                "extra_params": json.dumps({"use_resolution_template": False, "use_duration_template": False, "guardrails": True})}
        if self.negative_prompt:
            data["negative_prompt"] = self.negative_prompt
        return data

    def render_chunk(self, request):
        import requests  # Imported here so runs that don't use this backend don't need it.

        if len(request.cond) != 1:
            raise ValueError(f"this backend conditions on one frame, got {len(request.cond)}; use cond_frames=1")
        path = Path(request.cond[0].path)
        with path.open("rb") as image:
            files = {"input_reference": (path.name, image, mimetypes.guess_type(path.name)[0] or "image/png")}
            response = requests.post(f"{self.url}/v1/videos/sync", data=self.form(request), files=files,
                                     headers={"Accept": "video/mp4"}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        output = Path(request.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        return str(output)
