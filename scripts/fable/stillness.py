"""P3-C: does mosaic follow stillness or elapsed time? Builds the two control sets that test it, from the bridge
controls that set A (out/wm_multicontrol/a4_full_8bit, 150 moving frames) was painted from. CPU only, no model.

  A  moving 150 frames                  frame i = source i              (exists, painted: a4_full_8bit)
  B  still from frame 0                 frame i = source 60             (frame 60 repeated 150x)
  C  moving 60, then still 90           frame i = source min(i, 60)     (moves through frame 60, then holds it)

C holds the same frame B holds, so B and C differ only in whether the camera moved first. ffmpeg does the frame
selection and re-encodes with the bridge controls' own settings (libx264, yuv420p, CRF 10, 30 fps), streaming, so
nothing is held whole. That re-encode is one generation more than A's controls had; `verify` measures what it costs.

    python3 ops/memguard.py run --name fable_p3c_build --gb 4 -- .venv/bin/python scripts/fable/stillness.py build
    python3 ops/memguard.py run --name fable_p3c_verify --gb 4 -- .venv/bin/python scripts/fable/stillness.py verify
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.video_check import read_frames  # noqa: E402

SRC = Path("out/city_wm/bridge/controls/832x480")
OUT = Path("out/wm_multicontrol")
HINTS = ("blur", "seg", "depth", "edge")
FRAMES, HOLD, FPS = 150, 60, 30
ENCODE = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", "-r", str(FPS)]
SETS = {
    "B": {"what": f"still from frame 0: source frame {HOLD} repeated {FRAMES}x",
          "vf": f"select=eq(n\\,{HOLD}),loop=loop={FRAMES - 1}:size=1:start=0,setpts=N/({FPS}*TB)"},
    "C": {"what": f"moving {HOLD} then still {FRAMES - HOLD}: source frames 0-{HOLD}, then frame {HOLD} held "
                  f"(frame i = source min(i, {HOLD}))",
          "vf": f"trim=end_frame={HOLD + 1},setpts=N/({FPS}*TB),tpad=stop_mode=clone:stop={FRAMES - HOLD - 1}"},
}


def source_index(name, i):
    return HOLD if name == "B" else min(i, HOLD)


def controls_dir(name):
    return OUT / f"fable_still_{name}" / "controls"


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


def build(names):
    for name in names:
        d = controls_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        for hint in HINTS:
            dst = d / f"{hint}.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(SRC / f"{hint}.mp4"), "-vf", SETS[name]["vf"],
                            "-frames:v", str(FRAMES), *ENCODE, str(dst)], check=True)
            print(f"{name} {hint}: {dst}")
        (d / "controls.json").write_text(json.dumps({
            "set": name, "what": SETS[name]["what"], "source": str(SRC), "source_manifest": str(SRC.parent / "controls.json"),
            "frames": FRAMES, "hold_frame": HOLD, "fps": FPS, "size": "832x480", "hints": list(HINTS),
            "ffmpeg_vf": SETS[name]["vf"], "encoding": " ".join(ENCODE),
            "painted_with": "Variant A (world_transfer_multi.py, Cosmos3-Nano-Sim-Transfer), 4 controls at 0.25, "
                            "8-bit weights, 832x480, seed 2025, A's caption: scripts/fable/stillness_queue.sh",
            "built_by": "scripts/fable/stillness.py build"}, indent=1) + "\n")


def held_frame(path):
    return next(read_frames(path, batch=HOLD + 1))[HOLD]


def verify(names):
    """Same stream format and frame count as A's controls, and every frame is the source frame it should be: mean
    absolute difference (0-255) against that source frame, next to the smallest frame-to-frame step of the source (what
    an off-by-one would cost). The re-encode alone should stay well under that step."""
    report, ok = {}, True
    for name in names:
        for hint in HINTS:
            a, b = SRC / f"{hint}.mp4", controls_dir(name) / f"{hint}.mp4"
            pa, pb = probe(a), probe(b)
            same = all(pa[k] == pb[k] for k in ("codec_name", "width", "height", "pix_fmt", "r_frame_rate", "nb_read_frames"))
            hold = held_frame(a).astype(np.int16)
            src = (f for batch in read_frames(a) for f in batch)
            diffs, step, last = [], [], None
            for i, frame in enumerate(f for batch in read_frames(b) for f in batch):
                s = next(src).astype(np.int16)
                if last is not None and i <= HOLD:
                    step.append(float(np.abs(s - last).mean()))  # how much the source moves per frame up to the hold
                last = s
                want = hold if source_index(name, i) == HOLD else s
                diffs.append(float(np.abs(frame.astype(np.int16) - want).mean()))
            good = same and len(diffs) == FRAMES and max(diffs) < 1.5
            ok &= good
            report[f"{name}/{hint}"] = {"ok": good, "same_format_and_count_as_A": same, "frames": pb["nb_read_frames"],
                                        "size": f"{pb['width']}x{pb['height']}", "pix_fmt": pb["pix_fmt"], "fps": pb["r_frame_rate"],
                                        "mad_vs_source_mean": round(float(np.mean(diffs)), 3),
                                        "mad_vs_source_max": round(max(diffs), 3),
                                        "source_step_mad_min": round(min(step), 3)}
            print(f"{name}/{hint}: {'ok ' if good else 'BAD'} {pb['nb_read_frames']} frames {pb['width']}x{pb['height']} "
                  f"{pb['pix_fmt']} {pb['r_frame_rate']} (A: {pa['nb_read_frames']} {pa['width']}x{pa['height']}) "
                  f"MAD vs source mean {np.mean(diffs):.3f} max {max(diffs):.3f}; source frame-to-frame step min {min(step):.3f}")
    for name in names:
        (controls_dir(name) / "verify.json").write_text(json.dumps(
            {k: v for k, v in report.items() if k.startswith(name + "/")}, indent=1) + "\n")
    return ok


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=("build", "verify", "all"))
    p.add_argument("--sets", default="BC")
    a = p.parse_args(argv)
    names = [n for n in a.sets if n in SETS]
    if a.what in ("build", "all"):
        build(names)
    if a.what in ("verify", "all"):
        return 0 if verify(names) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
