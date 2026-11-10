"""Estimate a full run from a real one: wall-clock, GPU-hours, storage, and what the fallbacks would give.

Only the base row is measured. The fallback rows assume render time grows with pixels x frames x steps, a rough rule
that a real run should replace.
"""
import argparse
import statistics
from pathlib import Path

from kokopelli.loop import replay
from kokopelli.loop.config import WM_PRESETS

GB = 1024 ** 3
FULL_TICKS = 60
GPUS_PER_RUN = 3  # SimWorld, Cosmos and Qwen, one each.
# Fallbacks in the order to try them. Each is a change to the preset the run used.
FALLBACKS = [("Lower resolution (448x256)", {"size": "448x256"}), ("Fewer steps (20)", {"steps": 20}),
             ("Lower frame rate (12 fps, half the frames)", {"frame_scale": 0.5}),
             ("Keyframes only (one 81-frame clip per tick)", {"chunk_frames": [81]})]


def work(preset):
    width, height = (int(n) for n in preset["size"].split("x"))
    frames = sum(preset["chunk_frames"]) * preset.get("frame_scale", 1)
    return width * height * frames * max(1, preset["steps"])


def measure(run_dir):
    """Median seconds per tick by stage, and bytes on disk per tick."""
    run_dir = Path(run_dir)
    ticks = replay.summarize(run_dir)
    done = ticks["ticks"]
    if not done:
        raise SystemExit(f"{run_dir} has no finished ticks to measure")
    stages = {stage: statistics.median(tick["timing"]["seconds"].get(stage, 0) for tick in done) for stage in done[0]["timing"]["seconds"]}
    tick_folders = [folder for folder in (run_dir / "ticks").iterdir() if folder.name != "0000"]
    size = sum(path.stat().st_size for folder in tick_folders for path in folder.iterdir())
    return {"ticks": len(done), "seconds": stages, "bytes_per_tick": size / len(tick_folders),
            "preset": ticks["run"]["run_start"]["config"]["wm_preset"], "peak_memory_gb": ticks["run"]["totals"]["peak_memory_gb"]}


def estimate(measured, ticks=FULL_TICKS, dollars_per_gpu_hour=0.0):
    base = WM_PRESETS[measured["preset"]]
    seconds = measured["seconds"]
    other = seconds["total"] - seconds["wm"]
    rows = []
    for name, change in [("As measured", {}), *FALLBACKS]:
        preset = {**base, **change}
        tick_seconds = other + seconds["wm"] * work(preset) / work(base)
        hours = tick_seconds * ticks / 3600
        # Video is most of what's stored, so storage follows the frames and pixels.
        storage_scale = work({**preset, "steps": 1}) / work({**base, "steps": 1})
        rows.append({"plan": name, "seconds_per_tick": round(tick_seconds, 1), "wall_hours": round(hours, 2), "gpu_hours": round(hours * GPUS_PER_RUN, 2),
                     "dollars": round(hours * GPUS_PER_RUN * dollars_per_gpu_hour, 2),
                     "storage_gb": round(measured["bytes_per_tick"] * storage_scale * ticks * 2 / GB, 2)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="a finished run to measure from")
    parser.add_argument("--ticks", type=int, default=FULL_TICKS)
    parser.add_argument("--dollars-per-gpu-hour", type=float, default=0.0)
    args = parser.parse_args()
    measured = measure(args.run)
    print(f"Measured from {measured['ticks']} ticks on preset {measured['preset']}. Peak RAM by stage: {measured['peak_memory_gb']}")
    print("Median seconds per tick: " + ", ".join(f"{stage} {value:.1f}" for stage, value in measured["seconds"].items()))
    print(f"\nFor {args.ticks} ticks (storage counts the clips twice, for the stitched video). Rows after the first are estimates:")
    print(f"{'plan':46}{'s/tick':>9}{'hours':>8}{'GPU-h':>8}{'$':>9}{'GB':>8}")
    for row in estimate(measured, args.ticks, args.dollars_per_gpu_hour):
        print(f"{row['plan']:46}{row['seconds_per_tick']:>9}{row['wall_hours']:>8}{row['gpu_hours']:>8}{row['dollars']:>9}{row['storage_gb']:>8}")


if __name__ == "__main__":
    main()
