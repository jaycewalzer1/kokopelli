"""Check a finished run's video against its log, and rebuild it if asked. Exits non-zero if anything is wrong."""
import argparse
import subprocess
import sys
from pathlib import Path

from blend import FPS, probe
from runtime import replay
from runtime.frames import file_hash
from runtime.stitch import expected_frames, stitch


def _ffmpeg_log(path, video_filter):
    return subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", video_filter, "-f", "null", "-"],
                          check=True, capture_output=True, text=True).stderr


def scene_cuts(path, threshold=0.3):
    return _ffmpeg_log(path, f"select='gt(scene,{threshold})',showinfo").count("pts_time:")


def black_stretches(path):
    return _ffmpeg_log(path, "blackdetect=d=1.0").count("black_start:")


def frozen_stretches(path, seconds=5):
    return _ffmpeg_log(path, f"freezedetect=d={seconds}").count("freeze_start")


def check(run_dir, expect_seconds=None, rebuild=False):
    """Return (problems, facts). A problem means the video doesn't match the log. Facts are for a person to judge."""
    run_dir = Path(run_dir)
    summary = replay.summarize(run_dir)
    chunks = [chunk for tick in summary["ticks"] for chunk in tick["chunks"]]
    overlap = summary["run"]["run_start"]["config"]["cond_frames"]
    problems = []
    missing = [chunk["clip"] for chunk in chunks if not (run_dir / chunk["clip"]).exists()]
    if missing:
        problems.append(f"{len(missing)} clips in the log are missing, first {missing[0]}")
    changed = [chunk["clip"] for chunk in chunks if (run_dir / chunk["clip"]).exists() and file_hash(run_dir / chunk["clip"]) != chunk["hash"]]
    if changed:
        problems.append(f"{len(changed)} clips don't match their logged hash, first {changed[0]}")
    final = run_dir / "final.mp4"
    if rebuild and not missing:
        stitch([run_dir / chunk["clip"] for chunk in chunks], final, overlap)
    if not final.exists():
        problems.append("final.mp4 is missing; --rebuild makes it from the clips")
        return problems, {"ticks": len(summary["ticks"]), "clips": len(chunks)}
    width, height, frames = probe(final)
    wanted = expected_frames([chunk["frames"] for chunk in chunks], overlap)
    if frames != wanted:
        problems.append(f"final.mp4 has {frames} frames, the clips should join to {wanted}")
    seconds = frames / FPS
    if expect_seconds is not None and abs(seconds - expect_seconds) > 1:
        problems.append(f"final.mp4 is {seconds:.1f}s, expected {expect_seconds}s")
    facts = {"ticks": len(summary["ticks"]), "clips": len(chunks), "size": f"{width}x{height}", "frames": frames, "seconds": round(seconds, 1),
             "scene_cuts": scene_cuts(final), "reanchors": summary["run"]["totals"]["reanchors"],
             "black_stretches": black_stretches(final), "frozen_stretches": frozen_stretches(final)}
    return problems, facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expect-seconds", type=float, help="a full run is 1800")
    parser.add_argument("--rebuild", action="store_true", help="make final.mp4 again from the clips first")
    args = parser.parse_args()
    problems, facts = check(args.run, args.expect_seconds, args.rebuild)
    for key, value in facts.items():
        print(f"{key:18}{value}")
    for problem in problems:
        print(f"PROBLEM: {problem}")
    print("Scene cuts near re-anchors are expected on one-frame conditioning; judge them by eye." if not problems else "")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
