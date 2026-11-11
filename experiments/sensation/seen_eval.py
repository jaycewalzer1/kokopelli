"""How well each detector backend of kokopelli/wm/seen.py confirms a sim candidate in frames Cosmos really painted.

    # CPU, no model: pick the frames, build the labels from the sim's segmentation, write audit sheets to look at
    .venv/bin/python -m experiments.sensation.seen_eval labels --out out/sensation/seen_eval/RUN
    # The detectors, one at a time, through the GPU queue only:
    python3 kokopelli/ops/gpu.py run --name sens_seen_eval --priority 42 --max-hours 0.35 --gb 6 --cwd "$PWD" \
        --about "Leak fix: precision, recall and latency of OWLv2, Grounding DINO tiny and Florence-2-base at confirming a sim person in Cosmos-painted frames of the bodies demo run, to pick the backend for kokopelli/wm/seen.py" \
        --output out/sensation/seen_eval/RUN -- .venv/bin/python -m experiments.sensation.seen_eval run --out out/sensation/seen_eval/RUN
    # CPU: the tables again from the saved detections (after changing a threshold, say)
    .venv/bin/python -m experiments.sensation.seen_eval report --out out/sensation/seen_eval/RUN

The data is the one real painted closed-loop run with a person in it: out/bodies/demo/runs/wm (2026-11-08, two agents,
Cosmos3-Nano-Sim-Transfer 8-bit at 448x256, 16 fps, four controls). Its raw sim captures were deleted as it ran. What
is left, frame for frame with the painted film, is the segmentation control video (the sim's object masks crossed with
a material class, painted in a fixed palette, H.264). So:

  - a frame's truth is "the sim's segmentation shows a person here": a connected region of at least MIN_PX pixels in one
    of the palette colours a human body has in this run (HUMAN_RGB, found by hand from the sim films; the audit sheets
    are for checking that by eye). "Nobody" is strict: no trace of those colours, and no person-sized region within
    NEAR_S seconds either side in the same view (a far-off walker is a few pixels the codec smears before she is big
    enough to box). Everything between is "unclear": left out of the scores and counted;
  - the question put to seen() on every frame is the leak's own: the sim says another person exists; is she in the
    picture? One candidate, label LABEL, no box (egg_wm can't give one today). Confirmed with a person on screen is
    right; confirmed with nobody on screen is the leak surviving; that includes strangers Cosmos paints on its own;
  - frames up to CLEAN_UNTIL_S are the headline. After that this run's films break into a mosaic (its README); those
    are scored apart, because there a person the sim shows may truly not be painted.

Model time is kept short (the first run was made on a 68 W charger, where every model minute drained the battery):
the detectors only see the frames that get scored, which is every headline frame with a clear truth and every
LATE_EVERY-th frame after the mosaic, and each backend has BUDGET_S seconds of detecting. A backend that runs out
before the headline frames are done is reported as cut short and can't be picked.

Limits to keep in view: one run, two views, neighbouring frames half a second apart, one kind of thing (a person), and
the truth is the sim's, read back from a compressed video with colours matched by hand.

Writes <out>/frames/, labels.json, audit_*.png, detections_<backend>.jsonl (every box down to the worker's floor, so
the tables can be recomputed), run.json (models, revisions, licences, timings), report.md, report.json and, when a
backend clears the bar, chosen_backend.json. --fake swaps in a fake detector to test the plumbing; everything it
writes says so.
"""
import argparse
import json
import random
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

from kokopelli.wm import seen as seen_mod
from kokopelli.wm.manifest import git_state

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "out" / "bodies" / "demo" / "runs" / "wm"
VIEWS = ("mara", "iris")
FPS = 16
CLEAN_UNTIL_S = 52.0        # the run's README: both films look photographic up to about 52 s, then a mosaic takes over
STEP_CLEAN, STEP_LATE = 8, 16   # every 0.5 s in the clean part, every 1 s after it
# The palette colours a human body has in this run's seg control (read off region interiors; see the lane log), each
# with the smallest patch that counts as a trace of a person. The olive one also turns up as specks where the codec
# blends greens and browns, so it needs a bigger patch.
HUMAN_RGB = ((26, 229, 231), (132, 151, 55), (231, 228, 72))
TRACE_PX = (8, 12, 8)
COLOUR_TOL = 22.0
MIN_PX, AMBIGUOUS_PX = 150, 40
NEAR_S = 5.0
SMALL_H = 60                # a person shorter than this many pixels (of 256) counts as "small" in the breakdown
LABEL = "a person"
BACKENDS = ("owlv2", "grounding_dino", "florence2", "florence2_ground")
THRESHOLDS = [round(0.05 * k, 2) for k in range(1, 20)]
PRECISION_BAR, LATENCY_BAR_S = 0.9, 1.0
HINT_IOU = 0.3
LATE_EVERY = 4              # of the frames after the mosaic, the detectors see every 4th (one every 4 s)
BUDGET_S = 180.0            # seconds of detecting per backend, over all its tries; the load is not counted


def people_in(seg_rgb):
    """Person regions in one frame of the seg control: boxes of the clear ones, whether any region is person-sized,
    and whether there is any trace of a human colour at all."""
    seg = seg_rgb.astype(np.float32)
    near = np.zeros(seg.shape[:2], bool)
    trace = False
    for colour, least in zip(HUMAN_RGB, TRACE_PX, strict=True):
        this = np.linalg.norm(seg - np.array(colour, np.float32), axis=2) <= COLOUR_TOL
        near |= this
        n, _, stats, _ = cv2.connectedComponentsWithStats(this.astype(np.uint8), connectivity=8)
        trace = trace or bool(n > 1 and stats[1:, cv2.CC_STAT_AREA].max() >= least)
    mask = cv2.morphologyEx(near.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    areas = [tuple(int(v) for v in stats[k]) for k in range(1, n)]
    boxes = [[x, y, x + w, y + h] for x, y, w, h, area in areas if area >= MIN_PX]
    return {"boxes": boxes, "sized": any(area >= AMBIGUOUS_PX for *_, area in areas), "trace": trace}


def truths(found):
    """found: {frame number: people_in(...)} for one view. person, nobody or unclear for each frame (see the docstring)."""
    sized = [k for k, f in found.items() if f["sized"]]
    out = {}
    for k, f in found.items():
        if f["boxes"]:
            out[k] = "person"
        elif f["trace"] or f["sized"] or any(abs(k - other) <= NEAR_S * FPS for other in sized):
            out[k] = "unclear"
        else:
            out[k] = "nobody"
    return out


def read_frames(path, wanted):
    cap, out, k = cv2.VideoCapture(str(path)), {}, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if k in wanted:
            out[k] = frame
        k += 1
    return out, k


def sheet(tiles, path, across=4):
    while len(tiles) % across:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[k:k + across]) for k in range(0, len(tiles), across)]))


def labels(out, run=RUN):
    """Extract the painted frames and write labels.json; returns its rows."""
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    side = json.loads((run / "run.json").read_text())
    if side.get("fake_world_model") is not False:
        raise SystemExit(f"{run} isn't a real painted run (fake_world_model={side.get('fake_world_model')!r})")
    rows = []
    for view in VIEWS:
        total = int(cv2.VideoCapture(str(run / "film" / f"{view}.mp4")).get(cv2.CAP_PROP_FRAME_COUNT))
        clean_end = int(CLEAN_UNTIL_S * FPS)
        wanted = set(range(0, clean_end + 1, STEP_CLEAN)) | set(range(clean_end + STEP_LATE, total, STEP_LATE))
        painted, n_painted = read_frames(run / "film" / f"{view}.mp4", wanted)
        seg, n_seg = read_frames(run / "controls" / view / "seg.mp4", wanted)
        sim, _ = read_frames(run / "film" / f"sim_{view}.mp4", wanted)
        if n_painted != n_seg:
            raise SystemExit(f"{view}: the painted film has {n_painted} frames and the seg control {n_seg}; they must line up")
        tiles = {"person": [], "nobody": [], "unclear": []}
        found = {k: people_in(cv2.cvtColor(seg[k], cv2.COLOR_BGR2RGB)) for k in sorted(wanted)}
        truth = truths(found)
        for k in sorted(wanted):
            boxes, kind = found[k]["boxes"], truth[k]
            name = f"{view}_{k:04d}.png"
            cv2.imwrite(str(out / "frames" / name), painted[k])
            rows.append({"frame": name, "view": view, "k": k, "t": round(k / FPS, 3), "part": "clean" if k / FPS <= CLEAN_UNTIL_S else "late",
                         "truth": kind, "boxes": boxes})
            tile = np.hstack([sim[k], painted[k]])
            for x0, y0, x1, y1 in boxes:
                for dx in (0, sim[k].shape[1]):
                    cv2.rectangle(tile, (x0 + dx, y0), (x1 + dx, y1), (0, 255, 0), 1)
            cv2.putText(tile, f"{view} {k} {kind}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            tiles[kind].append(cv2.resize(tile, (448, 128)))
        for kind, made in tiles.items():   # every frame, sim render left and painting right, for checking the labels by eye
            if made:
                sheet(made, out / f"audit_{view}_{kind}.png")
    record = {"source_run": str(run.relative_to(ROOT)), "world_model": side.get("world_model"), "worker": side.get("worker"),
              "size": "448x256", "fps": FPS, "label": LABEL, "human_rgb": HUMAN_RGB, "trace_px": TRACE_PX, "colour_tol": COLOUR_TOL, "min_px": MIN_PX, "near_s": NEAR_S,
              "clean_until_s": CLEAN_UNTIL_S, "rows": rows}
    (out / "labels.json").write_text(json.dumps(record, indent=1))
    return rows


class FakeDetector:
    """A fake detector, for testing this script without a model: mostly right about people, with invented scores."""

    def __init__(self, rows, seed=0):
        self.rows, self.rng, self.last_seconds = {r["frame"]: r for r in rows}, random.Random(seed), 0.0

    def start(self):
        return {"ready": True, "load_seconds": 0.0, "about": {"model": "fake (no model)", "fake": True}}

    def detect(self, frame, labels):
        row = self.rows[Path(frame).name]
        self.last_seconds = 0.001
        found = [seen_mod.Detection(labels[0], tuple(box), self.rng.uniform(0.3, 0.9)) for box in row["boxes"] if self.rng.random() < 0.8]
        if self.rng.random() < 0.1:
            found.append(seen_mod.Detection(labels[0], (5.0, 5.0, 40.0, 90.0), self.rng.uniform(0.05, 0.5)))
        return found

    def stats(self):
        return {}

    def close(self):
        pass


def to_detect(rows):
    """The frames a detector is run on, headline first: every headline frame with a clear truth, then every
    LATE_EVERY-th frame after the mosaic. Unclear frames are never scored, so no model time goes on them."""
    clean = [r for r in rows if r["part"] == "clean" and r["truth"] != "unclear"]
    late = [r for r in rows if r["part"] == "late" and r["truth"] != "unclear"]
    return clean + late[::LATE_EVERY]


def detect_all(out, rows, backend, fake=False, device=None, budget_s=BUDGET_S):
    """Run one backend over the frames of to_detect(rows) and save all it found, stopping when budget_s seconds of
    detecting are used up; returns that backend's entry for run.json."""
    out = Path(out)
    det = FakeDetector(rows) if fake else seen_mod.WorkerDetector(backend, device=device)
    todo = to_detect(rows)
    began = None
    entry = {"backend": backend, "fake": fake, "errors": [], "frames_asked": len(todo), "frames_done": 0, "budget_s": round(budget_s, 1)}
    try:
        t0 = time.time()
        info = det.start()
        entry.update(load_seconds=info.get("load_seconds"), about=info.get("about"), start_seconds=round(time.time() - t0, 2))
        began = time.time()
        with (out / f"detections_{backend}.jsonl").open("w") as log:
            for row in todo:
                t = time.time()
                if t - began > budget_s:
                    entry["cut_short"] = f"out of time: {entry['frames_done']} of {len(todo)} frames in {budget_s:.0f} s"
                    break
                try:
                    found = det.detect(str(out / "frames" / row["frame"]), [LABEL])
                except RuntimeError as error:
                    entry["errors"].append({"frame": row["frame"], "error": str(error)})
                    if len(entry["errors"]) >= 5:
                        raise
                    continue
                log.write(json.dumps({"frame": row["frame"], "seconds": det.last_seconds, "round_trip_s": round(time.time() - t, 4),
                                      "detections": [{"label": d.label, "box": [round(v, 1) for v in d.box], "score": round(d.score, 4)}
                                                     for d in found]}) + "\n")
                entry["frames_done"] += 1
        entry["detect_seconds"] = round(time.time() - began, 1)
        entry["memory"] = det.stats()
    except Exception as error:   # one backend failing must not lose the others; run.json and the report say it failed
        entry["failed"] = f"{type(error).__name__}: {error}"
        entry["detect_seconds_before_failing"] = round(time.time() - began, 1) if began else 0.0
    finally:
        det.close()
    return entry


def load_detections(out, backend):
    path = Path(out) / f"detections_{backend}.jsonl"
    if not path.exists():
        return {}
    return {r["frame"]: r for r in map(json.loads, path.read_text().splitlines())}


def confirmed(row, found, threshold, hinted=False):
    """Does seen()'s filter confirm the one candidate on this frame? hinted: the candidate carries the sim's box."""
    detections = [seen_mod.Detection(d["label"], tuple(d["box"]), d["score"]) for d in found["detections"]]
    if hinted:
        return any(seen_mod.confirm([seen_mod.Candidate("other", LABEL, tuple(box))], detections, threshold, HINT_IOU) for box in row["boxes"])
    return bool(seen_mod.confirm([seen_mod.Candidate("other", LABEL)], detections, threshold, HINT_IOU))


def score(rows, found, threshold, hinted=False):
    """Counts and rates over the frames that have both a clear truth and a detection record."""
    tp = fp = fn = tn = 0
    for row in rows:
        if row["truth"] == "unclear" or row["frame"] not in found:
            continue
        there = row["truth"] == "person"
        if hinted and not there:
            continue   # with a box, a candidate the sim puts off screen is never offered
        said = confirmed(row, found[row["frame"]], threshold, hinted)
        tp, fp, fn, tn = tp + (said and there), fp + (said and not there), fn + (not said and there), tn + (not said and not there)
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None}


def best_at_bar(rows, found):
    """The threshold with the most recall among those whose precision is at least the bar, or None."""
    passing = [s for s in (score(rows, found, t) for t in THRESHOLDS) if s["precision"] is not None and s["precision"] >= PRECISION_BAR]
    return max(passing, key=lambda s: (s["recall"] or 0.0, s["threshold"])) if passing else None


def analyse(out):
    out = Path(out)
    record = json.loads((out / "labels.json").read_text())
    run = json.loads((out / "run.json").read_text()) if (out / "run.json").exists() else {"backends": []}
    rows = record["rows"]
    clean, late = [r for r in rows if r["part"] == "clean"], [r for r in rows if r["part"] == "late"]
    count = lambda part, truth: sum(r["truth"] == truth for r in part)   # noqa: E731
    shown = {r["frame"] for r in to_detect(rows)}
    result = {"frames": {name: {"all": len(part), "person": count(part, "person"), "nobody": count(part, "nobody"), "unclear": count(part, "unclear"),
                                "shown_to_detectors": sum(r["frame"] in shown for r in part)}
                         for name, part in (("clean", clean), ("late", late))}, "backends": {}, "fake": bool(run.get("fake"))}
    for entry in run["backends"]:
        name = entry["backend"]
        found = load_detections(out, name)
        if not found:
            result["backends"][name] = {"ran": False, "why": entry.get("failed") or "no detections file"}
            continue
        seconds = [found[r["frame"]]["seconds"] for r in rows if r["frame"] in found]
        warm = seconds[1:] or seconds   # the first frame pays for warm-up
        small = [r for r in clean if r["truth"] != "person" or max(b[3] - b[1] for b in r["boxes"]) < SMALL_H]
        large = [r for r in clean if r["truth"] != "person" or max(b[3] - b[1] for b in r["boxes"]) >= SMALL_H]
        at_bar = best_at_bar(clean, found)
        complete = all(r["frame"] in found for r in clean if r["truth"] != "unclear")   # cut short or erroring: not fully measured
        latency = {"median_s": round(statistics.median(warm), 4), "p95_s": round(sorted(warm)[int(0.95 * (len(warm) - 1))], 4),
                   "first_frame_s": seconds[0], "load_s": entry.get("load_seconds")}
        result["backends"][name] = {
            "ran": True, "frames_scored": len(seconds), "errors": len(entry.get("errors", [])), "latency": latency,
            "complete": complete, "cut_short": entry.get("cut_short"), "first_try_failed": entry.get("first_try_failed"),
            "memory": entry.get("memory"), "about": entry.get("about"), "at_bar_clean": at_bar,
            "sweep_clean": [score(clean, found, t) for t in THRESHOLDS],
            "late_at_same_threshold": score(late, found, at_bar["threshold"]) if at_bar else None,
            "small_at_same_threshold": score(small, found, at_bar["threshold"]) if at_bar else None,
            "large_at_same_threshold": score(large, found, at_bar["threshold"]) if at_bar else None,
            "hinted_recall_clean": score(clean, found, at_bar["threshold"], hinted=True) if at_bar else None,
            "passes": bool(complete and at_bar and at_bar["recall"] and latency["median_s"] < LATENCY_BAR_S)}
    passing = {} if result["fake"] else {n: b for n, b in result["backends"].items() if b.get("passes")}   # a fake detector is never picked
    result["pick"] = max(passing, key=lambda n: (passing[n]["at_bar_clean"]["recall"], -passing[n]["latency"]["median_s"])) if passing else None
    (out / "report.json").write_text(json.dumps(result, indent=1))
    return record, run, result


def report(out):
    out = Path(out)
    record, run, result = analyse(out)
    fake = result["fake"]
    f = result["frames"]
    lines = ["# seen(): which detector confirms a sim person in a painted frame", ""]
    if fake:
        lines += ["**Not a real detector.** This is a dry run of the script with a fake detector; no number below says anything about a model.", ""]
    lines += [f"Frames: `{record['source_run']}` ({record['world_model']}, 8-bit, {record['size']}, {record['fps']} fps), both agents' painted films. "
              f"Headline part (up to {record['clean_until_s']:g} s, every 0.5 s): {f['clean']['all']} frames, of which the sim's segmentation shows a person "
              f"in {f['clean']['person']}, nobody in {f['clean']['nobody']}, and {f['clean']['unclear']} are left out as unclear. "
              f"After the mosaic sets in (every 1 s): {f['late']['all']} frames, person in {f['late']['person']}, nobody in {f['late']['nobody']}, "
              f"unclear {f['late']['unclear']}.", "",
              f"Shortened to save model time: the detectors were shown only the frames that are scored, {f['clean']['shown_to_detectors']} headline "
              f"frames and every {LATE_EVERY}th frame after the mosaic ({f['late']['shown_to_detectors']}), and each backend had {BUDGET_S:g} s of detecting.", "",
              f"On each frame seen() gets one candidate, \"{LABEL}\", with no box. Precision: of the frames where it was confirmed, the share where the "
              "sim's segmentation has a person on screen. Recall: of the frames where it has one, the share confirmed. "
              f"The bar is the best recall at precision >= {PRECISION_BAR:g} with a median under {LATENCY_BAR_S:g} s per frame.", "",
              "| Backend | Threshold | Precision | Recall | TP / FP / FN / TN | Median s | p95 s | Load s | Passes |", "|---|---|---|---|---|---|---|---|---|"]
    for name, b in result["backends"].items():
        if not b["ran"]:
            lines.append(f"| {name} | did not run: {b['why']} | | | | | | | no |")
            continue
        lat, s = b["latency"], b["at_bar_clean"]
        if s:
            lines.append(f"| {name} | {s['threshold']:g} | {s['precision']:.3f} | {s['recall']:.3f} | {s['tp']} / {s['fp']} / {s['fn']} / {s['tn']} | "
                         f"{lat['median_s']:.3f} | {lat['p95_s']:.3f} | {lat['load_s']} | {'yes' if b['passes'] else 'no'} |")
        else:
            top = max(b["sweep_clean"], key=lambda r: r["precision"] or 0.0)
            lines.append(f"| {name} | none reaches {PRECISION_BAR:g} (best precision {top['precision']} at {top['threshold']:g}, recall {top['recall']}) | | | "
                         f"{top['tp']} / {top['fp']} / {top['fn']} / {top['tn']} | {lat['median_s']:.3f} | {lat['p95_s']:.3f} | {lat['load_s']} | no |")
    for name, b in result["backends"].items():
        notes = [f"cut short ({b['cut_short']}), so it can't be picked" if b.get("cut_short") else "",
                 f"{b['errors']} frames gave an error" if b.get("errors") else "",
                 f"the first try failed ({b['first_try_failed']}) and these numbers are from the retry on the CPU" if b.get("first_try_failed") else ""]
        if any(notes):
            lines += ["", f"{name}: " + "; ".join(n for n in notes if n) + "."]
    lines += ["", f"**Pick: {result['pick'] or 'none'}.**" + (" (A fake detector is never picked.)" if fake else ""), "",
              "## At each backend's own threshold from the table", "",
              "| Backend | Small people (under 60 px tall): recall | Larger: recall | With the sim's box (IoU >= 0.3): recall | After the mosaic: precision, recall |",
              "|---|---|---|---|---|"]
    rate = lambda s, key: "n/a" if not s or s[key] is None else f"{s[key]:.3f} ({s['tp']} of {s['tp'] + (s['fn'] if key == 'recall' else s['fp'])})"   # noqa: E731
    for name, b in result["backends"].items():
        if b["ran"] and b["at_bar_clean"]:
            lines.append(f"| {name} | {rate(b['small_at_same_threshold'], 'recall')} | {rate(b['large_at_same_threshold'], 'recall')} | "
                         f"{rate(b['hinted_recall_clean'], 'recall')} | {rate(b['late_at_same_threshold'], 'precision')}, {rate(b['late_at_same_threshold'], 'recall')} |")
    lines += ["", "## Every threshold, headline part", ""]
    for name, b in result["backends"].items():
        if b["ran"]:
            lines += [f"**{name}**", "", "| Threshold | Precision | Recall | TP | FP | FN | TN |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {s['threshold']:g} | {s['precision']} | {s['recall']} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} |" for s in b["sweep_clean"]]
            lines.append("")
    lines += ["## Models", "", "| Backend | Model | Weights (repo@revision) | Licence | Device | Peak memory (process, Metal) GB |", "|---|---|---|---|---|---|"]
    for name, b in result["backends"].items():
        a, m = b.get("about") or {}, b.get("memory") or {}
        lines.append(f"| {name} | {a.get('model')} | `{a.get('weights')}` | {a.get('licence')} | {a.get('device')} | {m.get('peak_rss_gb')}, {m.get('metal_gb')} |")
    lines += ["", "## What this does not show", "",
              "- One run, two views, frames half a second apart: neighbouring frames are nearly the same picture, so the counts overstate how much was seen.",
              "- One kind of thing. Nothing here says how a backend does on a ball, a bench or an egg.",
              "- The truth is the sim's segmentation read back from an H.264 control video, with the human colours matched by hand. "
              "The audit sheets beside this report show every frame with its label.",
              "- A false positive is a frame where the detector found a person and the sim has none on screen. Cosmos paints passers-by of its own "
              "(its prompt mentions neighbours), so some of these are the detector being right about the picture; for the leak they are still wrong.",
              "- Florence-2 gives no confidence, so its row is one operating point, not a threshold choice.",
              f"- Latency is one {record['size']} frame, one label, on this Mac, warm; the first frame and the load are listed apart.", ""]
    (out / "report.md").write_text("\n".join(lines))
    if result["pick"] and not fake:
        chosen = result["backends"][result["pick"]]
        (out / "chosen_backend.json").write_text(json.dumps({
            **(chosen["about"] or {}), "chosen_by": "experiments/sensation/seen_eval.py", "rule": f"best recall at precision >= {PRECISION_BAR} with median latency < {LATENCY_BAR_S} s",
            "threshold": chosen["at_bar_clean"]["threshold"], "measured": chosen["at_bar_clean"], "latency": chosen["latency"],
            "frames": record["source_run"], "report": "report.md", "commit": run.get("commit")}, indent=1))
    return result


def run(out, backends, fake=False):
    out = Path(out)
    rows = labels(out)
    record = {"experiment": "seen_eval", "made_by": "experiments/sensation/seen_eval.py", "fake": fake, "label": LABEL,
              "frames_from": str(RUN.relative_to(ROOT)), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), **git_state(ROOT), "backends": []}
    for backend in backends:   # one detector loaded at a time
        entry = detect_all(out, rows, backend, fake)
        if entry.get("failed") and not fake:   # Metal lacks an operation now and then; the CPU answer is slower but real
            left = BUDGET_S - entry.get("detect_seconds_before_failing", 0.0)
            entry = {**detect_all(out, rows, backend, device="cpu", budget_s=left), "first_try_failed": entry["failed"]}
        record["backends"].append(entry)
        record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (out / "run.json").write_text(json.dumps(record, indent=1))
    result = report(out)
    print(json.dumps({"pick": result["pick"], "report": str(out / "report.md")}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("labels", "run", "report"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        if name == "run":
            p.add_argument("--backends", nargs="+", default=list(BACKENDS), choices=sorted(seen_mod.BACKENDS))
            p.add_argument("--fake", action="store_true", help="a fake detector, to test this script; never a result")
    args = ap.parse_args()
    if args.cmd == "labels":
        rows = labels(args.out)
        print(json.dumps({kind: sum(r["truth"] == kind for r in rows) for kind in ("person", "nobody", "unclear")}))
    elif args.cmd == "run":
        run(args.out, args.backends, args.fake)
    else:
        report(args.out)


if __name__ == "__main__":
    main()
