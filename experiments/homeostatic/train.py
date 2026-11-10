"""Train an adapter with GRPO. A killed run continues from its last checkpoint with --resume, with a fresh optimizer."""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

import mlx.core as mx
import mlx.optimizers as optim
from mlx_vlm import load
from mlx_vlm.trainer.api import Trainer
from mlx_vlm.trainer.common.callbacks import TrainingCallback
from mlx_vlm.trainer.common.utils import save_trainable_weights
from mlx_vlm.trainer.peft.utils import apply_lora_layers, get_peft_model

from experiments.homeostatic.benchmark import run_benchmark, summarize
from experiments.homeostatic.grpo import REWARD_KINDS, Actor, make_homeostatic_task, training_args
from kokopelli.settings import HOMEOSTATIC_SEEDS, HOMEOSTATIC_TRAIN, LLM_MODEL_WEIGHTS


class Checkpoints(TrainingCallback):
    """Logs every report, and saves and validates on its own schedule so that progress on disk always matches a checkpoint."""

    def __init__(self, folder, model, actor, settings, already_done=0):
        self.folder, self.model, self.actor, self.settings, self.already_done = folder, model, actor, settings, already_done
        self.best = self.read_progress().get("best_drive", float("inf"))

    def read_progress(self):
        path = self.folder / "progress.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def on_train_loss_report(self, train_info):
        iteration = train_info["iteration"] + self.already_done
        keep = {key: float(value) for key, value in train_info.items() if key.startswith("train_") or key in ("step_time", "data_time_per_step", "peak_memory")}
        self.log("train.jsonl", {"iteration": iteration, **keep})
        if iteration % self.settings["steps_per_eval"] == 0:
            summary = self.validate()
            self.log("validation.jsonl", {"iteration": iteration, **summary})
            print(f"validation {iteration}: {summary}", flush=True)
            if summary["mean_drive"] < self.best:
                self.best = summary["mean_drive"]
                self.save("best.safetensors")
        if iteration % self.settings["steps_per_save"] == 0:
            self.save("adapters.safetensors")
            temporary = self.folder / "progress.tmp"
            temporary.write_text(json.dumps({"iteration": iteration, "best_drive": self.best}))
            os.replace(temporary, self.folder / "progress.json")

    def validate(self):
        lives, finished = HOMEOSTATIC_SEEDS["validation"], []

        def show(result):
            finished.append(result)
            self.show_validating(len(finished), len(lives))

        self.show_validating(0, len(lives))
        results = run_benchmark(self.actor.policy(), lives, on_episode=show)
        (self.folder / "validating.json").unlink()
        return summarize(results)

    def show_validating(self, done, total):
        temporary = self.folder / "validating.tmp"
        temporary.write_text(json.dumps({"done": done, "total": total}))
        os.replace(temporary, self.folder / "validating.json")

    def log_group(self, state, actions, scores, chosen):
        self.log("rollouts.jsonl", {"time": time.time(), "turn": state.turn, "values": state.values, "low": state.low, "high": state.high,
                                    "last": state.last, "replies": actions, "scores": scores, "chosen": chosen})

    def log(self, name, row):
        with open(self.folder / name, "a") as file:
            file.write(json.dumps(row) + "\n")

    def save(self, name):
        temporary = self.folder / f"tmp-{name}"
        save_trainable_weights(self.model, temporary)
        os.replace(temporary, self.folder / name)


def train(folder, reward, seed=0, resume=False, settings=HOMEOSTATIC_TRAIN):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mx.random.seed(seed)
    model, processor = load(str(LLM_MODEL_WEIGHTS))
    progress = folder / "progress.json"
    already_done = json.loads(progress.read_text())["iteration"] if resume and progress.exists() else 0
    if already_done:
        apply_lora_layers(model, folder / "adapters.safetensors")
    else:
        get_peft_model(model, rank=settings["lora_rank"], alpha=settings["lora_alpha"], dropout=0.0)
    remaining = settings["iters"] - already_done
    if remaining <= 0:
        return
    args = training_args(folder / "adapters.safetensors", settings, iters=remaining)
    actor = Actor(model, processor, args)
    callback = Checkpoints(folder, model, actor, settings, already_done)
    task = make_homeostatic_task(actor, processor, args, reward, settings, rng_seed=seed + already_done, on_group=callback.log_group)
    Trainer(model, args, task=task, train_dataset=list(HOMEOSTATIC_SEEDS["train"]), training_callback=callback,
            optimizer=optim.Adam(learning_rate=settings["learning_rate"]), seed=seed + already_done).train()
    if not (folder / "best.safetensors").exists():
        shutil.copy(folder / "adapters.safetensors", folder / "best.safetensors")
    (folder / "finished").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--reward", choices=REWARD_KINDS, default="homeostatic")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--iters", type=int, default=HOMEOSTATIC_TRAIN["iters"])
    parser.add_argument("--set", type=json.loads, default={}, help="JSON overrides for HOMEOSTATIC_TRAIN")
    options = parser.parse_args()
    train(options.folder, options.reward, options.seed, options.resume, HOMEOSTATIC_TRAIN | {"iters": options.iters} | options.set)
