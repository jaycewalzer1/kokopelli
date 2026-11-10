"""The real model on this Mac, called through the repo's llm_model.ask.

Always start it through the shared GPU queue (kokopelli/ops/gpu.py, see HANDOFF.md). The queue doesn't recognize this
process as a model job, so a run started directly would be invisible to it and could overlap another model.

What ask() lets us set, and what it doesn't:
  - temperature, max_tokens: passed directly.
  - top_p, top_k, repetition_penalty: ask() has no way to pass them, so mlx-vlm reads them from the checkpoint's
    generation_config.json. They are fixed in practice, as long as nobody changes that file, and each run records them.
  - seed: ask() has no seed argument. mlx-vlm's sampler draws from MLX's global random state, so calling
    mx.random.seed() just before ask() makes a draw repeatable, once the model is loaded. Tests check this on a tiny
    model. It's an implementation detail of the library, not a promise from ask(), so runs record it as `seed_method`.
  - temperature 0.0 means greedy: always the likeliest token, with no sampling at all.

Which model answers: ask() loads whatever llm_model.LLM_MODEL_WEIGHTS points to, so an arm with `weights` (a folder of
full weights, such as fused/ from homeostatic.export) points it there. That is the same thing runtime's MlxQwenAgent
does. ask() can't apply an adapter, so an arm with an `adapter` is refused: fuse it first.
"""
import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from experiments.benchmarks.backends.base import Backend, GenResult, adapter_hash, check_not_fake


class LLMModelBackend(Backend):
    name = "llm_model"

    def __init__(self):
        import mlx.core as mx
        from kokopelli.wm import llm_model
        from kokopelli.settings import LLM_MODEL_WEIGHTS
        self.mx, self.llm_model, self.weights = mx, llm_model, Path(LLM_MODEL_WEIGHTS)
        self.current = self.weights
        if not (self.weights / "config.json").exists():
            raise FileNotFoundError(f"No weights at {self.weights}. In a worktree, symlink models to the main checkout's models.")

    def _checkpoint_sampling(self, folder):
        config = json.loads((Path(folder) / "generation_config.json").read_text())
        return {key: config.get(key) for key in ("top_p", "top_k", "repetition_penalty")}

    def effective_sampling(self, sampling):
        checkpoint = self._checkpoint_sampling(self.weights)
        for key in ("top_p", "top_k"):
            wanted = sampling.get(key)
            if wanted is not None and wanted != checkpoint[key]:
                raise ValueError(f"llm_model.ask can't set {key}. Asked for {wanted}, but the checkpoint fixes {checkpoint[key]}.")
        return {**sampling, **checkpoint, "fixed_by": "checkpoint generation_config.json (ask() can't set top_p, top_k or repetition_penalty)",
                "seed_method": "mx.random.seed() before each ask() call; relies on mlx-vlm drawing from the global random state"}

    def _check_folder(self, folder):
        """A before-and-after comparison is only fair if the after model samples the same way as the before model."""
        if not (folder / "config.json").exists() or not any(folder.glob("*.safetensors")):
            raise FileNotFoundError(f"{folder} isn't a folder of full weights. Expected config.json and *.safetensors, as in fused/ from homeostatic.export.")
        if (folder / "generation_config.json").exists() and self._checkpoint_sampling(folder) != self._checkpoint_sampling(self.weights):
            raise ValueError(f"{folder} has different sampling defaults from {self.weights}, so results wouldn't be comparable.")

    def prepare_arm(self, arm, seed):
        if arm.adapter_for(seed):
            raise ValueError(f"Arm {arm.name} has an adapter, but llm_model.ask only runs full weights (base model only, unless `weights` is set). "
                             "Fuse the adapter with homeostatic.export and set `weights`, or use the vllm or api backend.")
        weights = arm.weights_for(seed)
        check_not_fake(weights)
        target = Path(weights) if weights else self.weights
        if weights:
            self._check_folder(target)
        if target != self.current or self.llm_model.LLM_MODEL_WEIGHTS != target:
            self.llm_model.unload()  # Two 18 GB models don't fit, and ask() would otherwise keep using the cached one.
            self.llm_model.LLM_MODEL_WEIGHTS = target
            self.current = target
        return {"model_id": target.name, "adapter_path": str(target) if weights else None, "adapter_hash": adapter_hash(target) if weights else None}

    def generate_batch(self, requests):
        results = []
        # Load before seeding. Building the model's layers uses up random numbers, so a load inside ask() would
        # silently change the first sample after every load.
        self.llm_model.load_llm()
        for request in requests:
            # MLX seeds are 32-bit or 64-bit depending on version, so stay in the safe range.
            self.mx.random.seed(request.seed % (2**31))
            started = time.perf_counter()
            text = self.llm_model.ask(request.prompt, max_tokens=request.sampling["max_tokens"],
                                      temperature=request.sampling["temperature"])
            results.append(GenResult(text, time.perf_counter() - started))
        return results

    def _chat(self, body):
        """Answer one OpenAI-style chat request. ask() takes a single prompt, so several messages are joined."""
        messages = body.get("messages", [])
        prompt = "\n\n".join(str(message.get("content", "")) for message in messages)
        return self.llm_model.ask(prompt, max_tokens=int(body.get("max_tokens") or 256), temperature=float(body.get("temperature") or 0.0))

    def run_harness_command(self, arm, build_command):
        """Serve this arm over a small local OpenAI-style server while an outside tool runs against it.

        Requests are handled on this thread, not a background one, because mlx-vlm's generation stream is thread-local.
        One request runs at a time, which is what ask() can do anyway. `stop` strings are ignored, which is harmless for
        lm-eval because it filters answers itself.
        """
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                reply = {"id": "evals_local", "object": "chat.completion", "model": body.get("model", ""),
                         "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": backend._chat(body)}}],
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)  # Port 0 asks the system for a free port.
        server.timeout = 1
        command = build_command(f"http://127.0.0.1:{server.server_address[1]}/v1", arm.name)
        process = subprocess.Popen(command)
        try:
            while process.poll() is None:
                server.handle_request()
        finally:
            server.server_close()
            if process.poll() is None:
                process.terminate()
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)

    def close(self):
        self.llm_model.unload()
        self.llm_model.LLM_MODEL_WEIGHTS = self.weights
        self.current = self.weights
