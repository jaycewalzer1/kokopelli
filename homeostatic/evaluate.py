"""Score one policy on the held-out test lives and save a result per life, so policies can be compared seed by seed."""
import argparse
import json
import os
from pathlib import Path

from homeostatic.benchmark import constant_policy, planner_policy, random_policy, run_benchmark, summarize
from settings import HOMEOSTATIC_SEEDS, LLM_MODEL_WEIGHTS

SIMPLE = {"random": random_policy, "idle": lambda: constant_policy("idle"), "greedy": lambda: planner_policy(1),
          "planner": lambda: planner_policy(4)}


def model_policy(adapter=None, reveal_effects=False):
    from mlx_vlm import load
    from mlx_vlm.trainer.peft.utils import apply_lora_layers

    from homeostatic.grpo import Actor, training_args

    model, processor = load(str(LLM_MODEL_WEIGHTS))
    if adapter:
        apply_lora_layers(model, adapter)
    model.eval()
    return Actor(model, processor, training_args("unused.safetensors"), reveal_effects=reveal_effects).policy()


def evaluate(policy, output, split, seeds=HOMEOSTATIC_SEEDS["test"]):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results = run_benchmark(policy, seeds, split)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"split": split, "summary": summarize(results), "episodes": results}))
    os.replace(temporary, output)
    return results


def write_validation_baselines(out):
    """How untrained policies score on the validation lives, which is what a run's validation curve is read against."""
    policies = {name: make() for name, make in SIMPLE.items()} | {"base": model_policy()}
    summaries = {name: summarize(run_benchmark(policy, HOMEOSTATIC_SEEDS["validation"])) for name, policy in policies.items()}
    output = Path(out) / "baselines-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summaries))
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="a results file, or with --validation the folder for its baselines")
    parser.add_argument("--validation", action="store_true", help="score the untrained policies on the validation lives instead")
    parser.add_argument("--policy", choices=[*SIMPLE, "model"], default="model")
    parser.add_argument("--adapter", help="an adapter weights file; leave out for the base model")
    parser.add_argument("--reveal-effects", action="store_true", help="tell the model what every action does in its prompt")
    parser.add_argument("--split", choices=["train", "ood"], default="train")
    parser.add_argument("--episodes", type=int)
    options = parser.parse_args()
    if options.validation:
        raise SystemExit(print(write_validation_baselines(options.output)))
    chosen = SIMPLE[options.policy]() if options.policy in SIMPLE else model_policy(options.adapter, options.reveal_effects)
    seeds = HOMEOSTATIC_SEEDS["test"]
    print(summarize(evaluate(chosen, options.output, options.split, seeds[:options.episodes] if options.episodes else seeds)))
