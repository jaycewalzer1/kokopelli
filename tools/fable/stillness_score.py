"""P3-C: score the three stillness paints per frame with kokopelli/wm/video_check.py and find where each crosses threshold.

  A  moving 150 frames            out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4   vs the bridge blur control
  B  still from frame 0           out/wm_multicontrol/fable_still_B/fable_still_B.mp4 vs its own blur control
  C  moving 60, then still 90     out/wm_multicontrol/fable_still_C/fable_still_C.mp4 vs its own blur control

Per frame: mosaic (threshold MOSAIC_MAX, higher is worse) and drift (layout correlation with the blur control,
threshold DRIFT_MIN, lower is worse). Crossing frame: the first frame from which the median of the next RUN frames is
past threshold, so one odd frame doesn't count; first_frame_over is the first single frame past it. Also the push
hook's own verdict (24-frame windows, 3 bad in a row). Writes stillness.json (curves, crossings, suggested reading),
stillness.csv and stillness.svg (curves) to --out. CPU only, reads in small batches.

    python3 kokopelli/ops/memguard.py run --name fable_p3c_score --gb 2 -- .venv/bin/python -m tools.fable.stillness_score
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
from kokopelli.wm import video_check as vc  # noqa: E402

W = "out/wm_multicontrol"
SETS = {
    "A": (f"{W}/a4_full_8bit/a4_full_8bit.mp4", "out/city_wm/bridge/controls/832x480/blur.mp4", "moving 150 frames"),
    "B": (f"{W}/fable_still_B/fable_still_B.mp4", f"{W}/fable_still_B/controls/blur.mp4", "still from frame 0 (frame 60 held)"),
    "C": (f"{W}/fable_still_C/fable_still_C.mp4", f"{W}/fable_still_C/controls/blur.mp4", "moving to frame 60, then still"),
}
STILL_FROM = {"A": None, "B": 0, "C": 60}
RUN = 8          # frames a crossing must hold (video_check.MIN_FRAMES: a push shorter than this isn't judged)
TOL = 12         # frames (3 latent chunks) within which two crossings count as "the same frame"
FPS = 30


def crossing(values, past, run=RUN):
    """First frame i where the median of values[i:i+run] is past threshold, and the first single frame past it."""
    v = np.array([np.nan if x is None else x for x in values], float)
    first = next((i for i, x in enumerate(v) if past(x)), None)
    held = next((i for i in range(len(v) - run + 1) if past(np.nanmedian(v[i:i + run]))), None)
    return held, first


def score(name, painted, control):
    rows = vc.score_video(painted, control)
    mosaic, drift = [r["mosaic"] for r in rows], [r["drift"] for r in rows]
    m_cross, m_first = crossing(mosaic, lambda x: x > vc.MOSAIC_MAX)
    d_cross, d_first = crossing(drift, lambda x: x < vc.DRIFT_MIN)
    fail = vc.first_failure(vc.windows(rows, FPS))
    still = STILL_FROM[name]
    return {"painted": painted, "control": control, "frames": len(rows), "still_from": still,
            "mosaic_cross": m_cross, "mosaic_first_frame_over": m_first,
            "mosaic_cross_after_still": None if m_cross is None or still is None else m_cross - still,
            "drift_cross": d_cross, "drift_first_frame_under": d_first,
            "push_hook_failure_at_s": None if fail is None else fail["t"],
            "mosaic_max": round(max(mosaic), 3), "mosaic_median": round(float(np.median(mosaic)), 3),
            "mosaic": [round(x, 4) for x in mosaic], "drift": [None if x is None else round(x, 4) for x in drift]}


def reading(res):
    """A mechanical first reading from the mosaic crossings; the conclusion in docs/MOSAIC.md is made by looking at the
    curves and the films too. stillness: mosaic starts a fixed time after the camera stops (B early, C about that long
    after frame 60). elapsed time: B and C break at the same frame, and so does A. both: B and C break at the same frame
    but the moving A doesn't."""
    if not all(k in res for k in "ABC"):
        return "inconclusive", "not all three sets were scored"
    a, b, c = (res[k]["mosaic_cross"] for k in "ABC")
    if b is None and c is None:
        return "inconclusive", f"neither B nor C crossed mosaic {vc.MOSAIC_MAX} in {res['B']['frames']} frames (A: {a})"
    if b is not None and c is not None:
        if abs((c - 60) - b) <= TOL and abs(c - b) > TOL:
            return "stillness", f"B crossed at {b}, C at {c} = {c - 60} frames after it stopped (A: {a})"
        if abs(c - b) <= TOL:
            return ("elapsed time" if a is not None else "both"), f"B crossed at {b}, C at {c}, A at {a}"
    return "inconclusive", f"crossings A {a}, B {b}, C {c} fit no single reading within {TOL} frames"


def svg(res, path):
    w, h, pad = 900, 520, 50
    ph = (h - 3 * pad) / 2
    n = max(r["frames"] for r in res.values())
    colors = {"A": "#1f77b4", "B": "#d62728", "C": "#2ca02c"}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="12">',
           f'<rect width="{w}" height="{h}" fill="white"/>']
    for k, (key, lo, hi, thr, title) in enumerate((("mosaic", 0, None, vc.MOSAIC_MAX, "mosaic (higher is worse)"),
                                                    ("drift", -0.2, 1.0, vc.DRIFT_MIN, "drift: layout correlation (lower is worse)"))):
        top = pad + k * (ph + pad)
        vals = [x for r in res.values() for x in r[key] if x is not None]
        hi = hi if hi is not None else max(2 * thr, max(vals, default=thr) * 1.05)
        x = lambda i: pad + i * (w - 2 * pad) / max(n - 1, 1)  # noqa: E731
        y = lambda v, top=top, lo=lo, hi=hi: top + ph - (min(max(v, lo), hi) - lo) / (hi - lo) * ph  # noqa: E731
        out.append(f'<text x="{pad}" y="{top - 8}">{title}; dashed = threshold {thr}; grey = frame 60</text>')
        out.append(f'<rect x="{pad}" y="{top}" width="{w - 2 * pad}" height="{ph}" fill="none" stroke="#999"/>')
        out.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y(thr):.1f}" y2="{y(thr):.1f}" stroke="#000" stroke-dasharray="4 3"/>')
        out.append(f'<line x1="{x(60):.1f}" x2="{x(60):.1f}" y1="{top}" y2="{top + ph}" stroke="#bbb"/>')
        for name, r in res.items():
            pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(r[key]) if v is not None)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{colors.get(name, "#555")}" stroke-width="1.5"/>')
    for j, (name, r) in enumerate(res.items()):
        out.append(f'<text x="{pad + j * 260}" y="{h - 12}" fill="{colors.get(name, "#555")}">{name}: {SETS[name][2]}, '
                   f'mosaic cross {r["mosaic_cross"]}</text>')
    path.write_text("\n".join(out) + "\n</svg>\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sets", default="ABC")
    p.add_argument("--painted", action="append", default=[], metavar="SET=PATH", help="score another file as this set")
    p.add_argument("--out", default=f"{W}/fable_still_C/score")
    a = p.parse_args(argv)
    override = dict(s.split("=", 1) for s in a.painted)
    res, missing = {}, []
    for name in a.sets:
        painted, control, _ = SETS[name]
        painted = override.get(name, painted)
        if not Path(painted).exists():
            missing.append(painted)
            continue
        res[name] = score(name, painted, control)
        r = res[name]
        print(f"{name}: {r['frames']} frames, mosaic median {r['mosaic_median']} max {r['mosaic_max']}, "
              f"cross {r['mosaic_cross']} (first frame over {r['mosaic_first_frame_over']}), drift cross {r['drift_cross']}, "
              f"push hook {'fails at ' + str(r['push_hook_failure_at_s']) + ' s' if r['push_hook_failure_at_s'] is not None else 'passes'}")
    label, why = reading(res)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stillness.json").write_text(json.dumps({
        "thresholds": {"mosaic_max": vc.MOSAIC_MAX, "drift_min": vc.DRIFT_MIN, "run_frames": RUN, "tolerance_frames": TOL},
        "suggested_reading": label, "why": why, "missing": missing, "sets": res}, indent=1) + "\n")
    with open(out / "stillness.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["frame"] + [f"{n}_{k}" for n in res for k in ("mosaic", "drift")])
        for i in range(max((r["frames"] for r in res.values()), default=0)):
            wr.writerow([i] + [r[k][i] if i < r["frames"] else "" for r in res.values() for k in ("mosaic", "drift")])
    if res:
        svg(res, out / "stillness.svg")
    print(f"suggested reading: {label} ({why})" + (f"; missing: {', '.join(missing)}" if missing else ""))
    print(f"wrote {out}/stillness.json, .csv, .svg")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
