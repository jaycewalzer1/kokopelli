"""An unattended run on the local model. It restarts itself after a crash and picks up where the log stops."""
import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

from life.engine import Budget, Engine
from life.llm_generator import LLMGenerator
from life.panel import seed_from
from life.report import write_report
from life.store import Store
from life.windows import _birthday, children, life_window
from settings import LIFE_TRIAL, LIFE_TRIAL_SEEDS, ROOT

OUT = ROOT / "out" / "overnight"
NO_CALL_LIMIT = 10 ** 9


def month_holding(birth, moment):
    window = life_window(birth)
    while window.level != "month":
        window = next(child for child in children(window, birth) if child.start <= moment < child.end)
    return window


def month_at(birth, age):
    """The month holding this birthday, which is where a slice of a life stage starts."""
    return month_holding(birth, _birthday(birth, age))


def slice_month(seed, phase):
    if "age" in phase:
        return month_at(seed.birth_date, phase["age"])
    return month_holding(seed.birth_date, datetime.fromisoformat(seed.anchors[0]["at"]))


def overnight_phases():
    """Skim the life so every stage gets written, zoom into one month per stage, then skim a second life to compare."""
    share = (1 - LIFE_TRIAL["skim_share"] - LIFE_TRIAL["second_life_share"]) / (len(LIFE_TRIAL["slice_ages"]) + 1)
    return [{"name": "skim", "seed": 0, "deepest": LIFE_TRIAL["skim_deepest"], "share": LIFE_TRIAL["skim_share"]},
            *({"name": f"age{age}", "fork": "skim", "age": age, "share": share} for age in LIFE_TRIAL["slice_ages"]),
            # An anchor's salience is always 1.0, so this is the one sure way to reach the scene levels.
            {"name": "anchor", "fork": "skim", "share": share},
            {"name": "second", "seed": 1, "deepest": LIFE_TRIAL["skim_deepest"], "share": LIFE_TRIAL["second_life_share"]}]


def trial_phases():
    """The smallest run that writes every level both ways: through one year, then into the days of its first month."""
    return [{"name": "skim", "seed": 0, "deepest": LIFE_TRIAL["skim_deepest"], "share": 0.8, "first_year": True},
            {"name": "age2", "fork": "skim", "age": 2, "share": 0.2, "calls": LIFE_TRIAL["trial_day_calls"]}]


def _load(folder):
    return json.loads((folder / "state.json").read_text())


def _save(folder, state):
    # Written to the side and moved into place, so a crash can't leave half a file behind.
    temporary = folder / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=1))
    temporary.replace(folder / "state.json")


def run_phase(store, folder, state, phase, end):
    runs = state["runs"]
    if phase["name"] not in runs:
        if "fork" in phase:
            source = runs[phase["fork"]]
            month = slice_month(store.public_seed(source), phase)
            if store.node(source, month.id) is None:
                print(f"Skipping {phase['name']}: the skim never reached {month.label}.", flush=True)
                return "skipped"
            runs[phase["name"]] = store.fork(source, month.id)
        else:
            runs[phase["name"]] = store.create_run(seed_from(LIFE_TRIAL_SEEDS[phase["seed"]]))
        _save(folder, state)
    run_id = runs[phase["name"]]
    birth = store.public_seed(run_id).birth_date
    until = slice_month(store.public_seed(run_id), phase).id if "fork" in phase else None
    if phase.get("first_year"):
        until = children(life_window(birth), birth)[0].id
    generator = LLMGenerator(store.public_seed(run_id), store.rng_key(run_id), log_path=folder / "calls.jsonl", tag=phase["name"])
    budget = Budget(generator_calls=phase.get("calls", NO_CALL_LIMIT), seconds=max(0, end - time.time()))
    return Engine(store, run_id, generator=generator, budget=budget, deepest=phase.get("deepest")).run(until=until)


def work(folder):
    state = _load(folder)
    store = Store(folder / "life.db")
    phases = trial_phases() if state["trial"] else overnight_phases()
    end = state["started"]
    for phase in phases:
        end += phase["share"] * state["hours"] * 3600
        if phase["name"] in state["done"]:
            continue
        print(f"Starting {phase['name']}", flush=True)
        state["done"][phase["name"]] = run_phase(store, folder, state, phase, end)
        print(f"Finished {phase['name']}: {state['done'][phase['name']]}", flush=True)
        _save(folder, state)
    store.close()
    print(f"Report: {write_report(folder)}", flush=True)


def supervise(folder):
    """Run the work in a child process. The model can die in ways a try/except never sees, like running out of memory."""
    crashes = 0
    with open(folder / "run.log", "a") as log:
        while True:
            child = subprocess.Popen([sys.executable, "-u", "-m", "life.overnight", "--worker", str(folder)],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
            for line in child.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            if child.wait() == 0:
                return 0
            crashes += 1
            print(f"Worker exited with {child.returncode}. Crash {crashes} of {LIFE_TRIAL['max_crashes']}.", flush=True)
            if crashes >= LIFE_TRIAL["max_crashes"]:
                return 1
            time.sleep(30)


def new_folder(trial, hours):
    folder = OUT / f"{'trial-' if trial else ''}{datetime.now():%Y-%m-%d-%H%M}"
    folder.mkdir(parents=True, exist_ok=True)
    _save(folder, {"trial": trial, "hours": hours, "started": time.time(), "runs": {}, "done": {}})
    latest = OUT / "latest"
    latest.unlink(missing_ok=True)
    latest.symlink_to(folder.name)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=8)
    parser.add_argument("--trial", action="store_true", help="the short run: one year, then a few days")
    parser.add_argument("--resume", help="continue the run in this folder, keeping its original end time")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        try:
            work(Path(args.worker))
        except Exception:
            traceback.print_exc()
            raise SystemExit(1)
        return
    folder = Path(args.resume) if args.resume else new_folder(args.trial, args.hours)
    print(f"Writing to {folder}", flush=True)
    raise SystemExit(supervise(folder))


if __name__ == "__main__":
    main()
