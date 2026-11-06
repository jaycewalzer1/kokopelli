"""The whole comparison, unattended: baselines, the base model, every training run, then the report.

Each step is a subprocess that hands its memory back when it ends. Finished steps are skipped on a restart, and a
crashed training run resumes from its last checkpoint.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from homeostatic.evaluate import SIMPLE
from homeostatic.report import write_report
from settings import HOMEOSTATIC_OUT, HOMEOSTATIC_TRAIN

SPLITS = ["train", "ood"]
MAX_CRASHES = 5


def run_step(command, log):
    """Run one step, returning whether it succeeded."""
    started = time.time()
    with open(log, "a") as file:
        file.write(f"\n$ {' '.join(command)}\n")
        file.flush()
        code = subprocess.run([sys.executable, "-u", "-m", *command], stdout=file, stderr=subprocess.STDOUT).returncode
    print(f"{'ok' if code == 0 else f'FAILED ({code})'} {time.time() - started:7.0f}s  {' '.join(command)}", flush=True)
    return code == 0


def evaluate_step(output, log, *flags):
    if output.exists():
        return
    if not run_step(["homeostatic.evaluate", str(output), *flags], log):
        raise SystemExit(f"Evaluation failed; see {log}")


def train_step(folder, reward, seed, settings, log):
    """Train until finished, resuming after a crash. Giving up on one run still leaves the others to finish."""
    command = ["homeostatic.train", str(folder), "--reward", reward, "--seed", str(seed), "--iters", str(settings["iters"]),
               "--set", json.dumps({key: settings[key] for key in settings if key != "iters"})]
    for _ in range(MAX_CRASHES):
        if (folder / "finished").exists():
            return True
        run_step(command + (["--resume"] if (folder / "progress.json").exists() else []), log)
    return (folder / "finished").exists()


def hand_off(folder, seed, log):
    """Pass a run on to the agent loop and benchmarks if it earned it. A refusal is a normal result, not a crash."""
    if not run_step(["homeostatic.export", str(folder), "--seed", str(seed)], log):
        print(f"{folder.name} wasn't handed off; see {log}", flush=True)


def main(out, seeds, rewards, settings):
    out.mkdir(parents=True, exist_ok=True)
    log = out / "run.log"
    results = out / "results"
    if not (out / "baselines-validation.json").exists() and not run_step(["homeostatic.evaluate", str(out), "--validation"], log):
        raise SystemExit(f"Evaluation failed; see {log}")
    for split in SPLITS:
        for name in SIMPLE:
            evaluate_step(results / f"{name}-{split}.json", log, "--policy", name, "--split", split)
    for split in SPLITS:
        evaluate_step(results / f"base-{split}.json", log, "--split", split)
        evaluate_step(results / f"base-told-{split}.json", log, "--split", split, "--reveal-effects")
    # Controls alternate with the real run, so an early stop still leaves something to compare it with.
    for seed in seeds:
        for reward in rewards:
            folder = out / "runs" / f"{reward}-{seed}"
            if not train_step(folder, reward, seed, settings, log):
                print(f"gave up on {folder.name}", flush=True)
                continue
            for split in SPLITS:
                evaluate_step(results / f"{reward}-{seed}-{split}.json", log, "--split", split, "--adapter", str(folder / "best.safetensors"))
            write_report(out)
            if reward == "homeostatic":
                hand_off(folder, seed, log)
    print(write_report(out))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HOMEOSTATIC_OUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--rewards", nargs="+", default=["homeostatic", "maximize", "shuffled"])
    parser.add_argument("--iters", type=int, default=HOMEOSTATIC_TRAIN["iters"])
    parser.add_argument("--set", type=json.loads, default={}, help="JSON overrides for HOMEOSTATIC_TRAIN")
    options = parser.parse_args()
    main(options.out, options.seeds, options.rewards, HOMEOSTATIC_TRAIN | {"iters": options.iters} | options.set)
