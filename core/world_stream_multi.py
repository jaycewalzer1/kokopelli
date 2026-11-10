"""Several continuous world-model rollouts sharing one set of weights: one causal Sim-Transfer video per pair of eyes.

world_stream.py runs one rollout per worker process. Two agents would need two workers, and each would load its own
~14 GB of Cosmos3-Nano-Sim-Transfer weights, which a 36 GB Mac can't hold next to SimWorld and Qwen. This worker loads
the weights once and keeps N independent streams. Each stream is a world_stream.Worker (imported, never edited) with its
own text cache, causal history, encoder/decoder warm-up and frame counters, so each one's frames continue its own video
exactly as a lone WorldStream would. Only the generator (the weights) is shared, and it carries no per-stream state.

    from world_stream_multi import MultiWorldStream                 # agent side, stdlib + numpy only
    wm = MultiWorldStream(out_dir=..., quantize=None)               # starts one worker
    wm.open("mara", prompt, size="448x256", fps=24, seed=2025)      # one stream per agent
    wm.open("iris", prompt, size="448x256", fps=24, seed=2026)
    frames = wm.push("mara", {"blur": b, "seg": s, "depth": d, "edge": e})   # -> painted uint8 [m, H, W, 3]
    wm.release()   # drop the weights while Qwen thinks; every stream keeps its history
    wm.close()

Memory: weights once (~14 GB bf16, ~7 GB with quantize=8) while painting, plus each stream's history, which stays
resident: about 2 GB per stream at 448x256 with window 24 (4 control branches + the shared target entries, 36 layers).

`fake=True` runs a stand-in worker in the caller's own Python, with no MLX and no weights: it "paints" each frame as a
mix of the blur and edge controls, with the real latent lag (latent 0 is frame 0, then 4 frames per latent). The dry
tests use it; it proves the protocol, the multiplexing and the film assembly, nothing about the model.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
HINTS = ("blur", "seg", "depth", "edge")
# KOKO_DRY_RUN=1 (what `gpu.py run --dry-run` sets) or `python -m core.world_stream_multi --dry-run`: load the weights,
# open one stream with the four controls at 0.25, push one frame (latent 0), write dry_run.json, exit 0.
DRY_RUN = os.environ.get("KOKO_DRY_RUN") == "1"


class MultiWorldStream:
    """Agent-side handle to one worker holding many streams. Each call is one JSON line to the worker and one back."""

    def __init__(self, out_dir=None, quantize=None, fake=False, check=None):
        self.dir = Path(out_dir or tempfile.mkdtemp(prefix="world_stream_multi_"))
        # Video check on every push (core/video_check.py): "stop" raises after 3 bad pushes in a row, "warn" only
        # records them in check.json, "off" skips it. The fake painter is not a painting, so it is off there by default.
        self.check = os.environ.get("KOKO_VIDEO_CHECK") or check or ("off" if fake else "stop")
        self.checks = {}
        self.dir.mkdir(parents=True, exist_ok=True)
        self.k = 0
        self.fake = fake
        self.info, self.last = {}, {}
        self.log = (self.dir / "worker.log").open("a")
        python = sys.executable if fake else str(RUNNER / ".venv" / "bin" / "python")
        cmd = [python, str(ROOT / "world_stream_multi.py"), "--worker"] + (["--fake"] if fake else [])
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
                                     cwd=str(ROOT if fake else RUNNER),
                                     env={**os.environ, "PYTHONPATH": str(ROOT) if fake else f"{RUNNER}:{ROOT}"})
        self.hello = self._call(cmd="hello", quantize=quantize)

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

    def open(self, stream, prompt, size="448x256", fps=24, weights=None, seed=2025, window=24, sink=1,
             planned_frames=None, raw_prompt=False):
        """Start a stream. Its seed should differ from the others', or two pairs of eyes share their noise."""
        self.info[stream] = self._call(cmd="open", stream=stream, prompt=prompt, size=size, fps=fps,
                                       weights=weights or {h: 0.25 for h in HINTS}, seed=seed, window=window, sink=sink,
                                       planned_frames=planned_frames, raw_prompt=raw_prompt)
        return self.info[stream]

    def push(self, stream, controls):
        """controls: {hint: uint8 [n, H, W, 3]}, same n for all. Returns this stream's newly painted frames,
        uint8 [m, H, W, 3]; m can lag n by up to 3 frames (a latent is painted once its 4 frames have arrived)."""
        import numpy as np
        self.k += 1
        paths = {}
        for hint, frames in controls.items():
            paths[hint] = str(self.dir / f"in_{stream}_{self.k:05d}_{hint}.npy")
            np.save(paths[hint], np.ascontiguousarray(frames, np.uint8))
        try:
            reply = self._call(cmd="push", stream=stream, controls=paths, out=str(self.dir / f"out_{stream}_{self.k:05d}.npy"))
        finally:
            for p in paths.values():
                Path(p).unlink(missing_ok=True)
        self.last[stream] = reply
        if not reply["frames"]:
            out = np.zeros((0,) + controls[next(iter(controls))].shape[1:], np.uint8)
        else:
            out = np.load(reply["out"])
            Path(reply["out"]).unlink(missing_ok=True)
        self._check(stream, out, controls.get("blur"))
        return out

    def _check(self, stream, painted, blur):
        """Judge this push for mosaic and drift against the blur control; record every stream in check.json."""
        if self.check == "off":
            return
        from core.video_check import RunCheck
        rc = self.checks.setdefault(stream, RunCheck(None, stream))
        rc.feed(painted, blur)
        record = {name: c.record() for name, c in self.checks.items()}
        (self.dir / "check.json").write_text(json.dumps({"mode": self.check, "failed": any(r["failed"] for r in record.values()),
                                                         "streams": record}, indent=1))
        if rc.failed and self.check == "stop":
            raise RuntimeError(f"video check failed for {stream}: {rc.reason}; see {self.dir / 'check.json'}")

    def release(self):
        return self._call(cmd="release")

    def stats(self):
        return self._call(cmd="stats")

    def close(self):
        try:
            self._call(cmd="stop")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


# ---------------------------------------------------------------- worker side

class SharedWeights:
    """The one generator every stream paints with. `loader` builds it; drop() lets the memory go."""

    def __init__(self, loader):
        self.loader, self.gen, self.loads, self.load_s = loader, None, 0, 0.0

    def get(self):
        if self.gen is None:
            t = time.time()
            self.gen = self.loader()
            self.loads += 1
            self.load_s += time.time() - t
        return self.gen

    def drop(self):
        self.gen = None


def stream_class():
    """world_stream.Worker with its weights taken from a SharedWeights instead of loaded per stream.
    Built lazily so this module imports without world_stream on the path."""
    from core.world_stream import Worker

    class Stream(Worker):
        def __init__(self, shared):
            self.shared = shared
            self.gen = None

        def _load(self):
            self.gen = self.shared.get()

        def release(self):
            self.gen = None
            return {"released": True}

    return Stream


class FakeStream:
    """Stand-in for a Stream with no model: paints each frame as 0.6 blur + 0.4 edge, with the real latent lag."""

    def __init__(self, shared):
        self.shared, self.gen = shared, None

    def start(self, prompt, size, fps, weights, seed, window, sink, quantize, planned_frames, raw_prompt):
        self.width, self.height = (int(n) for n in size.split("x"))
        self.frames_in = self.frames_out = 0
        return {"hints": list(weights), "weights": weights, "text_tokens": len(prompt.split()), "formatted_prompt": prompt,
                "model": "fake (no model)", "checkpoint_id": None}

    def release(self):
        self.gen = None
        return {"released": True}

    def push(self, controls, out):
        import numpy as np
        self.gen = self.shared.get()
        new = {h: np.load(p) for h, p in controls.items()}
        if any(v.shape[1:3] != (self.height, self.width) for v in new.values()):
            raise ValueError(f"controls must be {self.width}x{self.height}")
        if not hasattr(self, "pending"):
            self.pending = np.zeros((0,) + new["blur"].shape[1:], np.uint8)
        mix = (0.6 * new["blur"].astype(np.float32) + 0.4 * new["edge"].astype(np.float32)).astype(np.uint8)
        self.pending = np.concatenate([self.pending, mix])
        self.frames_in += len(mix)
        ready = 1 + 4 * ((self.frames_in - 1) // 4) - self.frames_out   # latent 0 = frame 0, then 4 frames per latent
        frames, self.pending = self.pending[:ready], self.pending[ready:]
        self.frames_out += len(frames)
        if len(frames):
            np.save(out, frames)
        return {"frames": len(frames), "out": out, "frames_out": self.frames_out, "latents": 1 + (self.frames_out - 1) // 4,
                "s_per_latent": 0.0, "peak_gb": 0.0}


class MultiWorker:
    def __init__(self, fake=False):
        self.fake = fake
        self.streams = {}
        self.shared = None
        self.quantize = None

    def hello(self, quantize=None):
        self.quantize = quantize
        if self.fake:
            self.shared = SharedWeights(lambda: object())
            self.make = FakeStream
            return {"fake": True, "model": "fake (no model)"}
        import mlx.core as mx
        from core import world_transfer as wt
        from core import world_transfer_multi as wm
        mx.set_default_device(mx.gpu)
        self.mx = mx
        self.shared = SharedWeights(lambda: wm.MultiGenerator(wt.shard_arrays(wt.MODEL_DIR), bits=quantize))
        self.make = stream_class()
        cfg = json.loads((wt.MODEL_DIR / "config.json").read_text())["cosmos3_nano_sim_bimanual"]
        return {"fake": False, "model": wt.MODEL_DIR.name, "checkpoint_id": cfg.get("checkpoint_id"), "quantize": quantize}

    def open(self, stream, **kw):
        if stream in self.streams:
            raise ValueError(f"stream {stream!r} is already open")
        # Opening builds the stream's text cache from a fresh read of the weights. Never hold two copies at once.
        self.release()
        s = self.make(self.shared)
        info = s.start(quantize=self.quantize, **kw)
        self.streams[stream] = s
        return {"stream": stream, **info}

    def push(self, stream, controls, out):
        if stream not in self.streams:
            raise KeyError(f"no stream {stream!r}; open it first")
        reply = self.streams[stream].push(controls, out)
        return {"stream": stream, "weight_loads": self.shared.loads, **reply}

    def release(self):
        """Drop the shared weights. Every stream's reference must go too, or the memory stays held."""
        if self.shared is not None:
            self.shared.drop()
        for s in self.streams.values():
            s.release()
        import gc
        gc.collect()
        if getattr(self, "mx", None) is not None:
            self.mx.clear_cache()
        return {"released": True, "streams": list(self.streams)}

    def stats(self):
        return {"streams": {k: {"frames_out": getattr(s, "frames_out", 0), "latents": getattr(s, "n_painted", None)}
                            for k, s in self.streams.items()},
                "weight_loads": self.shared.loads if self.shared else 0,
                "weight_load_s": round(self.shared.load_s, 1) if self.shared else 0.0}


def serve(fake=False):
    worker = MultiWorker(fake=fake)
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


def dry_run(argv=None):
    """One latent through a real worker (or the fake one with --fake). 0 if it came back as one painted frame."""
    import argparse

    import numpy as np
    p = argparse.ArgumentParser(description="world_stream_multi dry run: one stream, one latent")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out", default=str(ROOT / "out" / "test_outputs" / "wm_dry_run" / time.strftime("%Y%m%d-%H%M%S")))
    p.add_argument("--quantize", type=int, choices=(4, 8), default=8)
    p.add_argument("--size", default="448x256")
    p.add_argument("--fake", action="store_true", help="the stand-in worker: no MLX, no weights (for the tests)")
    args = p.parse_args(argv)
    width, height = (int(n) for n in args.size.split("x"))
    started = time.time()
    wm = MultiWorldStream(out_dir=args.out, quantize=args.quantize, fake=args.fake)
    try:
        info = wm.open("dry", "A city street by day, seen at eye level.", size=args.size, fps=24, planned_frames=1)
        grey = np.full((1, height, width, 3), 128, np.uint8)
        frames = wm.push("dry", {hint: grey for hint in HINTS})
    finally:
        wm.close()
    sidecar = {"dry_run": "dry run, 1 chunk", **wm.hello, "quantize": args.quantize, "size": args.size,
               "weights": {h: 0.25 for h in HINTS}, "frames_in": 1, "frames_out": int(len(frames)),
               "frame_shape": list(frames.shape[1:]), "opened": info, "seconds": round(time.time() - started, 1)}
    (Path(args.out) / "dry_run.json").write_text(json.dumps(sidecar, indent=1))
    print(json.dumps({"done": str(Path(args.out) / "dry_run.json"), "frames_out": sidecar["frames_out"],
                      "seconds": sidecar["seconds"]}), flush=True)
    return 0 if len(frames) == 1 else 1


if __name__ == "__main__":
    if "--worker" in sys.argv:
        serve(fake="--fake" in sys.argv)
    elif "--dry-run" in sys.argv or DRY_RUN:
        sys.exit(dry_run(sys.argv[1:]))
    else:
        print(__doc__)
