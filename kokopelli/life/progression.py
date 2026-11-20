"""The dev panel's progression page: the judgment plan (experiments/judgment/plan.json), its phases, gates, tasks and
open decisions. The page changes only a task's status or note and a decision's answer; everything else is edited in the file.
"""
import json
from pathlib import Path

from kokopelli.settings import ROOT

PLAN = ROOT / "experiments" / "judgment" / "plan.json"
STATUSES = ("todo", "doing", "done", "skipped", "blocked")


def plan(path: Path | None = None) -> dict:
    return json.loads((path or PLAN).read_text())


def _save(data: dict, path: Path):
    # Written beside the plan and renamed over it, so a crash never leaves half a file.
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def edit(body: dict, path: Path | None = None) -> dict:
    """One change: {"kind": "task", "id", "status"?, "note"?} or {"kind": "decision", "id", "answer"}. Returns the whole plan."""
    path = path or PLAN
    data = plan(path)
    if body.get("kind") == "task":
        task = next((t for phase in data["phases"] for t in phase["tasks"] if t["id"] == body.get("id")), None)
        if task is None:
            raise KeyError(f"no task {body.get('id')!r}")
        if "status" in body:
            if body["status"] not in STATUSES:
                raise ValueError(f"status must be one of {', '.join(STATUSES)}")
            task["status"] = body["status"]
        if "note" in body:
            task["note"] = str(body["note"])
    elif body.get("kind") == "decision":
        decision = next((d for d in data["decisions"] if d["id"] == body.get("id")), None)
        if decision is None:
            raise KeyError(f"no decision {body.get('id')!r}")
        decision["answer"] = str(body.get("answer", ""))
    else:
        raise ValueError("kind must be task or decision")
    _save(data, path)
    return data
