"""Did each labeled object come out as what its label says? The scoreboard for object labels (kokopelli/wm/labels.py).

After a paint, every 4th frame (one per latent frame), the painted picture is cropped around each listed actor's mask
(25% padding) and Qwen3-VL answers a forced choice: the actor's class, a few things it could be mistaken for, or
"other". Per actor:
  accuracy   share of asked frames answered with its class,
  flips      how often the answer changes from one asked frame to the next (the "became a ball halfway through" bug),
  said_labeled_class   for an actor that is only watched (a class, no label): share of frames answered with a labeled
             actor's class, which is a label leaking onto its neighbour.
With --baseline (the same paint without labels) it also measures how much the picture changed outside every label
region, the price the rest of the frame paid.

    python -m kokopelli.wm.label_check out/labels/a.mp4 --labels labels.json --clip out/labels/regression/clip
    python -m kokopelli.wm.label_check out/labels/a.mp4 --labels labels.json --clip CLIP --baseline out/labels/none.mp4
    python -m kokopelli.wm.label_check calibrate out/labels/calibration    # hand-sorted crops, one folder per class

Writes <video>.labels.json beside the paint's own sidecar. This loads Qwen (about 18 GB): queue it through
kokopelli/ops/gpu.py, after the paint, never while Cosmos is loaded. Calibrate first: if Qwen is wrong on more than
about 10% of crops a person sorted by hand, the checker is the bottleneck, not the world model.
"""
import argparse
import json
import random
import re
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from kokopelli.settings import LLM_MODEL, LLM_MODEL_WEIGHTS
from kokopelli.wm import labels as lb

ROOT = Path(__file__).resolve().parents[2]
OTHER = "other"
EVERY = 4            # one asked frame per latent frame
LAG = 3              # a batch paint runs 3 frames behind its clip (docs/SIM_TRANSFER_MLX.md, deviation 8): painted
                     # frame i shows clip frame i - 3. The streaming worker has no lag; pass --lag 0 for its films.
PAD = 0.25           # of the mask's box, added on every side
MIN_SIDE = 12        # a mask box narrower than this on the painted frame is too small to judge
CROP_SIDE = 224      # crops are enlarged so their short side is at least this
MAX_CHECKER_ERROR = 0.10
CACHE = ROOT / "out" / "labels" / "confusables.json"
# What each class gets mistaken for. A class not listed here is asked of Qwen once and remembered in CACHE.
CONFUSABLE = {
    "balloon": ["ball", "orange", "lamp", "fruit"],
    "ball": ["balloon", "orange", "lamp", "stone"],
    "lamp": ["balloon", "ball", "moon", "fruit"],
    "fruit": ["ball", "balloon", "flower", "lamp"],
}


def words(answer):
    return re.findall(r"[a-z]+", answer.lower())


def confusables(cls, ask, cache=CACHE):
    """Things a small or blurry `cls` could be taken for: the hand table, else Qwen's answer, asked once per class."""
    if cls in CONFUSABLE:
        return CONFUSABLE[cls]
    known = json.loads(cache.read_text()) if cache.exists() else {}
    if cls not in known:
        answer = ask(f"Name four everyday objects that a small or blurry picture of a {cls} could be mistaken for. "
                     "Answer with four single words separated by commas.")
        named = [words(piece)[-1] for piece in answer.split(",") if words(piece)]   # "and maybe a moon" -> "moon"
        known[cls] = [w for w in dict.fromkeys(named) if w not in (cls, OTHER)][:4]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    return known[cls]


def choices(cls, others, ask, cache=CACHE):
    """The forced choice for one actor: its class, the other classes in the clip, its look-alikes, then "other"."""
    listed = [cls] + [c for c in others if c != cls] + confusables(cls, ask, cache)
    return list(dict.fromkeys(listed))[:6] + [OTHER]


def question(options, key):
    """The options are shuffled, the same way every time for one actor and frame, so no class always comes first."""
    shuffled = options[:-1]
    random.Random(key).shuffle(shuffled)
    return ("Look at the object in the middle of this picture. Which one of these is it: "
            f"{', '.join(shuffled + options[-1:])}? Answer with exactly one word from the list.")


def parse(answer, options):
    """The first listed option the answer names, else "unparsed" (which counts as wrong)."""
    return next((w for w in words(answer) if w in options), "unparsed")


def crop(frame, box):
    """The frame cut to box [x0, y0, x1, y1] plus PAD on every side, enlarged to at least CROP_SIDE on its short side."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    px, py = PAD * (x1 - x0), PAD * (y1 - y0)
    x0, y0, x1, y1 = max(0, int(x0 - px)), max(0, int(y0 - py)), min(w, int(np.ceil(x1 + px))), min(h, int(np.ceil(y1 + py)))
    cut = frame[y0:y1, x0:x1]
    scale = CROP_SIDE / min(cut.shape[:2])
    if scale > 1:
        cut = cv2.resize(cut, (round(cut.shape[1] * scale), round(cut.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
    return cut


def ask_crop(ask, picture, options, key, folder):
    path = Path(folder) / (re.sub(r"\W+", "_", key) + ".png")
    cv2.imwrite(str(path), cv2.cvtColor(picture, cv2.COLOR_RGB2BGR))
    return parse(ask(question(options, key), images=[path], max_tokens=8), options)


def check_frames(frames, meta, ask, cache=CACHE, every=EVERY, lag=LAG):
    """frames: painted frames, uint8 [n, H, W, 3]; painted frame i + lag shows the clip's frame i. meta: the clip's
    labels_meta.json. ask: llm_model.ask or a stand-in. Answers are listed by clip frame. Returns
    {"actors": [...], "summary": {...}}."""
    rows = [r for r in meta["labels"] if r["class"]]
    labeled_classes = {r["class"] for r in rows if r["label"]}
    sx, sy = frames.shape[2] / meta["size"][0], frames.shape[1] / meta["size"][1]
    actors = []
    with tempfile.TemporaryDirectory(prefix="label_check_") as folder:
        for row in rows:
            options = choices(row["class"], [r["class"] for r in rows], ask, cache)
            answers, too_small = [], 0
            for i in range(0, min(len(frames) - lag, len(row["bbox"])), every):
                box = row["bbox"][i]
                if box is None:
                    continue
                box = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
                if min(box[2] - box[0], box[3] - box[1]) < MIN_SIDE:
                    too_small += 1
                    continue
                answers.append([i, ask_crop(ask, crop(frames[i + lag], box), options, f"{row['actor']}:{i}", folder)])
            said = [a for _, a in answers]
            others = labeled_classes - {row["class"]}
            actors.append({
                "actor": row["actor"], "class": row["class"], "labeled": bool(row["label"]), "label": row["label"],
                "priority": row["priority"], "options": options, "asked": len(said), "too_small": too_small,
                "accuracy": round(said.count(row["class"]) / len(said), 3) if said else None,
                "flips": sum(a != b for a, b in zip(said, said[1:], strict=False)),
                "unparsed": said.count("unparsed"),
                "said_labeled_class": round(sum(a in others for a in said) / len(said), 3) if said else None,
                "answers": answers})

    def mean(key, keep):
        got = [a[key] for a in actors if keep(a) and a[key] is not None]
        return round(float(np.mean(got)), 3) if got else None
    return {"actors": actors, "summary": {
        "labeled_accuracy": mean("accuracy", lambda a: a["labeled"]),
        "hero_accuracy": mean("accuracy", lambda a: a["labeled"] and a["priority"] == "hero"),
        "labeled_flips": sum(a["flips"] for a in actors if a["labeled"]),
        "watched_accuracy": mean("accuracy", lambda a: not a["labeled"]),
        "neighbor_leak": mean("said_labeled_class", lambda a: not a["labeled"]),
        "never_asked": [a["actor"] for a in actors if not a["asked"]]}}


def outside_change(frames, baseline, label_frames, lag=LAG):
    """Mean absolute pixel difference (0-255) between a labeled paint and the same paint without labels, outside every
    label region and inside them. A region is widened by one token (32 px), since a token on its border is half in.
    label_frames: uint16 [n, H, W] at the painted size (labels.read_frames); both paints run `lag` frames behind them."""
    n = min(len(frames), len(baseline), len(label_frames) + lag)
    kernel = np.ones((2 * lb.TOKEN + 1, 2 * lb.TOKEN + 1), np.uint8)
    out_sum = in_sum = out_n = in_n = 0.0
    for i in range(n):
        diff = np.abs(frames[i].astype(np.int16) - baseline[i].astype(np.int16)).mean(2)
        near = cv2.dilate((label_frames[max(0, i - lag)] > 0).astype(np.uint8), kernel).astype(bool)
        out_sum, out_n = out_sum + diff[~near].sum(), out_n + (~near).sum()
        in_sum, in_n = in_sum + diff[near].sum(), in_n + near.sum()
    return {"frames": n, "outside": round(out_sum / out_n, 3) if out_n else None,
            "inside": round(in_sum / in_n, 3) if in_n else None}


def calibrate(folder, ask, cache=CACHE):
    """How often Qwen is wrong on its own. folder/<class>/*.png|jpg are crops a person sorted. Writes
    folder/calibration.json; the checker is fit to use when the error is at most MAX_CHECKER_ERROR."""
    folder = Path(folder)
    classes = sorted(d.name for d in folder.iterdir() if d.is_dir())
    rows, wrong = [], 0
    for cls in classes:
        options = choices(cls, classes, ask, cache)
        for path in sorted(p for p in (folder / cls).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")):
            answer = parse(ask(question(options, f"{cls}:{path.name}"), images=[path], max_tokens=8), options)
            wrong += answer != cls
            rows.append({"file": f"{cls}/{path.name}", "truth": cls, "answer": answer})
    if not rows:
        raise SystemExit(f"no crops under {folder}/<class>/")
    error = wrong / len(rows)
    report = {"model": LLM_MODEL, "weights": str(LLM_MODEL_WEIGHTS), "crops": len(rows), "error": round(error, 3),
              "by_class": {c: round(float(np.mean([r["answer"] != c for r in rows if r["truth"] == c])), 3) for c in classes
                           if any(r["truth"] == c for r in rows)},
              "usable": error <= MAX_CHECKER_ERROR, "rows": rows}
    (folder / "calibration.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def read_video(path, size=None):
    from kokopelli.wm.video_check import read_frames
    return np.concatenate(list(read_frames(path, size)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="a painted video, or 'calibrate'")
    parser.add_argument("folder", nargs="?", help="with calibrate: the folder of hand-sorted crops")
    parser.add_argument("--labels", help="the labels.json the clip's label pass was built from")
    parser.add_argument("--clip", help="the clip folder (labels/ and labels_meta.json)")
    parser.add_argument("--baseline", help="the same paint without labels, for the outside-change measure")
    parser.add_argument("--lag", type=int, default=LAG, help="frames the paint runs behind its clip: 3 for world_transfer.py, 0 for the stream")
    args = parser.parse_args(argv)
    from kokopelli.wm.llm_model import ask   # here, not at the top: importing it loads mlx_vlm
    if args.video == "calibrate":
        if not args.folder:
            parser.error("calibrate needs the folder of crops")
        report = calibrate(args.folder, ask)
        print(f"{report['crops']} crops, Qwen wrong on {report['error']:.0%}: "
              + ("usable" if report["usable"] else "the checker is the bottleneck, don't trust label scores yet"))
        return 0 if report["usable"] else 1
    if not (args.labels and args.clip):
        parser.error("--labels and --clip are required")
    clip = Path(args.clip)
    lb.check_meta(clip / "labels", lb.load(args.labels))
    meta = json.loads((clip / "labels_meta.json").read_text())
    frames = read_video(args.video)
    report = check_frames(frames, meta, ask, lag=args.lag)
    if args.baseline:
        h, w = frames.shape[1:3]
        report["change_vs_baseline"] = {"baseline": str(args.baseline), **outside_change(
            frames, read_video(args.baseline, (w, h)), lb.read_frames(clip / "labels", w, h, len(frames)), args.lag)}
    paint = Path(str(args.video) + ".json")
    paint = json.loads(paint.read_text()) if paint.exists() else {}
    report = {"video": str(args.video), "lag_frames": args.lag, "checker_model": LLM_MODEL, "checker_weights": str(LLM_MODEL_WEIGHTS),
              "paint_model": paint.get("model"), "paint_labels": paint.get("labels", {}).get("file"),
              "labels_sha256": lb.sha256(args.labels), "clip": str(clip), **report}
    Path(str(args.video) + ".labels.json").write_text(json.dumps(report, indent=1) + "\n")
    for a in report["actors"]:
        acc = "-" if a["accuracy"] is None else f"{a['accuracy']:.0%}"
        print(f"{a['actor']:32s} {a['class']:10s} {'labeled' if a['labeled'] else 'watched'}  accuracy {acc:>4s}  "
              f"flips {a['flips']}  asked {a['asked']}  too small {a['too_small']}")
    print(json.dumps(report["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
