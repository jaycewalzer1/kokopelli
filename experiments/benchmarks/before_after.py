"""One command for the training pipeline: run a base model and a trained model on the same instruments and seeds, and compare.

Both sides go through run.py, so prompts, option orders and sampling match by construction, and a stopped run resumes.
Results go to <out>/results.jsonl, and the comparison to <out>/before_after.json, plus the usual report.

    python -m experiments.benchmarks.before_after --after-weights <run>/fused --name homeostatic --seeds 0 1 2 --samples 50 \\
        --instruments holt_laury lotteries mmlu --backend llm_model --real --out experiments/benchmarks/results/<id>

With a real backend this is refused until the owner has locked PREREG.md and named the arm in configs/contrasts.yaml.
See "Before and after" in HANDOFF.md, including how to start it through the GPU queue.

Exit codes: 0 finished, 2 refused, 3 leakage found, 75 time budget used (rerun the same command to continue).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from experiments.benchmarks import report, run, stats
from experiments.benchmarks.registry import instrument_entries, load_contrasts

BASE = "base"


def write_arms(args):
    """Save both arm configs with the results. A rerun with different settings is refused rather than mixed in."""
    folder = args.out / "arms"
    after = {"name": args.name, "model": args.model, "adapter": str(args.after_adapter) if args.after_adapter else None,
             "weights": str(args.after_weights) if args.after_weights else None, "api_model": args.api_model,
             "training_text": args.training_text, "notes": "Written by benchmarks.before_after."}
    before = {"name": BASE, "model": args.model, "adapter": None, "api_model": args.base_api_model, "notes": "Written by benchmarks.before_after."}
    folder.mkdir(parents=True, exist_ok=True)
    for arm in (before, after):
        path = folder / f"{arm['name']}.yaml"
        text = yaml.safe_dump(arm, sort_keys=True)
        if path.exists() and path.read_text() != text:
            raise run.Refused(f"{path} already holds different settings. Use a new --out.")
        path.write_text(text)
    return folder


def compare(out, name, n_perm=5000):
    """After minus before, per instrument. There is no predicted direction here: this says what moved and how surely."""
    rows = run.read_results(out)
    frame, entries = stats.to_frame(rows), instrument_entries()
    margin_points = load_contrasts()["contrasts"]
    guardrail_margin = next((c["margin"] for c in margin_points if c["kind"] == "guardrail"), 1.0)
    settings = load_contrasts()["settings"]
    keys = {arm: {run.result_key(row)[1:] for row in rows if row["arm"] == arm} for arm in (BASE, name)}
    main, guardrails = [], []
    for instrument in sorted(frame.instrument.unique()):
        role = entries.get(instrument, {}).get("role")
        if role == "guardrail":
            contrast = {"id": instrument, "kind": "guardrail", "instrument": instrument, "a": name, "b": BASE, "margin": guardrail_margin}
            table = stats.evaluate_contrasts(frame, {"settings": settings, "contrasts": [contrast]}, n_perm=1).iloc[0]
            guardrails.append({"instrument": instrument, "delta_points": _number(table["difference"]), "ci_95": [_number(table["ci_low"]), _number(table["ci_high"])],
                               "margin_points": guardrail_margin, "status": table["status"], "within_margin": table["status"].startswith("pass")})
            continue
        a, b = stats._matched(frame[frame.instrument == instrument], name, BASE)
        if a.empty or b.empty:
            continue
        low, high = stats.difference_ci(a, b)
        per_seed = a.groupby("seed").score.mean() - b.groupby("seed").score.mean()
        main.append({"instrument": instrument, "metric": _metric(rows, instrument), "before_mean": float(b.score.mean()), "after_mean": float(a.score.mean()),
                     "difference": float(a.score.mean() - b.score.mean()), "ci_95": [low, high], "cohens_d": _number(stats.cohens_d(a.score, b.score)),
                     "p": stats.permutation_test(a.score.to_numpy(), b.score.to_numpy(), stats._strata_labels(a), stats._strata_labels(b), n_perm=n_perm),
                     "difference_per_seed": {str(seed): float(value) for seed, value in per_seed.items()}, "n_before": len(b), "n_after": len(a)})
    for row, adjusted in zip(main, stats.holm([row["p"] for row in main]), strict=False):
        row["p_holm"] = adjusted
    failures = stats.parse_failures(rows)
    info = {arm: next((row for row in rows if row["arm"] == arm and row["instrument"] in {m["instrument"] for m in main} | {g["instrument"] for g in guardrails}), {}) for arm in (BASE, name)}
    return {
        "before": {"arm": BASE, "model_id": info[BASE].get("model_id")},
        "after": {"arm": name, "model_id": info[name].get("model_id"), "path": info[name].get("adapter_path"), "hash": info[name].get("adapter_hash")},
        # False means the two sides didn't cover the same questions, so don't trust the comparison until a rerun finishes them.
        "comparable": keys[BASE] == keys[name] and bool(keys[BASE]),
        "instruments": main, "guardrails": guardrails,
        "guardrails_ok": all(row["within_margin"] for row in guardrails) if guardrails else None,
        "parse_failures": failures.to_dict("records"),
        "note": "A difference here doesn't test a hypothesis. Only contrasts locked in PREREG.md can do that.",
    }


def _number(value):
    return None if value != value else float(value)


def _metric(rows, instrument):
    from experiments.benchmarks.registry import load_instrument
    return load_instrument(instrument).metric if instrument != "mid_travel" else "risky_rate"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    after = parser.add_mutually_exclusive_group(required=True)
    after.add_argument("--after-weights", type=Path, help="Folder of full weights: fused/ from homeostatic.export. May hold {seed}.")
    after.add_argument("--after-adapter", type=Path, help="Adapter folder, for the vllm, api or mock backends. May hold {seed}.")
    parser.add_argument("--name", default="after", help="The trained arm's name")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--instruments", nargs="+", default=["holt_laury", "lotteries"])
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--backend", default="mock", choices=["mock", "llm_model", "api", "vllm"])
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--amend-prereg", dest="amend_prereg")
    parser.add_argument("--training-text", nargs="*", default=[], help="Files or patterns the trained arm saw, for the leakage check")
    parser.add_argument("--api-model", help="The server's name for the trained model, for --backend api")
    parser.add_argument("--base-api-model", help="The server's name for the base model, for --backend api")
    parser.add_argument("--base-url")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--max-tokens", type=int, dest="max_tokens")
    parser.add_argument("--minutes", type=float)
    parser.add_argument("--progress", type=int, default=0)
    args = parser.parse_args(argv)

    if args.name == BASE:
        parser.error(f"--name can't be {BASE}: that is the before side.")
    try:
        arms_dir = write_arms(args)
    except run.Refused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return run.EXIT_REFUSED

    forwarded = ["--arms", BASE, args.name, "--arms-dir", str(arms_dir), "--instruments", *args.instruments, "--seeds", *map(str, args.seeds),
                 "--samples", str(args.samples), "--out", str(args.out), "--backend", args.backend, "--progress", str(args.progress)]
    for flag, value in (("--real", args.real),):
        if value:
            forwarded.append(flag)
    for flag, value in (("--amend-prereg", args.amend_prereg), ("--base-url", args.base_url), ("--temperature", args.temperature),
                        ("--max-tokens", args.max_tokens), ("--minutes", args.minutes)):
        if value is not None:
            forwarded += [flag, str(value)]
    code = run.main(forwarded)
    if code != 0:
        return code

    summary = compare(args.out, args.name)
    (args.out / "before_after.json").write_text(json.dumps(summary, indent=2, default=_json_number) + "\n")
    data = report.collect(args.out)
    (args.out / "report.md").write_text(report.to_markdown(data))
    (args.out / "report.html").write_text(report.to_html(data))
    print(f"Wrote {args.out / 'before_after.json'}. Comparable: {summary['comparable']}. Guardrails within margin: {summary['guardrails_ok']}.")
    return 0


def _json_number(value):
    return value.item() if isinstance(value, np.generic) else str(value)


if __name__ == "__main__":
    sys.exit(main())
