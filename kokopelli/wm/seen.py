"""What the agent may be told it sees: things the sim says are there, kept only if a detector finds them in the painted frame.

    from kokopelli.wm import seen
    kept = seen.seen("frames/seen_0004.png", [seen.Candidate("teo", "a person")])

The sim knows where everything is; the world model (Cosmos) paints the picture the agent actually gets, and it does not
always paint what the sim holds. Telling the agent about something the picture doesn't show is a leak. seen() closes it
from the world-model side: the caller hands over the sim's candidates and the painted frame, an open-vocabulary detector
looks at the frame, and each candidate is either confirmed (returned as a Seen with the detector's box and score) or
dropped. It never returns an id that wasn't a candidate, so the detector cannot add things to the world.

Matching, in confirm():
  - a detection only counts for a candidate with the same label, at or above the score threshold;
  - a candidate that carries a box (where the sim's segmentation or geometry puts it on screen) needs a detection that
    overlaps that box; one without a box takes the best detection left;
  - one detection confirms one candidate, so two people need two detected people. Without boxes the detector can't
    tell which is which: candidates are served in the order given, so put the nearest first.

Backends (kokopelli.settings.SEEN["backend"]), each loaded the first time it is needed:
  owlv2, grounding_dino, florence2 (its <OD> task), florence2_ground (its phrase-grounding task). All four run through
  `transformers` on torch, which the main .venv doesn't have, so they run in a worker process under
  SEEN["torch_python"] (simworld/.venv by default, which has both) and answer over a pipe. This file is that worker too
  (`python -m kokopelli.wm.seen --worker owlv2`), so it stays importable on Python 3.10 and imports nothing but settings.

A detector is a model: outside tests, run anything that reaches default_detector() through the GPU queue (kokopelli/ops/gpu.py).
Tests pass their own `detector=` and never load one.
"""
import argparse
import atexit
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from kokopelli import settings

Box = tuple[float, float, float, float]   # x0, y0, x1, y1 in pixels of the frame

# Checkpoints as read and recorded in docs/log/sensations/2026-11-11-seen.md (licences read 2026-11-10). Only safetensors
# weights are loaded, from the Hugging Face cache, at these exact revisions, with no network and no remote code.
BACKENDS: dict[str, dict[str, str]] = {
    "owlv2": {"model": "OWLv2 base (patch 16, ensemble)", "repo": "google/owlv2-base-patch16-ensemble",
              "revision": "cfd3195ba4ea9592eec887ded089f4c08eff231d", "licence": "Apache-2.0", "precision": "float32"},
    "grounding_dino": {"model": "Grounding DINO tiny", "repo": "IDEA-Research/grounding-dino-tiny",
                       "revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71", "licence": "Apache-2.0", "precision": "float32"},
    "florence2": {"model": "Florence-2-base, <OD> task", "repo": "florence-community/Florence-2-base",
                  "revision": "00921df66db728a9ceb750f5eca43e5c203a2051", "licence": "MIT", "precision": "float32"},
    "florence2_ground": {"model": "Florence-2-base, <CAPTION_TO_PHRASE_GROUNDING> task", "repo": "florence-community/Florence-2-base",
                         "revision": "00921df66db728a9ceb750f5eca43e5c203a2051", "licence": "MIT", "precision": "float32"},
}
FLOOR = 0.05   # the worker returns every detection down to this score; seen() applies the real threshold
# Florence-2's <OD> task names things from its own vocabulary, so a candidate label is matched through these.
OD_NAMES = {"person": ("person", "man", "woman", "boy", "girl", "people", "human")}
ARTICLES = ("a ", "an ", "the ")


@dataclass(frozen=True)
class Candidate:
    """Something the sim says could be in view. label is the words the detector looks for; box is optional."""
    id: str
    label: str
    box: Box | None = None


@dataclass(frozen=True)
class Detection:
    label: str
    box: Box
    score: float


@dataclass(frozen=True)
class Seen:
    """A candidate the detector found in the painted frame, with the detector's own box and score."""
    id: str
    label: str
    box: Box
    score: float


class Detector(Protocol):
    def detect(self, frame: Any, labels: list[str]) -> list[Detection]: ...


def iou(a: Box, b: Box) -> float:
    """Overlap of two boxes as a share of the area they cover together: 1 is the same box, 0 is no overlap."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    both = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / both if both > 0 else 0.0


def confirm(candidates: list[Candidate], detections: list[Detection], threshold: float, min_iou: float) -> list[Seen]:
    """The filter: which candidates the detections confirm. Pure, so tests need no detector."""
    ids = [c.id for c in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError(f"candidate ids must be unique, got {ids}")
    free = [d for d in detections if d.score >= threshold]
    found: dict[str, Seen] = {}
    # Candidates with a box choose first: their match depends on place, so a free-for-all must not take it from them.
    for c in sorted(candidates, key=lambda c: c.box is None):
        if c.box is None:
            fits = [(d.score, k) for k, d in enumerate(free) if d.label == c.label]
        else:
            fits = [(iou(c.box, d.box), k) for k, d in enumerate(free) if d.label == c.label and iou(c.box, d.box) >= min_iou]
        if fits:
            d = free.pop(max(fits)[1])
            found[c.id] = Seen(c.id, c.label, d.box, d.score)
    return [found[c.id] for c in candidates if c.id in found]


def seen(frame: Any, candidates: list[Candidate], detector: Detector | None = None,
         threshold: float | None = None, min_iou: float | None = None) -> list[Seen]:
    """The candidates that are really in the painted frame, in the order given. frame is a path, a PIL image or an array."""
    candidates = list(candidates)
    if not candidates:
        return []   # nothing to confirm, so no model is loaded
    labels = sorted({c.label for c in candidates})
    found = (detector or default_detector()).detect(frame, labels)
    return confirm(candidates, [d for d in found if d.label in labels],
                   settings.SEEN["threshold"] if threshold is None else threshold,
                   settings.SEEN["min_iou"] if min_iou is None else min_iou)


# --- the worker's side of the pipe: runs under SEEN["torch_python"], one model, one request per line

def match_label(found: str, labels: list[str]) -> str | None:
    """The asked label a detector's own wording stands for, or None when it's none or more than one of them."""
    found = found.strip().lower()
    hits = [lab for lab in labels if lab.lower() == found]
    if not hits:
        hits = [lab for lab in labels if found and (found in lab.lower() or lab.lower() in found)]
    return hits[0] if len(hits) == 1 else None


def od_label(found: str, labels: list[str]) -> str | None:
    found = found.strip().lower()
    for lab in labels:
        noun = lab.lower()
        for article in ARTICLES:
            noun = noun.removeprefix(article)
        if found in OD_NAMES.get(noun, (noun,)):
            return lab
    return None


def load_torch_detector(backend: str, device: str = "auto"):
    """Load one backend with transformers on torch; returns detect(image, labels) -> [(label, box, score)] and the device."""
    torch = importlib.import_module("torch")          # not in the main .venv; importlib keeps the type checker out of it
    tf = importlib.import_module("transformers")
    spec = BACKENDS[backend]
    kw = {"revision": spec["revision"], "local_files_only": True}
    dev = device if device != "auto" else ("mps" if torch.backends.mps.is_available() else "cpu")

    if backend == "owlv2":
        proc = tf.Owlv2Processor.from_pretrained(spec["repo"], **kw)
        model = tf.Owlv2ForObjectDetection.from_pretrained(spec["repo"], **kw).to(dev).eval()

        def owl(image, labels):
            inputs = proc(text=[labels], images=image, return_tensors="pt").to(dev)
            with torch.no_grad():
                out = model(**inputs)
            res = proc.post_process_grounded_object_detection(outputs=out, threshold=FLOOR, text_labels=[labels],
                                                              target_sizes=[(image.height, image.width)])[0]
            return [(lab, box.tolist(), float(s)) for lab, box, s in zip(res["text_labels"], res["boxes"], res["scores"], strict=True)]
        return owl, dev

    if backend == "grounding_dino":
        proc = tf.AutoProcessor.from_pretrained(spec["repo"], **kw)
        model = tf.GroundingDinoForObjectDetection.from_pretrained(spec["repo"], **kw).to(dev).eval()

        def dino(image, labels):
            found = []
            for label in labels:   # one pass per label: asked together, weak boxes come back named after several labels at once
                inputs = proc(images=[image], text=[[label.replace(".", " ")]], return_tensors="pt").to(dev)
                with torch.no_grad():
                    out = model(**inputs)
                res = proc.post_process_grounded_object_detection(out, inputs.input_ids, threshold=FLOOR, text_threshold=FLOOR,
                                                                  target_sizes=[(image.height, image.width)])[0]
                found += [(label, box.tolist(), float(s)) for box, s in zip(res["boxes"], res["scores"], strict=True)]
            return found
        return dino, dev

    if backend in ("florence2", "florence2_ground"):
        proc = tf.AutoProcessor.from_pretrained(spec["repo"], **kw)
        model = tf.Florence2ForConditionalGeneration.from_pretrained(spec["repo"], **kw).to(dev).eval()
        task = "<OD>" if backend == "florence2" else "<CAPTION_TO_PHRASE_GROUNDING>"

        def florence(image, labels):
            asked = [lab.replace(".", " ") for lab in labels]
            text = task if backend == "florence2" else task + ". ".join(asked)
            inputs = proc(text=[text], images=[image], return_tensors="pt").to(dev)
            with torch.no_grad():
                ids = model.generate(**inputs, max_new_tokens=256, num_beams=3, do_sample=False)
            raw = proc.batch_decode(ids, skip_special_tokens=False)[0]
            res = proc.post_process_generation(raw, task=task, image_size=(image.width, image.height))[task]
            name = od_label if backend == "florence2" else match_label
            named = [(name(lab, asked), [float(v) for v in box]) for lab, box in zip(res["labels"], res["bboxes"], strict=True)]
            # Florence-2 writes boxes as text and gives no confidence, so every box it writes scores 1.0.
            return [(labels[asked.index(lab)], box, 1.0) for lab, box in named if lab is not None]
        return florence, dev

    raise ValueError(f"unknown backend {backend!r}; one of {sorted(BACKENDS)}")


def about(backend: str, **more: Any) -> dict[str, Any]:
    """What a sidecar needs to say about a backend: model, repo, revision, licence, precision, runtime."""
    return {**BACKENDS[backend], "backend": backend, "weights": f"{BACKENDS[backend]['repo']}@{BACKENDS[backend]['revision']}",
            "runtime": "transformers on torch, in a worker process (kokopelli/wm/seen.py --worker)", **more}


def worker(backend: str, device: str) -> None:
    """Answer one JSON request per line on stdin: {"image": path, "labels": [...]} -> {"detections": [...], "seconds": s};
    {"stats": true} -> the worker's memory so far."""
    pipe = sys.stdout
    sys.stdout = sys.stderr   # libraries print while loading; the pipe carries only JSON
    Image = importlib.import_module("PIL.Image")
    t0 = time.time()
    detect, dev = load_torch_detector(backend, device)
    versions = {name: importlib.import_module(name).__version__ for name in ("torch", "transformers")}
    print(json.dumps({"ready": True, "load_seconds": round(time.time() - t0, 2),
                      "about": about(backend, device=dev, python=sys.version.split()[0], **versions)}), file=pipe, flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            ask = json.loads(line)
            if ask.get("stats"):   # memory so far: this process's peak, and what Metal holds for the model (0 on cpu)
                peak = importlib.import_module("resource").getrusage(0).ru_maxrss / 1e9   # macOS counts bytes
                metal = importlib.import_module("torch").mps.driver_allocated_memory() / 1e9 if dev == "mps" else 0.0
                print(json.dumps({"peak_rss_gb": round(peak, 2), "metal_gb": round(metal, 2)}), file=pipe, flush=True)
                continue
            image = Image.open(ask["image"]).convert("RGB")
            t = time.time()
            found = detect(image, list(ask["labels"]))
            reply = {"detections": [{"label": lab, "box": box, "score": s} for lab, box, s in found], "seconds": round(time.time() - t, 4)}
        except Exception as error:   # the parent decides what a failed frame means; the worker stays up
            reply = {"error": f"{type(error).__name__}: {error}"}
        print(json.dumps(reply), file=pipe, flush=True)


# --- the caller's side: start the worker when first needed, one at a time

class WorkerDetector:
    """A backend living in its own process. Nothing starts until the first detect()."""

    def __init__(self, backend: str, python: str | None = None, device: str | None = None):
        if backend not in BACKENDS:
            raise ValueError(f"unknown backend {backend!r}; one of {sorted(BACKENDS)}")
        self.backend = backend
        self.python = str(python or settings.SEEN["torch_python"])
        self.device = device or settings.SEEN["device"]
        self.proc: subprocess.Popen | None = None
        self.info: dict[str, Any] = {}
        self.last_seconds = 0.0
        self.tmp: str | None = None

    def start(self) -> dict[str, Any]:
        if self.proc is None:
            env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1", "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
            self.proc = subprocess.Popen([self.python, "-m", "kokopelli.wm.seen", "--worker", self.backend, "--device", self.device],
                                         cwd=settings.ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            self.info = self._read()
            atexit.register(self.close)
        return self.info

    def _read(self) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            code = self.proc.wait()
            self.proc = None
            raise RuntimeError(f"the {self.backend} worker under {self.python} stopped (exit {code}); its error is on stderr")
        return json.loads(line)

    def _path(self, frame: Any) -> str:
        if isinstance(frame, str | Path):
            return str(frame)
        Image = importlib.import_module("PIL.Image")
        if self.tmp is None:
            self.tmp = tempfile.mkdtemp(prefix="koko_seen_")
        path = str(Path(self.tmp) / "frame.png")
        (frame if hasattr(frame, "save") else Image.fromarray(frame)).save(path)
        return path

    def detect(self, frame: Any, labels: list[str]) -> list[Detection]:
        self.start()
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"image": self._path(frame), "labels": labels}) + "\n")
        self.proc.stdin.flush()
        reply = self._read()
        if "error" in reply:
            raise RuntimeError(f"{self.backend}: {reply['error']}")
        self.last_seconds = reply["seconds"]
        return [Detection(d["label"], (d["box"][0], d["box"][1], d["box"][2], d["box"][3]), d["score"]) for d in reply["detections"]]

    def stats(self) -> dict[str, Any]:
        """The worker's memory so far, or {} if it was never started."""
        if self.proc is None or self.proc.stdin is None:
            return {}
        self.proc.stdin.write(json.dumps({"stats": True}) + "\n")
        self.proc.stdin.flush()
        return self._read()

    def close(self) -> None:
        if self.proc is not None:
            if self.proc.stdin is not None:
                self.proc.stdin.close()   # the worker's loop ends with its input
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.terminate()     # our own child, by handle; never by name
            self.proc = None


_loaded: WorkerDetector | None = None


def default_detector() -> WorkerDetector:
    """The detector settings.SEEN["backend"] names. Starting it is cheap; the model loads at its first detect()."""
    global _loaded
    if _loaded is None or _loaded.backend != settings.SEEN["backend"]:
        release()
        _loaded = WorkerDetector(settings.SEEN["backend"])
    return _loaded


def release() -> None:
    """Stop the worker and give its memory back (it starts again at the next seen())."""
    global _loaded
    if _loaded is not None:
        _loaded.close()
        _loaded = None


def sidecar(found: list[Seen], backend: str | None = None) -> dict[str, Any]:
    """A record of one seen() call for a log: what was kept and which model said so."""
    name = backend or settings.SEEN["backend"]
    return {"kept": [asdict(s) for s in found], "detector": about(name), "threshold": settings.SEEN["threshold"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", required=True, choices=sorted(BACKENDS), help="serve this backend on stdin/stdout")
    ap.add_argument("--device", default="auto", help="auto (mps if there is one), mps or cpu")
    args = ap.parse_args()
    worker(args.worker, args.device)


if __name__ == "__main__":
    main()
