"""Hand a finished run to the rest of the system: full weights for the agent loop, an adapter and arm for the benchmarks.

An adapter that didn't beat the baselines on validation lives is refused, so a failed run can't slip into the 30 minutes.
Everything written is listed in handoff.json, which also has the commands that use it. See homeostatic/HANDOFF.md.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from homeostatic.watch import baselines, read_rows
from settings import HOMEOSTATIC_ADAPTERS, HOMEOSTATIC_OUT, LLM_MODEL, LLM_MODEL_WEIGHTS, ROOT

MAX_INVALID = 0.05


class NotBetter(RuntimeError):
    pass


def best_validation(rows):
    """The check the saved best adapter came from: the lowest mean drive among those with mostly valid replies.

    Invalid replies act like idling, so a model that has stopped answering can look healthy.
    """
    usable = [row for row in rows if row["invalid"] <= MAX_INVALID]
    return min(usable, key=lambda row: row["mean_drive"], default=None)


def gate(rows, reference):
    """Return the validation row an adapter earned, or say why it can't be used."""
    best = best_validation(rows)
    if best is None:
        raise NotBetter("No validation with mostly valid replies.")
    for name in ("base", "idle"):
        if name not in reference:
            raise NotBetter(f"No {name} score to compare with. Run homeostatic.evaluate --validation.")
        if best["mean_drive"] >= reference[name]["mean_drive"]:
            raise NotBetter(f"Mean drive {best['mean_drive']:.1f} doesn't beat {name} at {reference[name]['mean_drive']:.1f}.")
    return best


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(2 ** 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fuse_into(model):
    """Merge every adapter into the weights it sits on, leaving an ordinary model."""
    from mlx.utils import tree_unflatten
    fused = [(name, module.fuse()) for name, module in model.named_modules() if hasattr(module, "fuse")]
    model.update_modules(tree_unflatten(fused))
    return len(fused)


def write_full_weights(model, base, target):
    """A folder the same shape as the base model's, with only the weights changed. Built aside so a crash leaves nothing half-written."""
    from mlx_vlm.utils import save_weights
    target = Path(target)
    building = target.with_name(target.name + ".building")
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir(parents=True)
    for path in Path(base).iterdir():
        if path.is_file() and not path.name.endswith(".safetensors") and path.name != "model.safetensors.index.json":
            shutil.copy(path, building / path.name)
    save_weights(building, model, donate_weights=True)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(building, target)


def export_arm(folder, arm, seed, adapters=HOMEOSTATIC_ADAPTERS):
    """The adapter in the place benchmark arms look for one, with the prompts it trained on for their leakage check."""
    destination = Path(adapters) / arm / f"seed{seed}"
    (destination / "training_text").mkdir(parents=True, exist_ok=True)
    shutil.copy(folder / "best.safetensors", destination / "adapters.safetensors")
    shutil.copy(folder / "adapter_config.json", destination / "adapter_config.json")
    states = [json.dumps({key: row[key] for key in ("turn", "values", "low", "high", "last")}) for row in read_rows(folder / "rollouts.jsonl")]
    (destination / "training_text" / "states.jsonl").write_text("\n".join(states) + "\n")
    return destination


def arm_config(arm, seed, adapters=HOMEOSTATIC_ADAPTERS):
    """The arm's settings in the benchmarks' format, for them to add. Their configs and pre-registration aren't this module's to edit."""
    relative = Path(adapters).relative_to(ROOT).as_posix()
    return {"name": arm, "model": LLM_MODEL, "adapter": f"{relative}/{arm}/seed{{seed}}", "api_model": f"{arm}_seed{{seed}}", "seed": seed,
            "training_text": [f"{relative}/{arm}/seed{{seed}}/training_text/*"],
            "notes": "LoRA from homeostatic post-training. Written by homeostatic.export; not in PREREG.md."}


def agent_commands(weights):
    """Using these weights in the loop. The smoke run is the check that a trained model still gives valid decisions there."""
    return {"smoke": f"-m runtime.run --ticks 3 --wm mock --sim mock --agent qwen --agent-weights {weights}",
            "half_hour_this_mac": f"-m runtime.run --ticks 60 --sim mock --wm cosmos --agent qwen --agent-weights {weights}"}


def export(folder, out=HOMEOSTATIC_OUT, seed=0, arm="homeostatic", adapters=HOMEOSTATIC_ADAPTERS, load=None):
    folder = Path(folder).resolve()
    best = gate(read_rows(folder / "validation.jsonl"), baselines(out))
    if load is None:
        from mlx_vlm import load
    model, _ = load(str(LLM_MODEL_WEIGHTS), adapter_path=str(folder / "best.safetensors"))
    layers = fuse_into(model)
    weights = folder / "fused"
    write_full_weights(model, LLM_MODEL_WEIGHTS, weights)
    adapter = export_arm(folder, arm, seed, adapters)
    handoff = {"run": folder.name, "validation": {key: best[key] for key in ("iteration", "mean_drive", "in_range", "invalid")},
               "compared_with": {name: baselines(out)[name]["mean_drive"] for name in ("base", "idle")}, "fused_layers": layers,
               "adapter_sha256": sha256(folder / "best.safetensors"), "full_weights": str(weights), "adapter": str(adapter),
               "agent_loop": agent_commands(weights), "benchmark_arm": arm_config(arm, seed, adapters)}
    temporary = Path(out) / "handoff.tmp"
    temporary.write_text(json.dumps(handoff, indent=1))
    os.replace(temporary, Path(out) / "handoff.json")
    return handoff


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="a finished training run")
    parser.add_argument("--seed", type=int, default=0)
    options = parser.parse_args()
    print(json.dumps(export(options.folder, seed=options.seed), indent=1))
