"""The city agent runs in out/city_agents/, for the dev panel's live view. It only reads what kokopelli/agents/live.py writes.

A run is a folder named by its start time. A newer run also has live.json, rewritten every sim step; an older one has
only its transcript and event log, so what live.json would say is worked out from those instead.
A frame is served by run id and file name, both checked against what is really there, so a request never names a path.
"""
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path

from kokopelli.settings import ROOT

RUNS = ROOT / "out" / "city_agents"
RUN_ID = re.compile(r"^\d{8}-\d{6}$")
FRAME = re.compile(r"^(\d{4}|live)\.png$")
# A step takes 5 to 15 s, a slow decision a bit longer. A run that hasn't written for this long has stopped, whatever it says.
LIVE_WITHIN_S = 90

_HEADING = re.compile(r"^(\S+) — step (\d+)$")
_REPLY = re.compile(r"^> \*\*(.+?):\*\* (.*)$")


def _folder(run_id):
    if not isinstance(run_id, str) or not RUN_ID.match(run_id) or not (RUNS / run_id).is_dir():
        raise KeyError(f"no city agent run {run_id!r}")
    return RUNS / run_id


def _read_live(folder):
    try:
        return json.loads((folder / "live.json").read_text())
    except (OSError, ValueError):
        return None


def _age_s(live):
    try:
        return max(0.0, time.time() - datetime.fromisoformat(live["updated"]).timestamp())
    except (KeyError, TypeError, ValueError):
        return None


def is_live(live):
    age = _age_s(live) if live else None
    return bool(live and live.get("running") and age is not None and age <= LIVE_WITHIN_S)


def decisions(text):
    """Each decision in a transcript: when, the frame Qwen saw, its thought, its action, and what people said back."""
    found = []
    for block in text.split("\n### ")[1:]:
        lines = block.split("\n")
        heading = _HEADING.match(lines[0].strip())
        if not heading:
            continue
        entry = {"clock": heading[1], "step": int(heading[2]), "frame": None, "thought": "", "action": None, "replies": [], "notes": []}
        for line in lines[1:]:
            line = line.strip()
            if line == "---":
                break
            if line.startswith("![](frames/") and line.endswith(")"):
                entry["frame"] = Path(line[len("![]("):-1]).name
            elif line.startswith("**→**"):
                raw = line.removeprefix("**→**").strip().strip("`")
                try:
                    entry["action"] = json.loads(raw)
                except ValueError:
                    entry["action"] = {"type": "unreadable", "text": raw}
            elif reply := _REPLY.match(line):
                entry["replies"].append({"name": reply[1], "text": reply[2]})
            elif line.startswith("_(") and line.endswith(")_"):
                entry["notes"].append(line[2:-2])
            elif line.startswith("*") and line.endswith("*") and len(line) > 1 and not line.startswith("**"):
                entry["thought"] = line[1:-1]
        found.append(entry)
    return found


def _header(text):
    """The Who and Situation lines at the top of a transcript."""
    fields = {}
    for key in ("Who", "Situation", "Vision"):
        match = re.search(rf"^\*\*{key}:\*\* (.*)$", text, re.MULTILINE)
        if match:
            fields[key.lower()] = match[1]
    return fields


def trail(folder):
    """Where the agent stood after each step, in metres, from the outcome events. Step n's outcome is the n-th one."""
    points = []
    try:
        with open(folder / "events.jsonl") as file:
            for line in file:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("kind") == "outcome" and isinstance(event.get("at"), list) and len(event["at"]) == 2:
                    points.append([round(event["at"][0], 2), round(event["at"][1], 2)])
    except OSError:
        pass
    return points


def _derived(folder, text, found, points):
    """What live.json would say at the end of an older run that never wrote one."""
    last = found[-1] if found else None
    heading = None
    if len(points) >= 2:
        (x0, y0), (x1, y1) = points[-2], points[-1]
        if (x1, y1) != (x0, y0):
            heading = round(math.degrees(math.atan2(y1 - y0, x1 - x0)), 1)
    return {"run": folder.name, "updated": None, "running": False, **_header(text),
            "step": len(points) or None, "clock": last and last["clock"], "frame": None,
            "agent": {"x_m": points[-1][0], "y_m": points[-1][1], "yaw": heading, "carrying": None, "place": None} if points else None,
            "npcs": [], "objects": [], "route": [], "goal": None,
            "last_thought": last and last["thought"], "last_action": last and last["action"], "last_result": None,
            "heard": [f"{reply['name']}: {reply['text']}" for reply in last["replies"]] if last else [], "diary": [],
            "derived": True}


def listing():
    """Every run, newest first."""
    runs = []
    if RUNS.is_dir():
        for folder in sorted((path for path in RUNS.iterdir() if path.is_dir() and RUN_ID.match(path.name)), reverse=True):
            live = _read_live(folder)
            try:
                count = (folder / "transcript.md").read_text().count("\n### ")
            except OSError:
                count = 0
            runs.append({"run": folder.name, "has_live": live is not None, "live": is_live(live),
                         "running": bool(live and live.get("running")), "updated": live and live.get("updated"),
                         "clock": live and live.get("clock"), "decisions": count})
    return {"runs": runs}


def run(run_id):
    """A run's latest state, its decisions and its trail."""
    folder = _folder(run_id)
    try:
        text = (folder / "transcript.md").read_text()
    except OSError:
        text = ""
    found, points = decisions(text), trail(folder)
    live = _read_live(folder)
    state = {**_header(text), **live, "derived": False} if live else _derived(folder, text, found, points)
    for entry in found:
        entry["has_frame"] = bool(entry["frame"] and FRAME.match(entry["frame"]) and (folder / "frames" / entry["frame"]).is_file())
    state["has_live_frame"] = (folder / "frames" / "live.png").is_file()
    return {"run": folder.name, "live": is_live(live), "age_s": _age_s(live) if live else None, "state": state,
            "decisions": found, "trail": points}


def frame_file(run_id, name):
    """The path of one frame in a run's own frames folder, or KeyError."""
    if not isinstance(name, str) or not FRAME.match(name):
        raise KeyError("not a frame name")
    frames = (_folder(run_id) / "frames").resolve()
    path = (frames / name).resolve()
    if path.parent != frames or not path.is_file():
        raise KeyError("no such frame")
    return path
