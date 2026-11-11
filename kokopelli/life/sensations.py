"""The dev panel's sensations page: every sensation sweep and every hunger video run. It only reads out/sensation/.

    out/sensation/<sweep run>/report.json        experiments/sensation/sweep.py
    out/sensation/videos/<run>/<level>/          kokopelli/agents/egg_wm.py (a link to the run folder) + kokopelli/body/overlay.py
    out/sensation/videos/<run>/hunger_triptych.mp4

A video is served by (run, level, kind), each checked against a fresh listing and a fixed file name, so a request can
name a run but never a path.
"""
import json
from pathlib import Path

from kokopelli.settings import ROOT

OUT = ROOT / "out" / "sensation"
VIDEOS = OUT / "videos"
LEVELS = ("full", "half", "starving")
# What each kind of video is called on disk. "plain" is the painted film with no panel.
FILES = {"overlay": "overlay.mp4", "voice": "overlay_voice.mp4", "plain": "world_model.mp4"}


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _sweeps():
    runs = []
    if not OUT.exists():
        return runs
    for folder in sorted(OUT.iterdir()):
        report = _json(folder / "report.json") if folder.is_dir() and folder.name != "videos" else None
        if not report:
            continue
        record = report["record"]
        cells = {f"{c['arm']}|{c['level']}": {"gave": c["gave"], "shared": c["shared"], "n": c["n"], "invalid": c["invalid"]}
                 for c in report["cells"]}
        runs.append({"id": folder.name, "at": (folder / "report.json").stat().st_mtime, "sweep": record["sweep"],
                     "levels": record["levels"], "arms": record["arms"], "samples": record["samples"],
                     "backend": record["backend"], "arm": record["arm"], "real": record["real"],
                     "model": (record.get("model") or {}).get("model_id"), "cells": cells,
                     "verdicts": {arm: {"change": a["change"], "verdict": a["verdict"]} for arm, a in report["arms"].items()},
                     "anchor": report["anchor"],
                     # Per-scene words, absent from reports written before the scenes registry (the page then uses
                     # the hunger scene's): "gave" above is whatever the scene's primary score is.
                     "paraphrases": record.get("paraphrases"), "words": report.get("words")})
    return sorted(runs, key=lambda run: -run["at"])


def _videos():
    runs = []
    if not VIDEOS.exists():
        return runs
    for folder in sorted(VIDEOS.iterdir()):
        if not folder.is_dir():
            continue
        levels = {}
        for level in LEVELS:
            run = folder / level
            if not run.exists():
                continue
            result = _json(run / "egg.json") or {}
            levels[level] = {"outcome": result.get("outcome"), "food": result.get("food_at_start"),
                             "first": (result.get("first_response") or {}).get("action"),
                             "thought": (result.get("first_response") or {}).get("thought"),
                             "has": {kind: (run / name).exists() for kind, name in FILES.items()}}
        if not levels:
            continue
        sidecar = _json(folder / "hunger_triptych.mp4.json") or {}
        arm = next((result.get("arm") for level in LEVELS if (result := _json(folder / level / "egg.json"))), None)
        runs.append({"id": folder.name, "at": folder.stat().st_mtime, "arm": arm, "levels": levels,
                     "triptych": (folder / "hunger_triptych.mp4").exists(), "seconds": sidecar.get("seconds")})
    return sorted(runs, key=lambda run: -run["at"])


def listing() -> dict:
    return {"sweeps": _sweeps(), "videos": _videos()}


def video_file(run: str, kind: str, level: str | None = None) -> Path:
    """The file for a video run, or KeyError. Names come from the listing; the path is built here, never taken."""
    known = {video["id"]: video for video in _videos()}
    if run not in known:
        raise KeyError(run)
    if kind == "triptych":
        path = VIDEOS / run / "hunger_triptych.mp4"
    elif kind in FILES and level is not None and level in known[run]["levels"]:
        path = VIDEOS / run / level / FILES[kind]
    else:
        raise KeyError(kind)
    if not path.exists():
        raise KeyError(str(path.name))
    return path
