"""The dev panel's armed-bystander page: every run of experiments/bystander, and every decision in it in full. It only
reads out/bystander/.

    out/bystander/<run>/run.json        the model, the sampling, and who the agent was told it is
    out/bystander/<run>/results.jsonl   one row per decision: what it was told, its whole reply, how the reply was read

A request names a run, which is matched against a fresh listing, so it can never name a path. The gift-card benchmark
writes runs in the same shape, so benchmarks.py reads both through `out`.
"""
import json
from pathlib import Path

from kokopelli.settings import ROOT

OUT = ROOT / "out" / "bystander"
RECORD = ("model", "weights", "quantization", "temperature", "top_p", "top_k", "max_tokens", "seeds", "scenes", "started", "finished")
DECISION = ("scene", "seed", "outcome", "valid", "action", "thought", "error", "action_order", "prompt", "raw", "seconds")


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _decisions(folder):
    try:
        lines = (folder / "results.jsonl").read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:   # a run still writing can leave half a line
            continue
    return rows


def _runs(out):
    """{run name: (folder, record)} for every folder under `out` that holds a run's record."""
    if not out.is_dir():
        return {}
    found = ((folder, _json(folder / "run.json")) for folder in sorted(out.iterdir()) if folder.is_dir())
    return {folder.name: (folder, record) for folder, record in found if isinstance(record, dict)}


def _describe(name, folder, record, decisions):
    return {"id": name, "at": max((path.stat().st_mtime for path in folder.iterdir()), default=0), "count": len(decisions),
            # A mock run answers with canned replies. The page says so, and never shows one as a model's.
            "real": record.get("model") != "mock", **{key: record.get(key) for key in RECORD}}


def listing(out: Path | None = None) -> dict:
    """Every run, newest first, without its decisions."""
    runs = [_describe(name, folder, record, _decisions(folder)) for name, (folder, record) in _runs(out or OUT).items()]
    return {"runs": sorted(runs, key=lambda run: -run["at"])}


def run(run_id: str, out: Path | None = None) -> dict:
    """One run with every decision in full, or KeyError."""
    known = _runs(out or OUT)
    if run_id not in known:
        raise KeyError(f"no run {run_id!r}")
    folder, record = known[run_id]
    decisions = _decisions(folder)
    return {**_describe(run_id, folder, record, decisions), "system": record.get("system"), "note": record.get("prompt_note"),
            "decisions": [{key: row.get(key) for key in DECISION} for row in decisions]}
