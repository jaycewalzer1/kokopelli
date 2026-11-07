"""What the panel's Experiment 1 page reads. It only reads run folders written by exp1/run.py; nothing here changes a run.

For each decision it adds what the page needs to explain it: whether the outcome was a rare one (and its odds, which are
shown to the developer, never to the agent), which night's update it went into, and what that update did to pi there.
Each pipeline step also gets the file and line of the code that does it, read from the code itself so it can't go stale.
"""
import inspect
import json
import os
import time
from functools import lru_cache
from pathlib import Path

from exp1 import baselines, homeostasis, learn, observe, policy, world
from exp1 import run as runner
from exp1.world import FLIP

RUNS = Path(os.environ.get("EXP1_RUNS", Path.home() / "Desktop/kokopelli/out/exp1/runs"))
STALE_SECONDS = 600
REFERENCE_LIVES = 100
ROOT = Path(__file__).resolve().parents[1]


def _where(obj):
    lines, start = inspect.getsourcelines(obj)
    return f"{Path(inspect.getsourcefile(obj)).resolve().relative_to(ROOT)}:{start}"


@lru_cache(maxsize=1)
def code_locations():
    """file:line for each step of the pipeline strip."""
    return {"observation": _where(observe.observation), "policy": _where(policy.QwenPolicy.log_probs), "choice": _where(runner.Run.decide),
            "outcome": _where(world.Life._outcome), "needs": _where(homeostasis.apply), "reward": _where(homeostasis.drive),
            "advantage": _where(learn.Baseline.advantage), "sleep": _where(learn.Sleeper.sleep), "shift": _where(runner.Run.night),
            "gate": _where(world.Life.pending), "depletion": _where(homeostasis.relax)}


def _lines(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            break  # a line being written right now
    return out


def _json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _state(folder, status):
    if not status:
        return "starting"
    if status["phase"] == "done":
        return "finished"
    age = time.time() - (folder / "status.json").stat().st_mtime
    return status["phase"] if age < STALE_SECONDS else "stopped"


def listing():
    if not RUNS.exists():
        return []
    out = []
    for folder in sorted(RUNS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        config = _json(folder / "config.json")
        if not config:
            continue
        status = _json(folder / "status.json")
        out.append({"name": folder.name, "arm": config["arm"], "seed": config["seed"], "policy": config["policy"],
                    "lr": config["learn"]["lr"], "state": _state(folder, status), "decisions": status["decisions"] if status else 0})
    return out


def outcome_odds(row, arm):
    """The probability of the outcome this decision got, from the table it was drawn from."""
    option = FLIP.get(row["choice"], row["choice"]) if arm == "flipped" else row["outcome_source"]
    return next(p for p, _, key in homeostasis.TABLES[row["decision"]][option] if key == row["outcome_label"])


@lru_cache(maxsize=16)
def _reference(seed, arm, days):
    return baselines.reference(seed, arm, days, REFERENCE_LIVES)


def reference_for(folder, config):
    saved = _json(folder / "reference.json")
    return saved or _reference(config["seed"], config["arm"], config["days"])


def describe(name):
    folder = RUNS / Path(name).name
    config = _json(folder / "config.json")
    if not config:
        raise KeyError(f"no run called {name}")
    rows, nights = _lines(folder / "trajectory.jsonl"), _lines(folder / "sleep.jsonl")
    by_index = {night["index"]: night for night in nights}
    for row in rows:
        p = outcome_odds(row, config["arm"])
        row["outcome_p"] = p
        row["rare"] = p < 0.5
        row["group"] = baselines.group_of(row)
        night = by_index.get(row["index"])
        if night and night.get("steps"):
            match = next((t for t in night["today"] if t["decision"] == row["decision"]), None)
            row["pi_after_night"] = match["pi_after"] if match else None
        row.pop("base_logp", None)
    status = _json(folder / "status.json")
    summary = baselines.summarize_rows(rows, config["days"]) if rows else None
    return {"name": folder.name, "config": config, "status": status, "state": _state(folder, status), "rows": rows, "nights": nights,
            "summary": summary, "direction": baselines.direction(config["arm"], summary["shares"]) if summary else None,
            "report": _json(folder / "report.json"), "guardrails": _json(folder / "guardrails.json"),
            "reference": reference_for(folder, config), "code": code_locations(), "pairs": baselines.PAIRS,
            "needs": list(homeostasis.NEEDS), "setpoint": float(homeostasis.SETPOINT[0]), "deplete": homeostasis.DEPLETE}


def arms():
    """Every run's direction reading, grouped by arm, beside what the tabular learner does in that arm."""
    out = {}
    for run in listing():
        folder = RUNS / run["name"]
        config = _json(folder / "config.json")
        rows = _lines(folder / "trajectory.jsonl")
        if not rows:
            continue
        summary = baselines.summarize_rows(rows, config["days"])
        reference = reference_for(folder, config)
        out.setdefault(config["arm"], {"runs": [], "tabular": reference["tabular"]["shares"],
                                       "random_reward": reference["random"]["this_seed"]["mean_reward"]["all"],
                                       "always_safe_reward": reference["always_safe"]["this_seed"]["mean_reward"]["all"]})
        out[config["arm"]]["runs"].append({"name": run["name"], "state": run["state"], "policy": config["policy"], "lr": config["learn"]["lr"],
                                           "direction": baselines.direction(config["arm"], summary["shares"]),
                                           "mean_reward": summary["mean_reward"]["all"],
                                           "base_pi": {name: summary["shares"][name].get("base_pi") for name in baselines.PAIRS}})
    return {"arms": out, "pairs": baselines.PAIRS}
