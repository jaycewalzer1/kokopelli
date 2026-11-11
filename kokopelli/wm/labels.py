"""Optional object labels on top of the seg control, for Cosmos3-Nano-Sim-Transfer (docs/LABELS_PLAN.md).

A seg colour says where a region is and nothing about what it is: the colours are random by design (controls.py
Palette). What a region is comes from the caption, and every picture token reads every caption word, so a round blob is
as free to read "soccer ball" as "balloon". A label ties the two together: this actor's pixels, these words.

    labels.json   {"version": 1, "labels": [
                    {"actor": "GEN_BP_balloon_0", "label": "red latex balloon on a thin white string",
                     "class": "balloon", "priority": "hero"},
                    {"actor": "GEN_BP_ball_2", "class": "ball"}]}
                  Entry k (counting from 1) is pixel value k in the label frames. `label` is what the caption says;
                  an entry without one is only watched (label_check.py scores it, the paint never names it). `class`
                  is the checker's one-word name. `priority` "hero" goes first when a shot has too many labels.
                  "world_id" may stand in for "actor" where the caller has a world.json id -> actor name table.
    labels/NNNN.png, labels_meta.json   built here from segmentation/NNNN.png and the capture's mask colours: 16-bit
                  PNG, 0 = no label. Lossless on purpose: one H.264 colour bleed would hand a label its neighbour.

    .venv/bin/python -m kokopelli.wm.labels build --clip out/labels/regression/clip --labels labels.json

A paint (world_transfer.py --labels labels.json --label-frames clip/labels) then uses this file three ways:
  1. caption: one `subjects` entry per visible labeled actor, its location and size worded from its mask (Tier A);
  2. spans: where each label's description sits among the caption's tokens;
  3. regions and mask: which picture tokens of each latent frame lie on the actor, and the additive attention bias that
     lets only those tokens read that label's words (Tier B). One token is 32x32 px and 4 frames.

numpy and PIL only, no MLX: the Cosmos venv imports it for a paint, the repo venv for the build and the tests.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

VERSION = 1
TOKEN = 32   # pixels across one picture token: the VAE's 16x times the 2x2 patch
TCF = 4      # video frames per latent frame after the first (world_transfer.TCF)
PRIORITIES = ("hero", "normal")
FIELDS = {"actor", "world_id", "label", "class", "priority"}
# NVIDIA's subject fields in their order (prompts/build.py writes the same ones); a labeled thing fills the first four.
SUBJECT_REST = {"orientation": "", "clothing": "", "expression": "", "gender": "", "age": "", "skin_tone_and_texture": "",
                "facial_features": "", "number_of_subjects": 1, "number_of_arms": 0, "number_of_legs": 0}
PLACES = (("Upper left of frame", "Top of frame, centre", "Upper right of frame"),
          ("Left of frame, mid height", "Centre of frame", "Right of frame, mid height"),
          ("Lower left of frame", "Bottom of frame, centre", "Lower right of frame"))
SIZES = ((0.003, "Very small in frame"), (0.02, "Small in frame"), (0.12, "Medium in frame"),
         (float("inf"), "Large, filling much of the frame"))


# ---------------------------------------------------------------- labels.json

def load(path, actors=None):
    """labels.json -> entries in file order, each {"index", "actor", "label", "class", "priority"}. An entry names its
    Unreal actor ("actor") or a world.json id ("world_id") that `actors` {id: actor name} resolves: actor names change
    when the world is regenerated, ids don't."""
    data = json.loads(Path(path).read_text())
    if data.get("version") != VERSION:
        raise ValueError(f"{path}: version must be {VERSION}")
    entries, seen = [], set()
    for k, raw in enumerate(data.get("labels", []), 1):
        if set(raw) - FIELDS:
            raise ValueError(f"{path}: label {k} has unknown fields {sorted(set(raw) - FIELDS)}")
        actor = raw.get("actor")
        if actor is None:
            if raw.get("world_id") is None:
                raise ValueError(f"{path}: label {k} needs an actor or a world_id")
            if not actors or raw["world_id"] not in actors:
                raise ValueError(f"{path}: label {k} names world id {raw['world_id']!r} and no actor is known for it")
            actor = actors[raw["world_id"]]
        entry = {"index": k, "actor": actor, "label": " ".join((raw.get("label") or "").split()),
                 "class": (raw.get("class") or "").strip().lower(), "priority": raw.get("priority", "normal")}
        if actor in seen:
            raise ValueError(f"{path}: {actor} is listed twice")
        if not entry["label"] and not entry["class"]:
            raise ValueError(f"{path}: label {k} ({actor}) has neither a label nor a class")
        if entry["priority"] not in PRIORITIES:
            raise ValueError(f"{path}: label {k} priority must be one of {PRIORITIES}")
        seen.add(actor)
        entries.append(entry)
    return entries


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- the label pass (repo venv, after a capture)

def capture_colors(capture):
    """{actor: (r, g, b)} from a capture sidecar's "mask_colors" (the adapter's MaskColor list). The colour the server
    read back is the one its masks are drawn with; the one we asked for is a fallback for a server that won't say."""
    out = {}
    for m in capture.get("mask_colors", []):
        rgb = m.get("readback_rgb") or m.get("assigned_rgb")
        if rgb:
            out[m["actor"]] = tuple(int(v) for v in rgb[:3])
    return out


def build_pass(clip, entries, colors, labels_file=None):
    """Write clip/labels/NNNN.png (uint16, 0 = no label, k = entry k) and clip/labels_meta.json from the clip's
    segmentation frames, by exact colour match. Returns the meta dict."""
    from PIL import Image
    clip = Path(clip)
    seg_files = sorted((clip / "segmentation").glob("*.png"))
    if not seg_files:
        raise FileNotFoundError(f"no segmentation frames in {clip / 'segmentation'}")
    out = clip / "labels"
    stale = sorted(p.name for p in out.glob("*.png") if not (clip / "segmentation" / p.name).exists())
    if stale:   # an older, longer capture: a paint would read labels for frames this clip doesn't have
        raise ValueError(f"{out} holds frames the clip doesn't ({stale[0]}..{stale[-1]}); move them away first")
    warnings, lookup = [], {}
    labeled = {e["actor"] for e in entries}
    for e in entries:
        rgb = colors.get(e["actor"])
        if rgb is None or rgb == (0, 0, 0):   # black is the mask's "nothing here"
            warnings.append(f"{e['actor']} has no usable mask colour in the capture, so its label never appears")
            continue
        packed = rgb[0] << 16 | rgb[1] << 8 | rgb[2]
        if packed in lookup:
            raise ValueError(f"{e['actor']} and {entries[lookup[packed] - 1]['actor']} share mask colour {rgb}; "
                             "their labels can't be told apart")
        twins = sorted(a for a, c in colors.items() if c == rgb and a not in labeled)
        if twins:
            warnings.append(f"{e['actor']} shares mask colour {rgb} with {twins}, so its label also covers them")
        lookup[packed] = e["index"]
    out.mkdir(exist_ok=True)
    rows = {e["index"]: {"area_px": [], "centroid": [], "bbox": []} for e in entries}
    size = None
    for path in seg_files:
        seg = np.array(Image.open(path).convert("RGB")).astype(np.uint32)
        size = [seg.shape[1], seg.shape[0]]
        packed = seg[..., 0] << 16 | seg[..., 1] << 8 | seg[..., 2]
        lab = np.zeros(packed.shape, np.uint16)
        for colour, k in lookup.items():
            lab[packed == colour] = k
        Image.fromarray(lab).save(out / path.name)
        for k, row in rows.items():
            ys, xs = np.nonzero(lab == k)
            row["area_px"].append(len(xs))
            row["centroid"].append([round(float(xs.mean()), 1), round(float(ys.mean()), 1)] if len(xs) else None)
            row["bbox"].append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None)
    for e in entries:
        if e["actor"] in colors and not any(rows[e["index"]]["area_px"]):
            warnings.append(f"{e['actor']} is never in frame")
    meta = {"version": VERSION, "frames": len(seg_files), "size": size,
            "labels_file": str(labels_file) if labels_file else None,
            "labels_sha256": sha256(labels_file) if labels_file else None, "actors": [e["actor"] for e in entries],
            "labels": [{**e, "color": list(colors[e["actor"]]) if e["actor"] in colors else None,
                        "frames_visible": sum(a > 0 for a in rows[e["index"]]["area_px"]), **rows[e["index"]]}
                       for e in entries],
            "warnings": warnings}
    (clip / "labels_meta.json").write_text(json.dumps(meta) + "\n")
    return meta


def check_meta(frames_dir, entries):
    """The label frames store positions in labels.json, so a reordered or edited file would silently swap labels.
    labels_meta.json (written beside the frames) remembers the order they were built with."""
    meta = Path(frames_dir).parent / "labels_meta.json"
    if meta.exists():
        built = json.loads(meta.read_text())["actors"]
        if built != [e["actor"] for e in entries]:
            raise ValueError(f"{frames_dir} was built for actors {built}, labels.json now lists "
                             f"{[e['actor'] for e in entries]}; rebuild the label pass")


# ---------------------------------------------------------------- label frames -> stats, tokens

def read_frames(folder, width, height, frames=None):
    """The first `frames` label frames (None = all), uint16 [n, height, width]. Nearest neighbour, as the seg control
    itself is resized: an index must never be averaged with its neighbour's."""
    from PIL import Image
    files = sorted(Path(folder).glob("*.png"))[:frames]
    out = np.zeros((len(files), height, width), np.uint16)
    for i, path in enumerate(files):
        lab = np.array(Image.open(path))
        ys = ((np.arange(height) + 0.5) * lab.shape[0] / height).astype(int)
        xs = ((np.arange(width) + 0.5) * lab.shape[1] / width).astype(int)
        out[i] = lab[ys][:, xs]
    return out


def frame_stats(frames, n_labels):
    """Per label and frame: share of the frame it covers, and its centroid as fractions of width and height (nan when
    it isn't in frame). Three float arrays [n_labels, n_frames]."""
    n, h, w = frames.shape
    area = np.zeros((n_labels, n), np.float32)
    cx, cy = np.full((n_labels, n), np.nan, np.float32), np.full((n_labels, n), np.nan, np.float32)
    for i, frame in enumerate(frames):
        for k in np.unique(frame):
            if 0 < k <= n_labels:
                ys, xs = np.nonzero(frame == k)
                area[k - 1, i] = len(xs) / (h * w)
                cx[k - 1, i], cy[k - 1, i] = (xs.mean() + 0.5) / w, (ys.mean() + 0.5) / h
    return area, cx, cy


def token_cover(frames, n_labels):
    """frames uint16 [n, H, W] (one latent frame's video frames; H, W multiples of 16) -> float32 [n_labels, hp, wp]:
    the share of each token's pixels, over those frames, that lie on each label. Row y, column x here is token y*wp + x,
    the order world_transfer.patchify packs them in. An odd latent height or width gives the last row or column of
    tokens half a block of zero padding; that half isn't picture, so the share is taken over the real pixels only."""
    n, h, w = frames.shape
    hp, wp = -(-h // TOKEN), -(-w // TOKEN)
    padded = np.zeros((n, hp * TOKEN, wp * TOKEN), np.uint16)
    padded[:, :h, :w] = frames
    real = np.zeros((hp * TOKEN, wp * TOKEN), np.float32)
    real[:h, :w] = 1
    count = real.reshape(hp, TOKEN, wp, TOKEN).sum((1, 3)) * n
    cover = np.zeros((n_labels, hp, wp), np.float32)
    for k in np.unique(padded):
        if 0 < k <= n_labels:
            cover[k - 1] = (padded == k).reshape(n, hp, TOKEN, wp, TOKEN).sum((0, 2, 4)) / count
    return cover


def regions(cover, tau):
    """cover [K, hp, wp] -> (inside bool [K, hp*wp], fell_back bool [K]). A token belongs to a label when at least `tau`
    of it lies on the label. A label that is in frame but under tau everywhere (smaller than a token) keeps its one
    best token, so a small object still gets something; fell_back marks those."""
    flat = cover.reshape(len(cover), cover.shape[1] * cover.shape[2])   # not -1: there may be no labels
    inside = flat >= tau
    fell_back = ~inside.any(1) & (flat.max(1) > 0)
    for k in np.flatnonzero(fell_back):
        inside[k, flat[k].argmax()] = True
    return inside, fell_back


# ---------------------------------------------------------------- caption (Tier A)

def choose(entries, area, max_labels=6):
    """Which labels the caption names: those with text that are in frame at some point of the paint, heroes first, then
    by mean area; at most max_labels (0 = no cap). Returns (chosen, dropped), dropped as {"actor", "why"}."""
    chosen, dropped = [], []
    for e in entries:
        if not e["label"]:
            continue   # watched only
        if not area[e["index"] - 1].any():
            dropped.append({"actor": e["actor"], "why": "never in frame"})
        else:
            chosen.append(e)
    chosen.sort(key=lambda e: (e["priority"] != "hero", -float(area[e["index"] - 1].mean())))
    if max_labels and len(chosen) > max_labels:
        dropped += [{"actor": e["actor"], "why": f"over the cap of {max_labels} labels"} for e in chosen[max_labels:]]
        chosen = chosen[:max_labels]
    return chosen, dropped


def _place(x, y):
    return PLACES[min(2, int(y * 3))][min(2, int(x * 3))]


def subject(entry, area, cx, cy):
    """One caption subject for a labeled actor, in NVIDIA's subject format. area, cx, cy: its rows of frame_stats."""
    seen = np.flatnonzero(area > 0)
    first, last = _place(cx[seen[0]], cy[seen[0]]), _place(cx[seen[-1]], cy[seen[-1]])
    where = first if first == last else f"{first}, moving to the {last[0].lower()}{last[1:]}"
    share = float(np.median(area[seen]))
    return {"description": entry["label"], "appearance_details": "", "location": where,
            "relative_size": next(words for limit, words in SIZES if share < limit), **SUBJECT_REST}


def caption(prompt, subjects):
    """The structured caption with the label subjects appended to its `subjects` list, as one JSON string."""
    try:
        obj = json.loads(prompt)
    except (ValueError, TypeError):
        obj = None
    if not isinstance(obj, dict):
        raise ValueError("labels need the structured JSON caption (prompts/README.md): a plain-text prompt has no "
                         "subjects list to put them in")
    obj = {"subjects": [], **obj}   # NVIDIA's captions lead with subjects
    obj["subjects"] = list(obj["subjects"] or []) + subjects
    return json.dumps(obj)


# ---------------------------------------------------------------- spans and the mask (Tier B)

def find_spans(chat, offsets, subjects):
    """Where each label subject's description sits among the caption's tokens: [(start, end)] token indices, end
    exclusive, in the order of `subjects`. chat is the chat-templated caption and offsets each token's (start, end)
    characters in it (world_transfer.token_offsets). Each subject is found whole, in order, so two actors with the same
    label text each get their own span."""
    spans, cursor = [], 0
    for s in subjects:
        whole = json.dumps(s)   # how format_prompt and caption() write a subject inside the caption
        at = chat.find(whole, cursor)
        if at < 0:
            raise ValueError(f"label subject not found in the caption text: {s['description']!r}")
        a = at + len('{"description": "')
        b = a + len(json.dumps(s["description"])) - 2
        tokens = [i for i, (x, y) in enumerate(offsets) if x < b and y > a]
        if not tokens or offsets[-1][1] < b:
            raise ValueError(f"the caption was cut off before label {s['description']!r}; shorten the caption")
        spans.append((tokens[0], tokens[-1] + 1))
        cursor = at + len(whole)
    return spans


def text_mask(spans, inside, n_text, mode="hard", beta=5.0):
    """The additive attention bias over the caption's keys for one latent frame: float32 [N, n_text], row = picture
    token, column = text token. hard: -inf where a token outside label k's region meets label k's words. soft: -beta
    there and +beta inside. Every other column stays 0, so each token always reads the rest of the caption. Returns None
    when nothing is biased (every label covers the whole frame), which keeps that paint on the unmasked path."""
    if mode not in ("hard", "soft"):
        raise ValueError(f"mode must be hard or soft, got {mode!r}")
    mask = np.zeros((inside.shape[1], n_text), np.float32)
    for (s, e), rows in zip(spans, inside, strict=True):
        if mode == "hard":
            mask[~rows, s:e] = -np.inf
        else:
            mask[~rows, s:e] = -beta
            mask[rows, s:e] = beta
    return mask if mask.any() else None


class Paint:
    """One paint's labels: which the caption names, where their words sit in the text, and which tokens of each latent
    frame may read them. world_transfer.run builds one when --labels is given."""

    def __init__(self, labels_file, frames_dir, width, height, frame_index, steps=2, tau=0.25, mode="hard", beta=5.0,
                 store=False, max_labels=6):
        """frame_index: for each control frame the paint reads (after its reflect padding), the label frame that
        belongs to it. steps: how many of the denoise steps are masked, from the first; 0 = caption only (Tier A).
        store: also mask the clean pass whose keys become history."""
        self.file, self.frames_dir = Path(labels_file), Path(frames_dir)
        self.entries = load(self.file)
        self.steps, self.store, self.mode, self.beta, self.tau, self.max_labels = steps, bool(store), mode, beta, tau, max_labels
        check_meta(self.frames_dir, self.entries)
        frame_index = np.asarray(frame_index)
        need = int(frame_index.max()) + 1
        frames = read_frames(self.frames_dir, width, height, need)
        if len(frames) < need:
            raise ValueError(f"{self.frames_dir} has {len(frames)} label frames, the paint needs {need}")
        if frames.max() > len(self.entries):
            raise ValueError(f"{self.frames_dir} holds label {int(frames.max())}, {self.file} lists {len(self.entries)}")
        area, cx, cy = frame_stats(frames, len(self.entries))
        self.chosen, self.dropped = choose(self.entries, area, max_labels)
        rows = [e["index"] - 1 for e in self.chosen]
        self.subjects = [subject(e, area[r], cx[r], cy[r]) for e, r in zip(self.chosen, rows, strict=True)]
        self.inside, self.fell_back = [], []
        for f in range(1 + (len(frame_index) - 1) // TCF):   # latent 0 is frame 0 alone, latent f frames 4f-3..4f
            idx = frame_index[:1] if f == 0 else frame_index[TCF * f - 3:TCF * f + 1]
            inside, fell_back = regions(token_cover(frames[idx], len(self.entries))[rows], tau)
            self.inside.append(inside)
            self.fell_back.append(fell_back)
        self.grid = [-(-height // TOKEN), -(-width // TOKEN)]
        self.spans, self.n_text = None, None

    def prompt(self, base):
        """The caption the paint encodes. With no label in frame it is `base` untouched, byte for byte."""
        return caption(base, self.subjects) if self.subjects else base

    def bind(self, chat, offsets, n_text):
        """Find the labels' token spans in the encoded caption. n_text: the text cache's length (the mask's width)."""
        self.spans, self.n_text = find_spans(chat, offsets, self.subjects), n_text

    def mask(self, f):
        """text_mask for latent frame f, or None when there is nothing to mask."""
        if not self.chosen:
            return None
        return text_mask(self.spans, self.inside[f], self.n_text, self.mode, self.beta)

    def identity(self):
        """What goes in the run manifest: enough to tell which labels and mask settings painted a video."""
        return {"file": str(self.file), "sha256": sha256(self.file), "count": len(self.entries),
                "named": len(self.chosen), "steps": self.steps, "mode": self.mode,
                "beta": self.beta if self.mode == "soft" else None, "tau": self.tau, "store": self.store,
                "max": self.max_labels}

    def report(self):
        """The sidecar's "labels" block."""
        from kokopelli.wm.controls.prompts.build import check as banned_words
        counts = np.array([inside.sum(1) for inside in self.inside]).reshape(len(self.inside), len(self.chosen))
        fell = np.array(self.fell_back).reshape(len(self.inside), len(self.chosen))
        named = []
        for j, e in enumerate(self.chosen):
            named.append({"actor": e["actor"], "label": e["label"], "class": e["class"], "priority": e["priority"],
                          "location": self.subjects[j]["location"], "relative_size": self.subjects[j]["relative_size"],
                          "span": list(self.spans[j]) if self.spans else None,
                          "tokens": {"min": int(counts[:, j].min()), "median": float(np.median(counts[:, j])),
                                     "max": int(counts[:, j].max())},
                          "latents_in_frame": int((counts[:, j] > 0).sum()),
                          "latents_under_one_token": int(fell[:, j].sum()),
                          "banned_words": banned_words(e["label"])})
        masked = self.mode == "hard" and (self.steps > 0 or self.store)
        return {**self.identity(), "frames_dir": str(self.frames_dir), "grid": self.grid, "named_labels": named,
                "dropped": self.dropped, "watched": [e["actor"] for e in self.entries if not e["label"]],
                # prompts/build.py bans words that pulled whole frames toward illustration ("balloon"). A label may
                # carry one; whether the rest of the frame can read it depends on the mask.
                "banned_words_reach_whole_frame": bool(any(n["banned_words"] for n in named)) and not masked}


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write labels/NNNN.png and labels_meta.json for a captured clip")
    b.add_argument("--clip", required=True, help="clip folder with segmentation/NNNN.png")
    b.add_argument("--labels", required=True, help="labels.json")
    b.add_argument("--capture", help="capture sidecar holding mask_colors (default: <clip>/capture.json)")
    args = ap.parse_args(argv)
    clip = Path(args.clip)
    capture = json.loads(Path(args.capture or clip / "capture.json").read_text())
    meta = build_pass(clip, load(args.labels), capture_colors(capture), args.labels)
    for row in meta["labels"]:
        print(f"{row['index']:3d} {row['actor']}: in {row['frames_visible']}/{meta['frames']} frames, "
              f"up to {max(row['area_px'])} px")
    for w in meta["warnings"]:
        print(f"warning: {w}")
    print(f"wrote {clip / 'labels'} and {clip / 'labels_meta.json'}")


if __name__ == "__main__":
    main()
