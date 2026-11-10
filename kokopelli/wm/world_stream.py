"""A world model that keeps running: Cosmos3-Nano-Sim-Transfer (4 controls, MLX) as one causal rollout fed step by step.

world_transfer.py / world_transfer_multi.py paint a finished control clip in one go. A life doesn't arrive as a finished
clip: the sim advances a step, its controls arrive, the world model paints them, the agent looks and acts, and the next
step continues the same video. This worker keeps the model's causal history (text + control/RGB keys and values) alive
between steps, so every step's frames continue the one video and the pieces stitch into a single film.

Two processes, because the world model lives in ~/cosmos3/cosmos3-mlx/.venv and the agent in the repo's .venv:

    from kokopelli.wm.world_stream import WorldStream                         # agent side, stdlib + numpy only
    wm = WorldStream(prompt, size="448x256", fps=24, out_dir=...)  # starts the worker
    frames = wm.push({"depth": d, "seg": s, "edge": e, "blur": b})  # uint8 [n, H, W, 3] each -> painted uint8 frames
    wm.release()   # drop the 14 GB of weights while Qwen thinks (history stays); the next push reloads them
    wm.close()

Approximations beyond world_transfer.py's (docs/SIM_TRANSFER_MLX.md): the VAE encodes and decodes each step's new frames
with 3 earlier latents as causal warm-up rather than one cache over the whole life, and the target of the newest latent is
always written to the history (the batch runner skips the very last one). Positions and seeds follow the global latent index.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
HINTS = ("blur", "seg", "depth", "edge")
WARM = 3
# KOKO_PROFILE=1: each push reply carries "profile", seconds per stage (docs/PAINT_PROFILE.md). MLX is lazy, so a timed
# stage evaluates its own results before its clock stops; that sync is the only change in behavior, and only when profiling.
PROFILE = os.environ.get("KOKO_PROFILE") == "1"


SHM_OUT = "shm"   # a push's `out` when the client wants the painted frames back in shared memory (KOKO_WM_SHM=1)


def _untrack(shm):
    """Python 3.12's resource tracker claims every segment a process opens and destroys it when that process exits.
    The client owns these segments (it unlinks them), so the worker must not hold a claim."""
    from multiprocessing import resource_tracker
    resource_tracker.unregister(shm._name, "shared_memory")


def read_frames(spec):
    """A push's control frames, uint8 [n, H, W, 3]: an .npy path, or {"shm": name, "shape": [...]} (KOKO_WM_SHM=1)."""
    import numpy as np
    if isinstance(spec, str):
        return np.load(spec)
    from multiprocessing import shared_memory
    shm = shared_memory.SharedMemory(name=spec["shm"])
    _untrack(shm)
    try:
        return np.ndarray(spec["shape"], np.uint8, buffer=shm.buf).copy()
    finally:
        shm.close()


def write_frames(frames, out):
    """Painted frames for the client: saved to the .npy path `out`, or put in a new shared-memory segment when `out` is
    SHM_OUT. Returns what the reply's "out" should say."""
    import numpy as np
    if out != SHM_OUT:
        np.save(out, frames)
        return out
    from multiprocessing import shared_memory
    shm = shared_memory.SharedMemory(create=True, size=max(1, frames.nbytes))
    _untrack(shm)
    np.ndarray(frames.shape, np.uint8, buffer=shm.buf)[:] = frames
    shm.close()
    return {"shm": shm.name, "shape": list(frames.shape)}


class Stages:
    """Seconds per named stage, summed over repeats. A no-op unless KOKO_PROFILE=1."""

    def __init__(self, mx=None):
        self.mx, self.s = mx, {}

    @contextmanager
    def __call__(self, name, sync=None):
        if not PROFILE:
            yield
            return
        t = time.perf_counter()
        yield
        if sync is not None and self.mx is not None:
            self.mx.eval(sync() if callable(sync) else sync)
        self.s[name] = self.s.get(name, 0.0) + time.perf_counter() - t

    def report(self):
        return {k: round(v, 3) for k, v in self.s.items()}


class WorldStream:
    """Agent-side handle. Each call is one JSON line to the worker and one back."""

    def __init__(self, prompt, size="448x256", fps=24, weights=None, seed=2025, window=24, sink=1, quantize=None,
                 planned_frames=None, out_dir=None, raw_prompt=False):
        self.dir = Path(out_dir or tempfile.mkdtemp(prefix="world_stream_"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.k = 0
        self.log = (self.dir / "worker.log").open("a")
        self.proc = subprocess.Popen([str(RUNNER / ".venv" / "bin" / "python"), "-m", "kokopelli.wm.world_stream", "--worker"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, cwd=RUNNER,
                                     env={**os.environ, "PYTHONPATH": f"{RUNNER}:{ROOT}"})
        self.info = self._call(cmd="start", prompt=prompt, size=size, fps=fps, weights=weights or {h: 0.25 for h in HINTS},
                               seed=seed, window=window, sink=sink, quantize=quantize, planned_frames=planned_frames,
                               raw_prompt=raw_prompt)

    def _call(self, **msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"world model worker died; see {self.dir / 'worker.log'}")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(f"world model worker: {reply['error']}")
        return reply

    def push(self, controls):
        """controls: {hint: uint8 [n, H, W, 3]}, same n for all. Returns the newly painted frames, uint8 [m, H, W, 3].
        m can lag n by up to 3 frames: a latent is painted once its 4 frames have arrived."""
        import numpy as np
        self.k += 1
        paths = {}
        for hint, frames in controls.items():
            paths[hint] = str(self.dir / f"in_{self.k:05d}_{hint}.npy")
            np.save(paths[hint], np.ascontiguousarray(frames, np.uint8))
        reply = self._call(cmd="push", controls=paths, out=str(self.dir / f"out_{self.k:05d}.npy"))
        for p in paths.values():
            Path(p).unlink(missing_ok=True)
        self.last = reply
        if not reply["frames"]:
            return np.zeros((0,) + controls[next(iter(controls))].shape[1:], np.uint8)
        out = np.load(reply["out"])
        Path(reply["out"]).unlink(missing_ok=True)
        return out

    def release(self):
        return self._call(cmd="release")

    def close(self):
        try:
            self._call(cmd="stop")
        except Exception:
            pass
        self.proc.wait(timeout=60)
        self.log.close()


# ---------------------------------------------------------------- worker, in the cosmos3-mlx venv

class Worker:
    stages = Stages()

    def start(self, prompt, size, fps, weights, seed, window, sink, quantize, planned_frames, raw_prompt):
        import mlx.core as mx
        from kokopelli.wm import world_transfer as wt
        from kokopelli.wm import world_transfer_multi as wm
        mx.set_default_device(mx.gpu)
        self.wt, self.wm, self.mx = wt, wm, mx
        self.model_dir = wt.MODEL_DIR
        cfg = json.loads((self.model_dir / "config.json").read_text())["cosmos3_nano_sim_bimanual"]
        self.sigmas = list(cfg["fixed_step_sampler_config"]["t_list"]) + [0.0]
        self.width, self.height = (int(n) for n in size.split("x"))
        self.fps, self.seed, self.quantize = float(fps), seed, quantize
        self.hints = [h for h in HINTS if h in weights] + [h for h in weights if h not in HINTS]
        norm = wm.normalize_weights({h: None for h in self.hints}, weights)
        self.weights = [norm[h] for h in self.hints]
        planned = planned_frames or int(60 * self.fps)
        self.text = prompt if raw_prompt else wt.format_prompt(prompt, planned, self.fps, self.width, self.height)
        ids = wt.tokenize(self.model_dir, self.text)
        self.n_text = len(ids)
        self.rope = wt.Rope()
        t = time.time()
        arrays = wt.shard_arrays(self.model_dir)
        self.text_kv = wt.text_cache(arrays, ids, self.rope)
        del arrays
        mx.clear_cache()
        self.gen = None
        self.history = wm.MultiHistory(len(self.hints), window, sink)
        self.frames_in = 0                       # control frames received
        self.tail = {h: None for h in self.hints}  # recent control frames kept for encoder warm-up
        self.tail_start = 0                      # global index of tail[0]
        self.lat_c = {h: [] for h in self.hints}  # control latents not yet painted (per hint, list of [1,1,h,w,48])
        self.painted = []                        # recent target latents kept for decoder warm-up
        self.n_painted = 0
        self.frames_out = 0
        self.timing = {"text_s": round(time.time() - t, 1)}
        return {"hints": self.hints, "weights": dict(zip(self.hints, self.weights, strict=False)), "text_tokens": self.n_text,
                "formatted_prompt": self.text, "model": self.model_dir.name, "checkpoint_id": cfg["checkpoint_id"]}

    def _load(self):
        if self.gen is None:
            t = time.time()
            self.gen = self.wm.MultiGenerator(self.wt.shard_arrays(self.model_dir), bits=self.quantize)
            self.mx.clear_cache()
            self.timing["load_s"] = self.timing.get("load_s", 0) + time.time() - t

    def release(self):
        self.gen = None
        import gc
        gc.collect()
        self.mx.clear_cache()
        return {"released": True}

    def _encode(self, new):
        """Append new control frames; encode every latent whose frames are now complete. Latent 0 is frame 0 alone,
        latent j >= 1 is frames 4j-3..4j. A slice starting at frame 4s encodes as [s, s+1, ...], so warm-up works."""
        import numpy as np
        from cosmos3_mlx.encode_vae import encode_video
        mx = self.mx
        n_new = len(next(iter(new.values())))
        for h in self.hints:
            self.tail[h] = new[h] if self.tail[h] is None else np.concatenate([self.tail[h], new[h]])
        self.frames_in += n_new
        done = 1 + (self.frames_in - 1) // 4                    # latents whose frames are complete
        have = self.n_painted + len(self.lat_c[self.hints[0]])  # latents already encoded
        if done <= have:
            return
        s = max(0, have - WARM - 1) if have else 0
        first, last = 4 * s, 4 * (done - 1)                     # global frame range to encode
        for h in self.hints:
            clip = self.tail[h][first - self.tail_start:last - self.tail_start + 1]
            lat = encode_video(clip.astype(np.float32) / 255.0, str(self.model_dir / "vae"))   # [1, done - s, h, w, 48]
            mx.eval(lat)
            for j in range(have - s, done - s):
                self.lat_c[h].append(lat[:, j:j + 1])
        mx.clear_cache()
        keep_from = 4 * max(0, done - 1 - WARM - 1)               # enough frames for the next warm-up
        if keep_from > self.tail_start:
            for h in self.hints:
                self.tail[h] = self.tail[h][keep_from - self.tail_start:]
            self.tail_start = keep_from

    def _paint_latent(self, f, lat_cs):
        mx, wt = self.mx, self.wt
        h_lat, w_lat = lat_cs[0].shape[2:4]
        hp, wp = (h_lat + 1) // 2, (w_lat + 1) // 2
        hh = mx.broadcast_to(mx.arange(hp, dtype=mx.float32)[:, None], (hp, wp)).reshape(-1)
        ww = mx.broadcast_to(mx.arange(wp, dtype=mx.float32)[None, :], (hp, wp)).reshape(-1)
        t_pos = float(self.n_text + wt.MARGIN) + f * (wt.BASE_FPS / self.fps)
        cos, sin = self.rope.tables(mx.stack([mx.full(hh.shape, t_pos), hh, ww]))
        layers = lambda entries: [[self.text_kv[i]] + [e[i] for e in entries] for i in range(36)]
        hist, gen, branches, stage = self.history, self.gen, range(len(self.hints)), self.stages
        with stage("control_branches", sync=lambda: [hist.branches[b].entries[-1] for b in branches]):
            for b in branches:
                hist.add_control(b, gen.control(wt.patchify(lat_cs[b].astype(mx.bfloat16)), cos, sin,
                                                layers(hist.view(b, False))))
        ctxs = [layers(hist.view(b, True)) for b in branches]
        mx.random.seed(self.seed + f)
        x = mx.random.normal((1, 1, h_lat, w_lat, 48)).astype(mx.float32)
        for step, (s, s_next) in enumerate(zip(self.sigmas[:-1], self.sigmas[1:], strict=False)):
            with stage(f"denoise_{step}"):
                v, _ = gen.target(wt.patchify(x.astype(mx.bfloat16)), cos, sin, ctxs, self.weights, sigma=s)
                x0 = x - s * wt.unpatchify(v, h_lat, w_lat)
                if s_next == 0.0:
                    x = x0
                else:
                    mx.random.seed(self.seed + f * 1_000_003 + (step + 1) * 9_176)
                    x = (1 - s_next) * x0 + s_next * mx.random.normal(x.shape).astype(mx.float32)
                mx.eval(x)
        out = x.astype(mx.bfloat16)
        with stage("history_store", sync=lambda: kv):
            ctxs = [layers(hist.view(b, True)) for b in branches]
            _, kv = gen.target(wt.patchify(out), cos, sin, ctxs, self.weights, store=True)
            del ctxs
            hist.add_target(kv)
        mx.clear_cache()
        return out

    def _decode(self, new_latents):
        """Decode the newly painted latents with up to WARM earlier ones as context; return only their frames."""
        import numpy as np
        from cosmos3_mlx.decode_vae import decode_latents
        mx = self.mx
        ctx = self.painted[-WARM:] if self.painted else []
        lat = mx.concatenate(ctx + new_latents, axis=1)
        video = decode_latents(lat, str(self.model_dir / "vae"))
        mx.eval(video)
        video = np.array(video[0].astype(mx.float32))
        first_ever = not self.painted
        # The port's decoder turns the first latent into 4 frames, where the reference makes 1 (a latent after the first
        # is always 4). Without the trim the film runs 3 frames long and 0.1 s behind its controls (smoke test, 2026-11-08).
        # Keep the reference's count, 1 + 4(n-1) on the first push: same as video[3:] when the port made 4n frames, and
        # still the one frame when a first push of a single latent decodes to fewer than 4 (bodies demo, 2026-11-08).
        frames = video[-(1 + 4 * (len(new_latents) - 1)):] if first_ever else video[-4 * len(new_latents):]
        self.painted = (self.painted + new_latents)[-WARM:]
        mx.clear_cache()
        return (frames * 255).round().clip(0, 255).astype(np.uint8)

    def push(self, controls, out):
        mx = self.mx
        self.stages = stage = Stages(mx)
        t0 = time.time()
        with stage("read_controls"):
            new = {h: read_frames(controls[h]) for h in self.hints}
        if any(v.shape[1:3] != (self.height, self.width) for v in new.values()):
            raise ValueError(f"controls must be {self.width}x{self.height}")
        with stage("encode"):
            self._encode(new)
        t_enc = time.time() - t0
        ready = len(self.lat_c[self.hints[0]])
        if not ready:
            return {"frames": 0, "out": out, **({"profile": stage.report()} if PROFILE else {})}
        with stage("weights_load"):
            self._load()
        t1 = time.time()
        mx.reset_peak_memory()
        painted = []
        for _ in range(ready):
            f = self.n_painted
            painted.append(self._paint_latent(f, [self.lat_c[h].pop(0) for h in self.hints]))
            self.n_painted += 1
        t_paint = time.time() - t1
        t2 = time.time()
        with stage("decode"):
            frames = self._decode(painted)
        with stage("write_frames"):
            out = write_frames(frames, out)
        self.frames_out += len(frames)
        return {"frames": len(frames), "out": out, "latents": self.n_painted, "frames_out": self.frames_out,
                "encode_s": round(t_enc, 1), "paint_s": round(t_paint, 1), "decode_s": round(time.time() - t2, 1),
                "s_per_latent": round(t_paint / ready, 2), "peak_gb": round(mx.get_peak_memory() / 2 ** 30, 2),
                **({"profile": stage.report()} if PROFILE else {})}


def serve():
    worker = Worker()
    out = sys.stdout
    sys.stdout = sys.stderr   # anything else printing must not corrupt the protocol
    for line in sys.stdin:
        msg = json.loads(line)
        cmd = msg.pop("cmd")
        try:
            if cmd == "stop":
                out.write(json.dumps({"stopped": True}) + "\n")
                out.flush()
                return
            reply = getattr(worker, cmd)(**msg)
        except Exception as e:
            import traceback
            traceback.print_exc()
            reply = {"error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        serve()
    else:
        print(__doc__)
