"""Catch a painted world-model video going wrong: mosaic (the picture breaks into coloured 16 px tiles) and drift (the
picture stops following the sim it was painted from). CPU only, numpy and OpenCV, no model.

Mosaic. The breakage seen in the Mara and Iris lunch films is saturated colour blobs laid on the latent tile grid
(the VAE's 8x downsample times the 2x2 patch = 16 px). Two cheap measures each rise with it, and each also rises on
some clean frames (a regular paving pattern repeats near 16 px; a sunny garden is colourful). Their geometric mean
rises on both only when the frame is really tiled:
  * blob contrast: mean absolute Laplacian of the saturation map at 1/4 size (the score out/world_stream/still_test.py
    used), divided by BLOB_REF;
  * grid periodicity: luma gradient averaged per column (and per row) phase modulo 16, coefficient of variation of
    those 16 means, divided by GRID_REF. Phase-free on purpose: the tiles' edges sit at x = 8 mod 16 in these films.
  mosaic = sqrt(blob/BLOB_REF * grid/GRID_REF); 1.0 is the threshold.

Drift. Correlation between the painted frame's luma and the blur control it was painted from, both blurred and cut to
1/8 size, so only the layout (where the bright and dark masses are) counts. A frame from an unrelated moment of the
same walk scores about 0.0-0.35 against the control; painted frames that follow the sim score 0.45-0.8. Edge-vs-edge
agreement was tried first (the plan's candidate) and separated worse: the edge control is full of sim-only texture
(paving grid lines) that a good painting rightly leaves out. See docs/fable_log/P3-D.md for the numbers.

Why the older drift number read 0.99 on garbage: kokopelli/loop/drift.py compared the painted frame with the mock sim's grid
picture, which shares no layout with any painting, so the distance sat near its ceiling for good and broken frames
alike. A drift measure is only as good as the reference it compares with; here it is the frame's own control.

    python -m kokopelli.wm.video_check film.mp4 --control blur.mp4          # per-second scores and a verdict
    python -m kokopelli.wm.video_check calibrate                            # the labelled clips -> out/test_outputs/video_check/
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TILE = 16
BLOB_REF = 25.0
GRID_REF = 0.08
MOSAIC_MAX = 1.0
DRIFT_MIN = 0.2
WINDOW = 24          # frames per verdict when scoring a file; one lunch push is 24 frames
MIN_FRAMES = 8       # a push with fewer painted frames is not judged
BAD_IN_A_ROW = 3


def blob_contrast(frame):
    f = frame.astype(np.float32)
    top = f.max(2)
    sat = (top - f.min(2)) / (top + 1)
    h, w = sat.shape
    small = cv2.resize(sat, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    return float(np.abs(cv2.Laplacian(small, cv2.CV_32F)).mean() * 100)


def grid_periodicity(gray):
    dx = np.abs(np.diff(gray, axis=1)).mean(0)
    dy = np.abs(np.diff(gray, axis=0)).mean(1)
    cv = []
    for d in (dx, dy):
        phases = np.array([d[k::TILE].mean() for k in range(TILE)])
        cv.append(phases.std() / (phases.mean() + 1e-6))
    return float(np.mean(cv))


def _layout(gray):
    h, w = gray.shape
    s = cv2.resize(cv2.GaussianBlur(gray, (0, 0), 3), (max(w // 8, 1), max(h // 8, 1)), interpolation=cv2.INTER_AREA)
    s = s - s.mean()
    return s / (np.linalg.norm(s) + 1e-6)


def _gray(frame):
    return cv2.cvtColor(np.ascontiguousarray(frame, np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)


def frame_scores(frame, blur_control=None):
    """frame, blur_control: uint8 [H, W, 3] RGB at the painted size. Returns {"mosaic", "drift"}; drift is None
    without a control. drift is a correlation: higher means the painting follows the sim more closely."""
    gray = _gray(frame)
    mosaic = float(np.sqrt(max(blob_contrast(frame), 0) / BLOB_REF * grid_periodicity(gray) / GRID_REF))
    drift = None
    if blur_control is not None:
        drift = float((_layout(gray) * _layout(_gray(blur_control))).sum())
    return {"mosaic": mosaic, "drift": drift}


def judge(scores):
    """Median of a window's per-frame scores, and why it is bad (empty list when it is fine)."""
    mosaic = float(np.median([s["mosaic"] for s in scores]))
    drifts = [s["drift"] for s in scores if s["drift"] is not None]
    drift = float(np.median(drifts)) if drifts else None
    reasons = []
    if mosaic > MOSAIC_MAX:
        reasons.append(f"mosaic {mosaic:.2f} > {MOSAIC_MAX}")
    if drift is not None and drift < DRIFT_MIN:
        reasons.append(f"drift: layout agreement with the control {drift:.2f} < {DRIFT_MIN}")
    return {"mosaic": round(mosaic, 3), "drift": None if drift is None else round(drift, 3), "bad": reasons}


class RunCheck:
    """Watches one stream's pushes. feed() aligns painted frames with the blur control frames they were painted from
    (painting lags the controls by up to 3 frames), judges each push and, given a path, writes it there as JSON. After BAD_IN_A_ROW
    bad pushes in a row `failed` turns true and stays true."""

    def __init__(self, path=None, stream="", stride=2):
        self.path, self.stream, self.stride = path and Path(path), stream, stride
        self.waiting = []          # blur control frames not yet matched with a painted frame
        self.frames = 0
        self.pushes, self.in_a_row, self.failed, self.reason = [], 0, False, None

    def feed(self, painted, blur=None):
        if blur is not None:
            self.waiting.extend(blur)
        controls = [None] * len(painted)
        if blur is not None:
            controls, self.waiting = self.waiting[:len(painted)], self.waiting[len(painted):]
        start, self.frames = self.frames, self.frames + len(painted)
        if len(painted) < MIN_FRAMES:
            return None
        picks = range(0, len(painted), self.stride)
        verdict = {"frames": [start, self.frames], **judge([frame_scores(painted[i], controls[i]) for i in picks])}
        self.pushes.append(verdict)
        self.in_a_row = self.in_a_row + 1 if verdict["bad"] else 0
        if self.in_a_row >= BAD_IN_A_ROW and not self.failed:
            self.failed = True
            self.reason = f"{BAD_IN_A_ROW} bad pushes in a row, last at frames {verdict['frames']}: " + "; ".join(verdict["bad"])
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.record(), indent=1))
        return verdict

    def record(self):
        thresholds = {"mosaic_max": MOSAIC_MAX, "drift_min": DRIFT_MIN, "bad_in_a_row": BAD_IN_A_ROW}
        return {"stream": self.stream, "failed": self.failed, "reason": self.reason, "thresholds": thresholds,
                "pushes": self.pushes}


# ---------------------------------------------------------------- files

def probe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def read_frames(path, size=None, crop=None, batch=16):
    """Yield uint8 [n<=batch, H, W, 3] batches from ffmpeg, so a clip is never held whole. crop is ffmpeg's w:h:x:y."""
    w, h = size or probe_size(path)
    if crop:
        w, h = (int(n) for n in crop.split(":")[:2])
    vf = [f"crop={crop}"] if crop else []
    if size:
        vf.append(f"scale={w}:{h}")
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)] + (["-vf", ",".join(vf)] if vf else []) + \
          ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    one = w * h * 3
    try:
        while True:
            raw = proc.stdout.read(one * batch)  # pyright: ignore[reportOptionalMemberAccess]  # stdout=PIPE
            n = len(raw) // one
            if n:
                yield np.frombuffer(raw[:n * one], np.uint8).reshape(n, h, w, 3)
            if n < batch:
                break
    finally:
        proc.stdout.close()  # pyright: ignore[reportOptionalMemberAccess]  # stdout=PIPE
        proc.kill()
        proc.wait()


def score_video(path, control=None, crop=None, stride=1):
    """Per-frame scores of a painted video, optionally against its blur control (resized to the painted size).
    Both files are read in small batches side by side."""
    w, h = (int(n) for n in crop.split(":")[:2]) if crop else probe_size(path)
    ctl = read_frames(control, size=(w, h)) if control else None
    waiting, rows, i = np.zeros((0, h, w, 3), np.uint8), [], 0
    for batch in read_frames(path, crop=crop):
        while ctl is not None and len(waiting) < len(batch):
            more = next(ctl, None)
            if more is None:
                break
            waiting = np.concatenate([waiting, more])
        for k, frame in enumerate(batch):
            if (i + k) % stride == 0:
                rows.append({"frame": i + k, **frame_scores(frame, waiting[k] if k < len(waiting) else None)})
        waiting = waiting[len(batch):]
        i += len(batch)
    return rows


def windows(rows, fps, window=WINDOW):
    """Judge consecutive windows of `window` frames, the way the push hook judges pushes."""
    out = []
    for start in range(0, rows[-1]["frame"] + 1 if rows else 0, window):
        chunk = [r for r in rows if start <= r["frame"] < start + window]
        if chunk:
            out.append({"t": round(start / fps, 2), **judge(chunk)})
    return out


# ---------------------------------------------------------------- calibration

DEMO = "out/bodies/demo/runs/wm"
BRIDGE = "out/city_wm/bridge/controls/832x480/blur.mp4"
# (name, painted, blur control or None, fps, crop, labelled segments in seconds: (start, end, expected verdict)).
# Labels come from contact sheets of each clip, read by eye before the thresholds were set (docs/fable_log/P3-D.md).
CLIPS = [
    ("iris", f"{DEMO}/film/iris.mp4", f"{DEMO}/controls/iris/blur.mp4", 16, None, [(0, 46, "good"), (58, 120, "bad")]),
    ("mara", f"{DEMO}/film/mara.mp4", f"{DEMO}/controls/mara/blur.mp4", 16, None,
     [(0, 8.5, "drift"), (9, 50, "good"), (64, 71, "bad"), (98, 108, "bad")]),
    ("a4_full_8bit", "out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4", BRIDGE, 30, None, [(0, 5, "good")]),
    ("a4_full", "out/wm_multicontrol/a4_full/a4_full.mp4", BRIDGE, 30, None, [(0, 5, "good")]),
    ("a4_blind_left", "out/wm_multicontrol/a4_8bit_blind/side_by_side.mp4", BRIDGE, 30, "832:480:0:0", [(0, 5, "good")]),
    ("a4_blind_right", "out/wm_multicontrol/a4_8bit_blind/side_by_side.mp4", BRIDGE, 30, "832:480:848:0", [(0, 5, "good")]),
    ("still_8bit", "out/world_stream/still_test/still_8bit.mp4", None, 16, None, [(0, 13, "good"), (14, 15.1, "bad")]),
    ("still_bf16", "out/world_stream/still_test/still_bf16.mp4", None, 16, None, [(0, 13, "good"), (14, 15.1, "bad")]),
    ("sway_8bit", "out/world_stream/still_test/sway_8bit.mp4", None, 16, None, [(0, 15.1, "good")]),
]


def first_failure(wins):
    """The first window that ends a run of BAD_IN_A_ROW bad windows (what stops a live run), or None."""
    run = 0
    for w in wins:
        run = run + 1 if w["bad"] else 0
        if run >= BAD_IN_A_ROW:
            return w
    return None


def check_file(path, control=None, fps=16, stride=2):
    """Score a finished video the way the push hook judges a live one. Returns (failure window or None, windows)."""
    wins = windows(score_video(path, control, stride=stride), fps)
    return first_failure(wins), wins


def classify(wins, start, end):
    """What the push hook would conclude on this stretch: 'good', or the kind of failure after BAD_IN_A_ROW bad
    windows in a row ('bad' for mosaic, 'drift' for drift alone)."""
    w = first_failure([w for w in wins if start <= w["t"] and w["t"] + 0.5 < end])
    if w is None:
        return "good"
    return "bad" if any(r.startswith("mosaic") for r in w["bad"]) else "drift"


def old_drift(painted, control, crop=None, every=WINDOW):
    """kokopelli/loop/drift.py's score (0 = same, 1 = unrelated) on every `every`-th frame, against the blur control (the
    closest thing to the sim frame it compared with). Kept for contrast only."""
    from PIL import Image

    from kokopelli.loop.drift import LAYOUT_WEIGHT, SMALL, appearance_distance, layout_distance
    w, h = (int(n) for n in crop.split(":")[:2]) if crop else probe_size(painted)
    small = lambda x: np.asarray(Image.fromarray(x).convert("L").resize(SMALL, Image.BILINEAR), np.float64)  # noqa: E731  # pyright: ignore[reportAttributeAccessIssue]  # Pillow keeps Image.BILINEAR
    out, i = [], 0
    for a, b in zip(read_frames(painted, crop=crop), read_frames(control, size=(w, h)), strict=False):
        for k in range(min(len(a), len(b))):
            if (i + k) % every == 0:
                x, y = small(a[k]), small(b[k])
                out.append(round(LAYOUT_WEIGHT * layout_distance(x, y) + (1 - LAYOUT_WEIGHT) * appearance_distance(x, y), 3))
        i += len(a)
    return out


def svg_curve(name, wins, segments, fps_label):
    """Two stacked panels (mosaic, drift), one series each, threshold drawn as a dashed rule; labelled stretches shaded."""
    W, H, L, R, T, gap = 720, 150, 48, 12, 22, 34
    end = max(w["t"] for w in wins) + 1e-6
    x = lambda t: L + (W - L - R) * t / end  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{T + 2 * H + gap + 30}" font-family="system-ui" '
             f'font-size="11"><rect width="100%" height="100%" fill="#fcfcfb"/>',
             f'<text x="{L}" y="14" fill="#0b0b0b" font-size="13">{name}: score per {WINDOW}-frame window ({fps_label})</text>']
    panels = [("mosaic", 0.0, 2.0, MOSAIC_MAX, "above the line = mosaic"), ("drift", -1.0, 1.0, DRIFT_MIN, "below the line = drift")]
    for p, (key, lo, hi, line, note) in enumerate(panels):
        top = T + p * (H + gap)
        y = lambda v, top=top, lo=lo, hi=hi: top + H - H * (min(max(v, lo), hi) - lo) / (hi - lo)  # noqa: E731
        for s, e, lab in segments:
            fill = "#e8e7e3" if lab == "good" else "#d9d8d2"
            parts.append(f'<rect x="{x(s):.1f}" y="{top}" width="{x(min(e, end)) - x(s):.1f}" height="{H}" fill="{fill}"/>')
            parts.append(f'<text x="{x(s) + 2:.1f}" y="{top + 11}" fill="#52514e">{lab}</text>') if p == 0 else None
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(line):.1f}" y2="{y(line):.1f}" stroke="#52514e" stroke-dasharray="4 3"/>')
        parts.append(f'<text x="{W - R}" y="{y(line) - 3:.1f}" fill="#52514e" text-anchor="end">{key} {line} ({note})</text>')
        for v in (lo, hi):
            parts.append(f'<text x="{L - 6}" y="{y(v) + 4:.1f}" fill="#52514e" text-anchor="end">{v:g}</text>')
        pts = [(x(w["t"]), y(w[key])) for w in wins if w[key] is not None]
        if pts:
            parts.append('<polyline fill="none" stroke="#2a78d6" stroke-width="2" points="' +
                         " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '"/>')
        else:
            parts.append(f'<text x="{L + 8}" y="{top + H / 2}" fill="#52514e">no control for this clip</text>')
    base = T + 2 * H + gap + 16
    for t in range(0, int(end) + 1, max(int(end) // 8, 1)):
        parts.append(f'<text x="{x(t):.1f}" y="{base}" fill="#52514e" text-anchor="middle">{t}s</text>')
    return "\n".join(parts + ["</svg>"])


def calibrate(out_dir):
    import time
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report, ok = {"thresholds": {"mosaic_max": MOSAIC_MAX, "drift_min": DRIFT_MIN, "window": WINDOW,
                                 "bad_in_a_row": BAD_IN_A_ROW}, "clips": {}}, True
    for name, painted, control, fps, crop, segments in CLIPS:
        if not (ROOT / painted).exists():
            report["clips"][name] = {"missing": painted}
            print(f"{name:15} MISSING {painted}")
            continue
        t = time.process_time()
        rows = score_video(ROOT / painted, control and ROOT / control, crop=crop)
        cpu = time.process_time() - t
        wins = windows(rows, fps)
        results = []
        for s, e, lab in segments:
            got = classify(wins, s, e)
            results.append({"seconds": [s, e], "label": lab, "verdict": got, "correct": got == lab})
            ok &= got == lab
        old = old_drift(ROOT / painted, ROOT / control, crop) if control else []
        report["clips"][name] = {"frames": len(rows), "cpu_s_per_100_frames": round(100 * cpu / max(len(rows), 1), 3),
                                 "segments": results, "windows": wins, "old_drift_per_window": old,
                                 "old_drift_range": [min(old), max(old)] if old else None}
        (out_dir / f"{name}.svg").write_text(svg_curve(name, wins, segments, f"{fps} fps"))
        print(f"{name:15} {len(rows):5} frames {100 * cpu / max(len(rows), 1):.2f} cpu-s/100  " +
              "  ".join(f"{r['seconds']}:{r['label']}->{r['verdict']}" for r in results))
    report["all_correct"] = bool(ok)
    (out_dir / "calibration.json").write_text(json.dumps(report, indent=1))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="a painted video, or 'calibrate'")
    parser.add_argument("--control", help="the blur control video it was painted from (enables the drift check)")
    parser.add_argument("--fps", type=float, default=16)
    parser.add_argument("--crop", help="ffmpeg crop w:h:x:y, for one panel of a side-by-side")
    parser.add_argument("--out", default=str(ROOT / "out/test_outputs/video_check"))
    args = parser.parse_args(argv)
    if args.video == "calibrate":
        return 0 if calibrate(args.out)["all_correct"] else 1
    wins = windows(score_video(args.video, args.control, crop=args.crop), args.fps)
    for w in wins:
        print(f"{w['t']:7.1f}s mosaic {w['mosaic']:.2f} drift {w['drift'] if w['drift'] is not None else '-':>6} "
              + ("BAD: " + "; ".join(w["bad"]) if w["bad"] else ""))
    failed = first_failure(wins)
    print(f"FAILED at {failed['t']}s ({BAD_IN_A_ROW} bad windows in a row)" if failed else "passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
