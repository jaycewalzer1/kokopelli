"""Every model run on this machine, for the dev panel's model runs tab. It only reads: folders, logs and the videos' own headers.

Runs live in several places, one per tool that made them. Each source below knows where its runs are and what to say about them.
A video is served by its id, which is looked up in a fresh listing, so a request can name a run but never a path.
"""
import struct
import time
from pathlib import Path

from life import pipeline
from settings import PIPELINE_PATHS, ROOT

COSMOS_OUTPUTS = Path.home() / "cosmos3" / "outputs"
OUT = ROOT / "out"
EDGE_FILTER = OUT / "edge_filter"
CONTINUOUS = OUT / "continuous_video"
FILTER_TEST = OUT / "filter_test"
# Edge filter files that are what the model was given, not what it made.
FILTER_INPUTS = {"source", "control", "control_pingpong", "mock_sim_edges"}
_durations = {}


def mp4_seconds(path):
    """Length from the mp4's movie header (moov/mvhd), without decoding. None if the file is partial or not an mp4."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _durations:
        _durations[key] = _read_mvhd(path, stat.st_size)
    return _durations[key]


def _boxes(file, start, end):
    """(type, body start, body end) of each box between start and end."""
    at = start
    while at + 8 <= end:
        file.seek(at)
        size, kind = struct.unpack(">I4s", file.read(8))
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", file.read(8))[0], 16
        elif size == 0:
            size = end - at
        if size < header:
            return
        yield kind, at + header, at + size
        at += size


def _read_mvhd(path, size):
    try:
        with open(path, "rb") as file:
            for kind, start, end in _boxes(file, 0, size):
                if kind != b"moov":
                    continue
                for inner, body, _ in _boxes(file, start, end):
                    if inner == b"mvhd":
                        file.seek(body)
                        version = file.read(1)[0]
                        file.seek(body + (20 if version == 1 else 12))
                        scale, length = struct.unpack(">IQ" if version == 1 else ">II", file.read(12 if version == 1 else 8))
                        return round(length / scale, 2) if scale else None
    except (OSError, struct.error, IndexError):
        return None
    return None


def video_facts(path):
    stat = path.stat()
    return {"seconds": mp4_seconds(path), "mb": round(stat.st_size / 1024 ** 2, 1), "at": stat.st_mtime}


def notes(folder):
    """A notes.json beside the videos, {"file stem": "what this run tried"}, says what a run was for."""
    return pipeline.read_json(Path(folder) / "notes.json") or {}


def entry(group, path, name, kind, lines=(), prompt=None, state=None, at=None, video=True):
    """One run. kind is one of TYPES' ids, or mixed; state is running or None."""
    facts = video_facts(path) if video else {"seconds": None, "mb": None, "at": None}
    about = notes(path.parent).get(path.stem) or notes(path.parent.parent).get(name)
    return {"id": f"{group}/{path.relative_to(path.anchor)}" if video else f"{group}/{name}", "group": group, "name": name, "kind": kind,
            "state": state, "prompt": prompt, "about": about, "lines": [line for line in lines if line], "video": video, **facts,
            "at": at or facts["at"], "path": str(path)}


def loop_kind(run):
    if run["wm"] in (None, "mock"):
        return "mock" if run["wm"] == "mock" else "mixed"
    return "cosmos"


def loop_entries(group, folder, module, table, now):
    entries = []
    for run in pipeline.loop_runs(folder, table, now, module):
        path = Path(folder) / run["name"] / "final.mp4"
        lines = [f"{run['done']} of {run['target']} ticks" if run["target"] else f"{run['done']} ticks",
                 f"sim {run['sim']}, world model {run['wm']}, agent {run['agent']}",
                 f"{run['rendered_s']} s rendered per tick" if run["rendered_s"] is not None else None,
                 f"took {run['total_s'] / 60:.0f} min" if run["total_s"] else None]
        state = "running" if run["state"] in ("moving", "alive, quiet") else None
        entries.append(entry(group, path, run["name"], loop_kind(run), lines, state=state, at=run["at"], video=path.is_file()))
    return entries


def writing(table, script):
    """Output files that a running Python script is writing, from its --output option."""
    return {Path(option).name for row in table if pipeline.is_python(row["parts"]) and pipeline.python_target(row["parts"]) == ("script", script)
            and (option := pipeline.option(row["parts"], "--output"))}


def filter_entries(table=()):
    busy = writing(table, "world_filter.py")
    metrics = {row.get("name"): row for row in pipeline.read_rows(EDGE_FILTER / "results.jsonl")}
    entries = []
    for path in sorted(EDGE_FILTER.rglob("*.mp4")):
        row = metrics.get(path.stem, {})
        lines = [f"follows the edges {row['edge_f1_to_control']:.2f} (F1)" if "edge_f1_to_control" in row else None,
                 f"took {row['seconds'] / 60:.1f} min" if row.get("seconds") else None,
                 "from " + path.parent.relative_to(EDGE_FILTER.parent).as_posix()]
        kind = "input" if path.stem in FILTER_INPUTS else "cosmos"
        entries.append(entry("filter", path, path.stem, kind, lines, state="running" if path.name in busy else None))
    return entries


def single_entries():
    entries = [entry("single", path, path.stem, "cosmos", ["from ~/cosmos3/outputs"]) for path in sorted(COSMOS_OUTPUTS.glob("*.mp4"))]
    final = CONTINUOUS / "final.mp4"
    if final.is_file():
        segments = len(list(CONTINUOUS.glob("segment_*.mp4")))
        entries.append(entry("single", final, "continuous_video", "cosmos", [f"{segments} segments, each continuing the last"]))
    return entries


def clip_entries():
    entries = []
    for folder in sorted(OUT.glob("world_data_*")):
        for row in pipeline.read_rows(folder / "manifest.jsonl"):
            path = folder / row.get("file", "")
            if row.get("ok") and path.suffix == ".mp4" and path.is_file():
                lines = [f"{row.get('category')}, seed {row.get('seed')}", f"took {row['seconds']:.0f} s" if row.get("seconds") else None]
                entries.append(entry("clips", path, path.stem, "cosmos", lines, prompt=row.get("prompt")))
    return entries


def filter_test_entries():
    """The sim-to-real test: the SimWorld clip, then one folder per filter run on it. Each run folder's run.json says which
    model made it ({"model": "cosmos" or "sd15", "about": ..., "lines": [...]})."""
    entries = []
    clip = FILTER_TEST / "test_clip"
    capture = pipeline.read_json(clip / "capture.json") or {}
    source = capture.get("route_source") or {**capture.get("qwen_source", {}), "chosen_by": "qwen"}
    said = {"rgb": "What the sim rendered.", "depth": "The sim's own depth, near is bright. A preview, not what a model is given.",
            "segmentation": "Which object each pixel belongs to."}
    for modality, about in said.items():
        path = clip / f"{modality}.mp4"
        if path.is_file():
            lines = [f"{capture.get('frames')} frames at {capture.get('fps')} fps, {'x'.join(map(str, capture.get('size', [])))}",
                     capture.get("place_about"),
                     f"replays Qwen's go_to {source.get('place')} from {source.get('run')}" if source.get("chosen_by") == "qwen"
                     else "route picked by hand, not by the agent"]
            entries.append({**entry("sim", path, f"test_clip {modality}", "sim", lines), "about": about})
    folders = sorted(path for path in FILTER_TEST.iterdir() if path.is_dir() and path != clip) if FILTER_TEST.is_dir() else []
    for folder in folders:
        run = pipeline.read_json(folder / "run.json") or {}
        for path in sorted(folder.glob("*.mp4")):
            entries.append({**entry("sim", path, f"{folder.name} {path.stem}", run.get("model", "cosmos"), run.get("lines", [])),
                            "about": run.get("about")})
    return entries


TYPES = [
    {"id": "cosmos", "name": "Cosmos"},
    {"id": "sd15", "name": "SD1.5"},
    {"id": "sim", "name": "Sim"},
    {"id": "mock", "name": "Mock"},  # mixed runs count here too
    {"id": "input", "name": "Inputs"},
]

GROUPS = [
    {"id": "sim", "name": "Sim-to-real test", "about": "One 10-second SimWorld clip, and each filter run on it to make it look real."},
    {"id": "loop", "name": "Agent loop", "about": "The 30-minute life: the sim, the world model painting it, and the agent acting on what it sees."},
    {"id": "filter", "name": "Edge filter", "about": "The world model painting over the sim's edges, tested on a stand-in clip."},
    {"id": "mind", "name": "Mind runs", "about": "The agent loop with feelings, run on the mock world model so far."},
    {"id": "single", "name": "Single generations", "about": "One-off videos from a prompt or an image, and the long continued video."},
    {"id": "clips", "name": "Collected clips", "about": "Short clips made overnight as world model training and test data."},
]


def collect(paths=PIPELINE_PATHS, now=None):
    now = time.time() if now is None else now
    table = pipeline.process_table()
    readers = {"loop": lambda: loop_entries("loop", Path(paths["agent_loop"]) / "runs", "runtime.run", table, now),
               "mind": lambda: loop_entries("mind", paths["mind"], "mind.run", table, now),
               "filter": lambda: filter_entries(table), "single": single_entries, "clips": clip_entries, "sim": filter_test_entries}
    runs = []
    for group in GROUPS:
        runs += pipeline.safely(readers[group["id"]], [])
    runs.sort(key=lambda run: run["at"] or 0, reverse=True)
    made = [run for run in runs if run["kind"] == "cosmos" and run["seconds"]]
    longest = max(made, key=lambda run: run["seconds"], default=None)
    for run in runs:
        del run["path"]
    return {"groups": GROUPS, "types": TYPES, "runs": runs, "longest": longest and {"name": longest["name"], "seconds": longest["seconds"]}}


def video_file(run_id, paths=PIPELINE_PATHS):
    """The video for a run id from a fresh listing. Anything else raises KeyError."""
    table = []
    readers = {"loop": lambda: loop_entries("loop", Path(paths["agent_loop"]) / "runs", "runtime.run", table, 0),
               "mind": lambda: loop_entries("mind", paths["mind"], "mind.run", table, 0),
               "filter": filter_entries, "single": single_entries, "clips": clip_entries, "sim": filter_test_entries}
    group = run_id.split("/", 1)[0]
    if group not in readers:
        raise KeyError(run_id)
    found = {run["id"]: run for run in readers[group]() if run["video"]}
    return Path(found[run_id]["path"])
