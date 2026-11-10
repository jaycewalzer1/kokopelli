"""P4-A: per-stage profile of closed-loop world-model pushes (KOKO_PROFILE=1).

Mirrors one lunch step: two streams (Variant A, four controls at 0.25, 8-bit), a 1-frame first push each, release the
weights (as the loop does while Qwen thinks), a 16-frame push each, then one 160-frame push on the first stream (the
size of a real closed-loop push). Controls are recorded, not live: Iris's 448x256 controls from the 2026-11-08 bodies demo
feed both streams, with different seeds. Writes <out>/profile.json and prints a table.

    env KOKO_PROFILE=1 .venv/bin/python scripts/fable/p4_profile.py --out out/fable/P4/profile [--fake] [--long 160]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

K = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(K))
CONTROLS = K / "out/bodies/demo/runs/wm/controls/iris"
HINTS = ("blur", "seg", "depth", "edge")
PROMPT = ("First-person view of someone walking through a sunny solarpunk village around midday, at eye level. "
          "Timber apartment buildings with planted balconies, vines and green roofs line paved streets.")


def read_frames(path, n, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", str(n), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    import numpy as np
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--size", default="448x256")
    p.add_argument("--quantize", type=int, default=8)
    p.add_argument("--short", type=int, default=16)
    p.add_argument("--long", type=int, default=160, help="0 skips the long push")
    p.add_argument("--fake", action="store_true", help="stand-in worker, no model (checks this script only)")
    a = p.parse_args()
    if os.environ.get("KOKO_PROFILE") != "1":
        sys.exit("set KOKO_PROFILE=1")
    dry = os.environ.get("KOKO_DRY_RUN") == "1"
    from core.world_stream_multi import MultiWorldStream
    w, h = (int(x) for x in a.size.split("x"))
    total = 1 + a.short + a.long
    t = time.perf_counter()
    ctl = {k: read_frames(CONTROLS / f"{k}.mp4", total, w, h) for k in HINTS}
    read_s = time.perf_counter() - t
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    started = time.perf_counter()
    wm = MultiWorldStream(out_dir=out / "wm", quantize=a.quantize, fake=a.fake)
    try:
        streams = ["mara"] if dry else ["mara", "iris"]
        for i, s in enumerate(streams):
            wm.open(s, PROMPT, size=a.size, fps=16, seed=2025 + i, window=24, planned_frames=total)

        def push(s, lo, hi, label):
            t = time.perf_counter()
            frames = wm.push(s, {k: ctl[k][lo:hi] for k in HINTS})
            wall = time.perf_counter() - t
            r = wm.last[s]
            worker = r.get("profile", {})
            client = r.get("client_profile", {})
            named = sum(worker.values()) + sum(v for k, v in client.items() if k != "client_call")
            rows.append({"push": label, "stream": s, "frames_in": hi - lo, "frames_out": len(frames),
                         "wall_s": round(wall, 3), "stage_sum_s": round(named, 3),
                         "unnamed_s": round(wall - named, 3), "worker": worker, "client": client,
                         "s_per_latent": r.get("s_per_latent"), "peak_gb": r.get("peak_gb"),
                         "weight_loads": r.get("weight_loads")})
            print(json.dumps(rows[-1]), flush=True)

        for s in streams:
            push(s, 0, 1, "first_1")
        if not dry:
            wm.release()
            for s in streams:
                push(s, 1, 1 + a.short, f"step_{a.short}")
            if a.long:
                wm.release()
                push("mara", 1 + a.short, total, f"step_{a.long}")
    finally:
        wm.close()
    side = {"what": "P4-A per-stage profile of closed-loop pushes (KOKO_PROFILE=1)",
            "model": "fake (no model)" if a.fake else "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer)",
            "variant": "A", "weights": {k: 0.25 for k in HINTS}, "quantize": a.quantize, "size": a.size,
            "lowered": f"size {a.size} (closed-loop size of the 2026-11-08 run), not 832x480",
            "controls": str(CONTROLS) + " (recorded, both streams)", "dry_run": dry,
            "controls_read_s": round(read_s, 2), "seconds": round(time.perf_counter() - started, 1),
            "hello": wm.hello, "pushes": rows}
    (out / "profile.json").write_text(json.dumps(side, indent=1))
    print(json.dumps({"done": str(out / "profile.json"), "seconds": side["seconds"]}))


if __name__ == "__main__":
    main()
