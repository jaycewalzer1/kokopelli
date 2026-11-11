"""The pilot: one small LoRA on 4-bit Qwen from a fixed sample of the prepared Psych-101 rows, then fused for the sweep.

It loads Qwen, so it only ever runs through the GPU queue:

    python3 kokopelli/ops/gpu.py run --name sens_lora_psych101_pilot --priority 50 --max-hours 0.65 --gb 14 --cwd "$PWD" \
      --about "Pilot LoRA: Qwen3-VL-8B-Instruct 4-bit on a fixed sample of Psych-101 human choices ..." \
      --output models/adapters/psych101_pilot -- \
      .venv/bin/python -u -m experiments.sensation.psych101.train_pilot --minutes 15

What it does, in order, and why:

  1. Reads lora/pilot/train.jsonl (prepare.py wrote it round-robin over experiments, so any prefix is a balanced sample)
     and refuses if a held-out experiment is in it.
  2. Measures the untrained model's loss on the validation rows. The loss is on the human's choice only.
  3. Sizes itself. A short probe (real training steps on the first rows) gives tokens per second on this Mac as it is
     tonight, plugged in or not; the rows that fit the remaining minutes follow from that, and the arithmetic goes in
     the sidecar. A fixed row count would either waste the night or outlive the battery.
  4. Trains on the rest of that prefix, once through, and measures the loss again.
  5. Fuses. The benchmarks' backend runs full weights only, so the adapter has to be merged into the base. Merging
     into 4-bit weights the stock way (homeostatic.export.fuse_into) rounds the sum back to 4 bits, and an update much
     smaller than one rounding step can vanish. So the loss is measured after that merge; if less than
     `--keep` of the adapter's gain survives, the adapted layers are stored as 32-bit floats instead (their 4-bit base
     values plus the update, which is what was trained) and everything else stays 4-bit.
  6. Reloads the fused folder as an ordinary model and measures the loss a last time: the sweep will load that folder,
     so that number is the one that says whether the sweep is testing the adapter.

Training code: mlx-vlm's own supervised trainer (mlx_vlm.trainer, what `python -m mlx_vlm.train` calls). The homeostatic
area's train.py and grpo.py are built around its simulator (states, branch scores, a loss on the first token) and load
the full-precision weights, so they don't fit supervised text; what is shared is imported from there: the fuse, the
weight-folder writer and the file hash in export.py.
"""
import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path

from experiments.benchmarks.core import REPO
from experiments.homeostatic.export import fuse_into, sha256, write_full_weights
from experiments.sensation.psych101 import prepare
from kokopelli.settings import LLM_MODEL

BASE = REPO / "models" / "Qwen3-VL-8B-Instruct-4bit"
OUT = REPO / "models" / "adapters" / "psych101_pilot"
SETTINGS = {
    "rank": 8, "alpha": 16.0, "dropout": 0.0,
    # The two attention projections LoRA was introduced on. Fewer layers than "every linear layer" keeps the fused
    # folder small if the adapted layers have to be stored as 32-bit floats (about 2.6 GB more than 4-bit, not 30).
    "targets": ["q_proj", "v_proj"],
    # 1e-4 is the usual LoRA rate. Centaur and the homeostatic runs use 5e-5 over far more steps; the pilot sees each of
    # a few thousand rows once, so at the lower rate "nothing changed" would say little.
    "learning_rate": 1e-4, "optimizer": "adamw", "weight_decay": 0.0, "batch_size": 1, "max_seq_length": 4096,
    "train_on_completions": True, "seed": 0,
}


def load_rows(path, limit=None):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def check_rows(rows, lists):
    """No held-out experiment may reach training, whatever file the rows came from."""
    held = sorted({row["experiment"] for row in rows if prepare.listed(row["experiment"], lists["held_out"])})
    if held:
        raise SystemExit(f"Held-out experiments are in the training rows: {held}. Not training.")


def measured_rate(history):
    """Tokens per second from the trainer's reports, preparation time included. The first report carries the warm-up."""
    rates = [report["end_to_end_tokens_per_second"] for report in history if "end_to_end_tokens_per_second" in report]
    if not rates:
        raise ValueError("The trainer reported no token rate.")
    return statistics.median(rates[1:] if len(rates) > 2 else rates)


def rows_that_fit(tokens_per_second, seconds, mean_tokens, available, cap):
    """How many more rows the time allows, and the sum that says so."""
    by_time = int(tokens_per_second * seconds / mean_tokens)
    rows = max(0, min(by_time, available, cap))
    limit = "the time" if rows == by_time else "the rows prepared" if rows == available else "the cap"
    return {"rows": rows, "limited_by": limit,
            "arithmetic": f"{tokens_per_second:.0f} tokens/s x {seconds:.0f} s / {mean_tokens:.0f} tokens per row = {by_time} rows; "
                          f"{available} available, cap {cap}; so {rows}"}


def kept_share(base, adapter, fused):
    """How much of the adapter's change in validation loss the fused weights still show: 1 is all of it, 0 is none.

    None when the adapter didn't move the loss enough to tell (under 0.001), since a ratio of two noises means nothing.
    """
    gain = base - adapter
    return None if abs(gain) < 1e-3 else (base - fused) / gain


def training_args(adapter_file, iters, settings=SETTINGS, report=4):
    from mlx_vlm.trainer.vlm.config import VLMTrainingArgs
    return VLMTrainingArgs(batch_size=settings["batch_size"], iters=iters, steps_per_report=report, steps_per_eval=None,
                           steps_per_save=10 ** 9, val_batches=-1, adapter_file=str(adapter_file),
                           max_seq_length=settings["max_seq_length"], train_on_completions=settings["train_on_completions"])


def trainer_for(model, processor, args, settings=SETTINGS, train=None, validation=None):
    import mlx.optimizers as optim
    from mlx_vlm.trainer.api import Trainer
    optimizer = optim.AdamW(learning_rate=settings["learning_rate"], weight_decay=settings["weight_decay"])
    return Trainer(model, args, train_dataset=train, eval_dataset=validation, processing_class=processor,
                   optimizer=optimizer, seed=settings["seed"])


def train_rows(model, processor, rows, adapter_file, settings=SETTINGS, report=4):
    """Once through these rows. Returns the trainer's reports and the seconds it took, preparation included."""
    args = training_args(adapter_file, len(rows) // settings["batch_size"], settings, report)
    trainer = trainer_for(model, processor, args, settings, train=rows)
    started = time.time()
    trainer.train()
    return list(trainer.log_history), time.time() - started


def validation_loss(model, processor, rows, adapter_file, settings=SETTINGS):
    """Mean cross-entropy on the human's choice, over every validation row."""
    trainer = trainer_for(model, processor, training_args(adapter_file, 1, settings), settings, validation=rows)
    return float(trainer.evaluate()["val_loss"])


def token_lengths(model, processor, rows, settings=SETTINGS):
    from mlx_vlm.trainer.vlm.sft.dataset import VisionDataset
    dataset = VisionDataset(rows, model.config, processor, config=training_args("unused", 1, settings))
    return [int(dataset[index]["input_ids"].shape[-1]) for index in range(len(rows))]


def fuse_float(model):
    """Merge every adapter into its layer and store that layer as 32-bit floats, so the update isn't rounded away.

    homeostatic.export.fuse_into rounds the merged layer back to 4 bits, and mlx-vlm's own `fuse(dequantize=True)`
    adds the update in the base's bfloat16 (8 significant bits), which loses an update that small just the same. So
    the sum is done here in float32: the layer's 4-bit base values, exactly, plus the update. Untouched layers keep
    their 4-bit form. Handles the plain LoRA layer over a linear layer, which is all the pilot attaches.
    """
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_unflatten
    fused = []
    for name, module in model.named_modules():
        if not hasattr(module, "lora_a"):
            continue
        linear = module.linear
        if isinstance(linear, nn.QuantizedLinear):
            weight = mx.dequantize(linear.weight, linear.scales, linear.biases, group_size=linear.group_size, bits=linear.bits,
                                   mode=linear.mode)
        elif isinstance(linear, nn.Linear):
            weight = linear.weight
        else:
            raise TypeError(f"{name}: can't fuse an adapter over {type(linear).__name__}")
        update = (module.scale * module.lora_b.T.astype(mx.float32)) @ module.lora_a.T.astype(mx.float32)
        layer = nn.Linear(weight.shape[1], weight.shape[0], bias="bias" in linear)
        layer.weight = weight.astype(mx.float32) + update
        if "bias" in linear:
            layer.bias = linear.bias
        fused.append((name, layer))
    model.update_modules(tree_unflatten(fused))
    mx.eval(model.parameters())
    return len(fused)


def folder_bytes(folder):
    return sum(path.stat().st_size for path in Path(folder).rglob("*") if path.is_file())


def power():
    try:
        return subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "unknown"


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(data=prepare.DATA, out=OUT, base=BASE, minutes=25.0, probe=24, cap=3000, validation_rows=120, keep=0.9,
        settings=SETTINGS, load=None, held_out_path=prepare.HELD_OUT):
    """Train, fuse and write the sidecar. `load` is mlx-vlm's loader unless a test passes its own."""
    import mlx.core as mx
    from mlx_vlm.trainer.common.model import prepare_model_for_training
    from mlx_vlm.version import __version__ as mlx_vlm_version
    if load is None:
        from mlx_vlm import load
    data, out, base = Path(data), Path(out), Path(base)
    started = time.time()
    lists = prepare.load_held_out(held_out_path)
    rows = load_rows(data / "lora" / "pilot" / "train.jsonl")
    validation = load_rows(data / "lora" / "pilot" / "validation.jsonl", validation_rows)
    check_rows(rows + validation, lists)
    if len(rows) <= probe:
        raise SystemExit(f"Only {len(rows)} training rows; the probe alone needs {probe}.")
    manifest = json.loads((data / "manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    adapter_file = out / "adapters.safetensors"
    side = out / "run.json"
    record = {
        "what": "Pilot LoRA: Psych-101 human choices, a fixed sample. Made to measure the route, not to be used.",
        "made_by": "experiments/sensation/psych101/train_pilot.py", "real": True, "finished": False,
        "model": {"id": LLM_MODEL, "weights": str(base.relative_to(REPO)) if base.is_relative_to(REPO) else str(base),
                  "quantization": json.loads((base / "config.json").read_text()).get("quantization"),
                  "weights_bytes": folder_bytes(base)},
        "data": {**manifest["source"], "held_out_list_sha256": manifest["held_out_list_sha256"],
                 "prepare_settings": manifest["settings"],
                 "split": "lora/pilot/train.jsonl, the first rows of its fixed round-robin order",
                 "validation_split": f"lora/pilot/validation.jsonl, first {len(validation)} rows (people the training never sees)"},
        "training": {**settings, "scale": settings["alpha"] / settings["rank"], "trainer": f"mlx-vlm {mlx_vlm_version} SFT (mlx_vlm.trainer)",
                     "budget_minutes": minutes, "probe_rows": probe, "cap": cap},
        "git_commit": git_commit(), "power_at_start": power(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
    }

    def save_record():
        side.write_text(json.dumps(record, indent=1) + "\n")

    save_record()
    mx.random.seed(settings["seed"])
    model, processor = load(str(base))
    prepare_model_for_training(model, train_type="lora", lora_rank=settings["rank"], lora_alpha=settings["alpha"],
                               lora_dropout=settings["dropout"], target_modules=settings["targets"])
    lengths = token_lengths(model, processor, rows, settings)
    losses = {"base": validation_loss(model, processor, validation, adapter_file, settings)}
    print(f"validation loss, untrained: {losses['base']:.4f}", flush=True)

    history, seconds = train_rows(model, processor, rows[:probe], adapter_file, settings)
    rate = measured_rate(history)
    rest = lengths[probe:]
    fit = rows_that_fit(rate, minutes * 60, sum(rest) / len(rest), len(rest), cap - probe)
    print(f"probe: {rate:.0f} tokens/s. {fit['arithmetic']}", flush=True)
    trained = probe + fit["rows"]
    if fit["rows"]:
        more, longer = train_rows(model, processor, rows[probe:trained], adapter_file, settings, report=10)
        history, seconds = history + more, seconds + longer
    losses["adapter"] = validation_loss(model, processor, validation, adapter_file, settings)
    print(f"validation loss, with the adapter: {losses['adapter']:.4f}", flush=True)
    used = rows[:trained]
    record["training"] |= {
        "rows": trained, "steps": trained // settings["batch_size"], "epochs": 1,
        "experiments_covered": len({row["experiment"] for row in used}), "tokens": sum(lengths[:trained]),
        "mean_tokens_per_row": round(sum(lengths[:trained]) / trained, 1),
        "probe_tokens_per_second": round(rate, 1), "sizing": fit["arithmetic"], "limited_by": fit["limited_by"],
        "train_seconds": round(seconds, 1), "tokens_per_second": round(sum(lengths[:trained]) / seconds, 1),
        "peak_memory_gb": round(max(report.get("peak_memory", 0) for report in history), 2),
        "first_train_loss": round(history[0]["train_loss"], 4), "last_train_loss": round(history[-1]["train_loss"], 4),
    }
    record["adapter"] = {"file": "adapters.safetensors", "sha256": sha256(adapter_file), "bytes": adapter_file.stat().st_size}
    record["validation_loss"] = losses
    save_record()

    # Fuse the stock way first (4-bit in, 4-bit out), and look at what survived.
    fuse_into(model)
    losses["fused_requantized"] = validation_loss(model, processor, validation, adapter_file, settings)
    share = kept_share(losses["base"], losses["adapter"], losses["fused_requantized"])
    print(f"validation loss, fused and rounded back to 4-bit: {losses['fused_requantized']:.4f} (keeps {share})", flush=True)
    fused = out / "fused"
    if share is not None and share >= keep:
        variant = "4-bit: the adapter merged and every layer rounded back to 4 bits (homeostatic.export.fuse_into)"
    else:
        del model
        mx.clear_cache()
        model, processor = load(str(base), adapter_path=str(out))
        layers = fuse_float(model)
        variant = (f"mixed: the {layers} adapted layers ({', '.join(settings['targets'])}) are 32-bit floats holding their 4-bit base values "
                   "plus the update; every other layer is the base's 4-bit weights, unchanged")
    write_full_weights(model, base, fused)
    del model
    mx.clear_cache()
    model, processor = load(str(fused))
    losses["fused_folder"] = validation_loss(model, processor, validation, adapter_file, settings)
    print(f"validation loss, the fused folder reloaded: {losses['fused_folder']:.4f}", flush=True)
    record["fused"] = {"folder": str(fused.relative_to(REPO)) if fused.is_relative_to(REPO) else str(fused), "variant": variant,
                       "bytes": folder_bytes(fused), "requantized_keeps": None if share is None else round(share, 3),
                       "folder_keeps": (lambda value: None if value is None else round(value, 3))(
                           kept_share(losses["base"], losses["adapter"], losses["fused_folder"])),
                       "keep_threshold": keep,
                       "note": "config.json is the base's and still says 4-bit; mlx-vlm quantizes only layers whose file has .scales"}
    record |= {"validation_loss": losses, "finished": True, "seconds": round(time.time() - started, 1), "power_at_end": power()}
    save_record()
    (fused / "run.json").write_text(json.dumps(record, indent=1) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minutes", type=float, default=25.0, help="training time after the probe; the rows follow from it")
    parser.add_argument("--cap", type=int, default=3000, help="most rows to train on, whatever the time allows")
    parser.add_argument("--probe", type=int, default=24)
    parser.add_argument("--validation-rows", type=int, default=120)
    parser.add_argument("--keep", type=float, default=0.9, help="share of the adapter's validation gain the 4-bit fuse must keep")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    record = run(out=args.out, minutes=args.minutes, probe=args.probe, cap=args.cap, validation_rows=args.validation_rows,
                 keep=args.keep)
    print(json.dumps({key: record[key] for key in ("training", "validation_loss", "fused")}, indent=1))


if __name__ == "__main__":
    main()
