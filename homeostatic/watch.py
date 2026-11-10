"""What the dev panel shows of training. It only reads the files runs leave in out/homeostatic, so it can't disturb one."""
import json
import shlex
import subprocess
import time
from pathlib import Path

from core.settings import HOMEOSTATIC_OUT, HOMEOSTATIC_TRAIN, ROOT

RECENT_GROUPS = 12


def read_rows(path):
    """Rows of a log another process is appending to. A last line it's still writing is left for the next read."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return rows


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def trainers(listing):
    """The folder and total updates of every training process in a `ps` listing."""
    found = {}
    for line in listing.splitlines():
        if "homeostatic.train" not in line:
            continue
        try:
            parts = shlex.split(line)
            # A job waiting in the GPU queue has this command on its line too, but it isn't running yet.
            if any(part.endswith("gpu.py") for part in parts):
                continue
            folder = parts[parts.index("homeostatic.train") + 1]
        except (ValueError, IndexError):
            continue
        iters = int(parts[parts.index("--iters") + 1]) if "--iters" in parts else HOMEOSTATIC_TRAIN["iters"]
        found[(ROOT / folder).resolve()] = iters
    return found


def running_trainers():
    return trainers(subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True).stdout)


def run_folders(out):
    """Every folder a training run has logged to, newest first. Names come from here, never straight from a request."""
    folders = [path.parent for path in Path(out).rglob("train.jsonl")] + [path.parent for path in Path(out).rglob("rollouts.jsonl")]
    folders = sorted(set(folders), key=lambda folder: max(path.stat().st_mtime for path in folder.iterdir()), reverse=True)
    return {folder.relative_to(out).as_posix(): folder for folder in folders}


def state_of(folder, running):
    resolved = folder.resolve()
    if resolved in running:
        return "training"
    return "finished" if (folder / "finished").exists() else "stopped"


def list_runs(out=HOMEOSTATIC_OUT, running=None):
    running = running_trainers() if running is None else running
    return [{"name": name, "state": state_of(folder, running)} for name, folder in run_folders(out).items()]


def collapsed(train, window=5):
    """Whether the model has given one action across all states for several updates, so it isn't responding to the state."""
    recent = train[-window:]
    return len(recent) == window and all(row.get("train_distinct_actions", 2) <= 1 for row in recent)


def describe_run(name, out=HOMEOSTATIC_OUT, running=None):
    running = running_trainers() if running is None else running
    folder = run_folders(out)[name]
    train = read_rows(folder / "train.jsonl")
    state = state_of(folder, running)
    done = train[-1]["iteration"] if train else 0
    updated = max(path.stat().st_mtime for path in folder.iterdir())
    return {"name": name, "state": state, "done": done, "total": running.get(folder.resolve(), done), "seconds_since_update": time.time() - updated,
            "collapsed": collapsed(train), "train": train, "validation": read_rows(folder / "validation.jsonl"),
            "validating": read_json(folder / "validating.json"), "groups": read_rows(folder / "rollouts.jsonl")[-RECENT_GROUPS:][::-1]}


def baselines(out=HOMEOSTATIC_OUT):
    """How untrained policies score on the validation lives, once measured. See homeostatic.evaluate --validation."""
    return read_json(Path(out) / "baselines-validation.json") or {}


def held_out_results(out=HOMEOSTATIC_OUT):
    """Summaries of whatever has finished on the test lives. Tables are made only from these saved files."""
    results = {}
    for path in sorted((Path(out) / "results").glob("*.json")):
        saved = read_json(path)
        if saved:
            results[path.stem] = saved["summary"]
    return results
