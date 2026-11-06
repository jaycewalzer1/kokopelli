"""Cosmos3-Nano (MLX, base model) repainting test_clip from the sim's depth, through world_filter.py. Experiment 1.

    .venv/bin/python filter_test/scripts/run_cosmos.py            # all 300 frames, about an hour
    .venv/bin/python filter_test/scripts/run_cosmos.py --chunks 1 # one chunk, a smoke test

Stands in for Cosmos3-Nano-Sim-Transfer, which needs an NVIDIA GPU. world_filter.py is the edge-control runner; its system prompt
already names depth as a control, so the depth video goes in where the edges would. Same command as world_model.filter_video,
run here directly so each chunk's time and memory can be logged. Settings: 448x256, chunks of 16 frames carrying 5 into the
next (11 new each), 30 steps, guidance 3 and control guidance 1.5 (NVIDIA's edge example; Sim-Transfer itself is distilled to
4 steps, which the base model isn't). world_filter.py writes 24 fps; the result is re-timed to the clip's 30 fps.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from settings import WORLD_MODEL_RUNNER, WORLD_MODEL_WEIGHTS  # noqa: E402

CONTROL = ROOT / "out" / "filter_test" / "controls" / "cosmos_simdepth.mp4"
OUT = ROOT / "out" / "filter_test" / "cosmos_simdepth"
PROMPT = (ROOT / "filter_test" / "prompt.txt").read_text().strip()
SIZE, FRAMES, COND, STEPS, SEED = "448x256", 16, 5, 30, 7


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", type=int)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    painted = OUT / "painted_24fps.mp4"
    command = [str(WORLD_MODEL_RUNNER / ".venv" / "bin" / "python"), str(ROOT / "world_filter.py"), PROMPT, "--control", str(CONTROL),
               "--output", str(painted), "--model-dir", str(WORLD_MODEL_WEIGHTS), "--size", SIZE, "--frames", str(FRAMES),
               "--cond-frames", str(COND), "--steps", str(STEPS), "--seed", str(SEED)] + (["--chunks", str(args.chunks)] if args.chunks else [])
    started, chunks = time.time(), []
    with subprocess.Popen(command, cwd=WORLD_MODEL_RUNNER, stdout=subprocess.PIPE, text=True,
                          env={**os.environ, "PYTHONPATH": str(WORLD_MODEL_RUNNER)}) as process:
        for line in process.stdout:
            if line.startswith("{"):
                chunks.append(json.loads(line))
                print(line.strip(), flush=True)
    if process.returncode:
        raise SystemExit(f"world_filter.py exited {process.returncode}")
    total = time.time() - started
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-r", "30", "-i", str(painted), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "16", "-r", "30", str(OUT / "output.mp4")], check=True)
    painted.unlink()
    frames = chunks[-1]["frames"]
    stats = {"frames": frames, "chunks": len(chunks), "total_s": round(total, 1), "first_chunk_s": chunks[0]["seconds"],
             "time_to_first_frame_s": round(chunks[0]["seconds"], 1), "output_fps": round(frames / total, 3),
             "peak_gb": max(chunk["peak_gb"] for chunk in chunks), "size": SIZE, "steps": STEPS, "seed": SEED, "prompt": PROMPT,
             "weights": str(WORLD_MODEL_WEIGHTS), "per_chunk": chunks}
    (OUT / "stats.json").write_text(json.dumps(stats, indent=1))
    (OUT / "run.json").write_text(json.dumps({"model": "cosmos", "about": "Cosmos3-Nano (MLX) repainting the sim from its own depth.",
                                              "lines": [f"{frames} frames at {SIZE}, {len(chunks)} chunks of {FRAMES}",
                                                        f"took {total / 60:.0f} min, peak {stats['peak_gb']} GB"]}))
    print(json.dumps({k: v for k, v in stats.items() if k != "per_chunk"}))


if __name__ == "__main__":
    main()
