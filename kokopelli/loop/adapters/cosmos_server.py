"""Cosmos on NVIDIA GPUs, through the vLLM-Omni server. This follows the model README but hasn't run on a real GPU yet.

The README's rollout conditions each chunk on one frame, the last of the chunk before, so a run on this backend uses
cond_frames=1. That also changes what a re-anchor does: it replaces the only conditioning frame instead of the oldest of
five, so the next chunk starts directly from the sim's picture. Expect a stronger pull back, and a more visible jump.

With a control video, this is filter mode on Cosmos3-Nano-Sim-Transfer: the sim's geometry fixes every frame and the model
paints them. The fields follow its model card, which only shows one-request sessions. Keeping a session open across
requests, so appearance carries from chunk to chunk, is untested. The server has to be able to read control_path.
"""
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path

from kokopelli.loop.interfaces import WorldModel

FPS = 24
GUIDANCE = 6.0
FLOW_SHIFT = 10.0
MAX_PROMPT_TOKENS = 4096
TIMEOUT_SECONDS = 3600
ATTEMPTS = 3
RETRY_WAIT_SECONDS = 30
FILTER_MODEL = "nvidia/Cosmos3-Nano-Sim-Transfer"
FILTER_HISTORY = {"kv_cache_inference_size": 30, "attention_sink_size": 3}


class CosmosServerWorldModel(WorldModel):
    def __init__(self, url, size, steps, negative_prompt=None, control_kind="depth"):
        self.url, self.size, self.steps, self.negative_prompt = url.rstrip("/"), size, steps, negative_prompt
        # A new process can't continue the server's old session, so a resumed run starts a new one and may show a seam.
        self.session, self.session_open, self.control_kind = uuid.uuid4().hex, False, control_kind

    def form(self, request):
        data = {"prompt": request.prompt, "size": self.size, "num_frames": str(request.frames), "fps": str(FPS),
                "num_inference_steps": str(self.steps), "guidance_scale": str(GUIDANCE), "flow_shift": str(FLOW_SHIFT),
                "max_sequence_length": str(MAX_PROMPT_TOKENS), "seed": str(request.seed),
                "extra_params": json.dumps({"use_resolution_template": False, "use_duration_template": False, "guardrails": True})}
        if self.negative_prompt:
            data["negative_prompt"] = self.negative_prompt
        return data

    def filter_form(self, request, hint):
        extra = {"session_id": self.session, "reset": not self.session_open, "close_session": False, "resolution": "480",
                 "aspect_ratio": "16,9", "max_prompt_tokens": MAX_PROMPT_TOKENS, "emphasize_control_in_prompt": False,
                 **FILTER_HISTORY, hint: {"control_path": str(Path(request.control).resolve())}}
        return {"model": FILTER_MODEL, "prompt": request.prompt, "size": self.size, "num_frames": str(request.frames),
                "fps": str(FPS), "seed": str(request.seed), "extra_params": json.dumps(extra)}

    def render_chunk(self, request):
        if request.control:
            self._post(request, self.filter_form(request, self.control_kind), None)
            self.session_open = True
            return request.output
        if len(request.cond) != 1:
            raise ValueError(f"this backend conditions on one frame, got {len(request.cond)}; use cond_frames=1")
        return self._post(request, self.form(request), Path(request.cond[0].path))

    def _post(self, request, form, path):
        import requests  # Imported here so runs that don't use this backend don't need it.

        response = None
        # A 30 minute run makes 240 of these, so one dropped connection shouldn't cost a restart. A 4xx won't fix itself.
        for attempt in range(ATTEMPTS):
            try:
                # The model card sends a filter request as a plain form, with no file attached.
                with path.open("rb") if path else open(os.devnull, "rb") as image:
                    files = {"input_reference": (path.name, image, mimetypes.guess_type(path.name)[0] or "image/png")} if path else None
                    response = requests.post(f"{self.url}/v1/videos/sync", data=form, files=files,
                                             headers={"Accept": "video/mp4"}, timeout=TIMEOUT_SECONDS)
                if response.status_code < 500:
                    break
            except requests.ConnectionError:
                if attempt == ATTEMPTS - 1:
                    raise
            time.sleep(RETRY_WAIT_SECONDS)
        assert response is not None  # ATTEMPTS >= 1: the loop either raised or set it
        response.raise_for_status()
        output = Path(request.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        return str(output)
