"""Run arms through instruments and append one result line per sample.

Mock, which is safe anywhere:
    python -m experiments.benchmarks.run --arms fake_base fake_lived --instruments holt_laury lotteries --samples 20 --seeds 0 1 2

Real models on this Mac go through the shared GPU queue. scripts/evals_noise_check.sh shows the exact command.

A stopped run continues when you rerun it with the same --out, skipping every key it already has. --minutes ends a
run cleanly with exit code 75 ("more to do"), so a long job can give the GPU back and rejoin the queue.
"""
import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from experiments.benchmarks import freeze, leakage, prereg
from experiments.benchmarks.backends import get_backend
from experiments.benchmarks.backends.base import GenRequest
from experiments.benchmarks.core import BANNED_IN_PROMPTS, BENCHMARKS, REPO, Parsed, option_order, sha256_file, stable_int
from experiments.benchmarks.registry import load_arm, load_contrasts, load_instrument, load_sampling

EXIT_REFUSED, EXIT_LEAK, EXIT_MORE_TO_DO = 2, 3, 75  # 75 is the usual "try again later" exit code.
RESULTS, RECORD, SUMMARY = "results.jsonl", "run_record.json", "summary.parquet"


class Refused(RuntimeError):
    pass


def git_state():
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "experiments/benchmarks"))}


def read_results(out):
    """Read results, tolerating a torn last line from a run that was killed mid-write."""
    path = Path(out) / RESULTS
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"WARNING: skipping unreadable line {number} in {path}", file=sys.stderr)
    return rows


def result_key(row):
    return (row["arm"], row["instrument"], row["item_id"], row["template"], row["seed"], row["sample"])


def open_append(out):
    """Open results for appending. If the last line was torn, start a new line so the next record is intact."""
    path = Path(out) / RESULTS
    file = path.open("a")
    if path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        file.write("\n")
    return file


def item_hashes(instruments):
    return {i.name: sha256_file(i.items_path) if i.items_path.exists() else None for i in instruments}


def write_record(out, record):
    """One record per folder. Rerunning must match its config, or the results would mix two different setups."""
    path = Path(out) / RECORD
    fixed = ("sampling", "backend", "item_hashes", "exploratory")
    if path.exists():
        previous = json.loads(path.read_text())
        for key in fixed:
            if previous[key] != record[key]:
                raise Refused(f"Can't resume in {out}: {key} changed from {previous[key]} to {record[key]}. Use a new --out.")
        previous["sessions"].append(record["sessions"][0])
        previous["arms"] = sorted(set(previous["arms"]) | set(record["arms"]))
        previous["instruments"] = sorted(set(previous["instruments"]) | set(record["instruments"]))
        previous["seeds"] = sorted(set(previous["seeds"]) | set(record["seeds"]))
        record = previous
    path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def base_row(run_id, arm, instrument, seed, info, sampling):
    return {"run_id": run_id, "arm": arm.name, "instrument": instrument.name, "seed": seed, "sampling": sampling, **info}


def plan(arm, seed, instrument, samples, done):
    """Every (item, template, sample) still to run, in a fixed order."""
    for item in instrument.items:
        for template in instrument.templates:
            for sample in range(samples):
                if (arm.name, instrument.name, instrument.item_id(item), template, seed, sample) not in done:
                    yield item, template, sample


def make_request(arm, instrument, item, template, seed, sample, sampling, attempt=0):
    order = option_order(instrument.options, instrument.name, instrument.item_id(item), template, seed, sample)
    prompt = instrument.build_prompt(item, template, order)
    if instrument.far_or_mid and BANNED_IN_PROMPTS.search(prompt):
        raise Refused(f"{instrument.name}/{instrument.item_id(item)}/{template} mentions the training world: "
                      f"{BANNED_IN_PROMPTS.search(prompt).group(0)!r}")
    return order, GenRequest(
        prompt=arm.prompt_prefix + prompt, sampling=sampling,
        seed=stable_int("sample", instrument.name, instrument.item_id(item), template, seed, sample, attempt),
        mock_context={"instrument": instrument, "item": item, "order": order})


def run_prompts(arm, seed, instrument, backend, info, args, sampling, done, out_file, stats):
    work = list(plan(arm, seed, instrument, args.samples, done))
    size = args.batch_size or backend.batch_size
    for start in range(0, len(work), size):
        if args.deadline and time.time() > args.deadline:
            raise OutOfTime()
        batch = work[start:start + size]
        built = [make_request(arm, instrument, *entry[:2], seed, entry[2], sampling) for entry in batch]
        outputs = backend.generate_batch([request for _, request in built])
        parsed = [instrument.parse(output.text, entry[0], order) for entry, (order, _), output in zip(batch, built, outputs)]

        # Retry a parse failure once with a fresh seed. A second failure is recorded as invalid, never dropped.
        retries = [index for index, result in enumerate(parsed) if not result.valid]
        failed_outputs = {index: [{"raw": outputs[index].text, "reason": parsed[index].reason}] for index in retries}
        if retries:
            second = backend.generate_batch([
                make_request(arm, instrument, batch[i][0], batch[i][1], seed, batch[i][2], sampling, attempt=1)[1] for i in retries])
            for index, output in zip(retries, second):
                outputs[index] = output
                parsed[index] = instrument.parse(output.text, batch[index][0], built[index][0])

        for index, ((item, template, sample), (order, _request)) in enumerate(zip(batch, built)):
            result: Parsed = parsed[index]
            scored = instrument.score(result, item, order) if result.valid else None
            row = {**base_row(args.run_id, arm, instrument, seed, info, sampling),
                   "item_id": instrument.item_id(item), "template": template, "sample": sample,
                   "option_order": ",".join(order), "raw_output": outputs[index].text, "parsed_choice": result.choice,
                   "valid": result.valid, "invalid_reason": result.reason if not result.valid else "",
                   "attempts": 2 if index in failed_outputs else 1, "failed_outputs": failed_outputs.get(index, []),
                   "score": scored.score if scored else None, "extras": scored.extras if scored else {},
                   "latency_s": round(outputs[index].latency_s, 4), "at": datetime.now(timezone.utc).isoformat()}
            out_file.write(json.dumps(row) + "\n")
            stats["written"] += 1
            stats["invalid"] += not result.valid
        out_file.flush()
        if args.progress and start % args.progress < size:
            print(f"{arm.name} seed {seed} {instrument.name}: {min(start + size, len(work))}/{len(work)}", flush=True)


def run_harness(arm, seed, instrument, backend, info, args, sampling, done, out_file, stats):
    if any(key[0] == arm.name and key[1] == instrument.name and key[4] == seed for key in done):
        return
    harness_sampling = {"note": "lm-eval's own settings for this task"}
    for doc_id, points, raw in instrument.run_harness(arm, seed, backend, args.out):
        row = {**base_row(args.run_id, arm, instrument, seed, info, harness_sampling),
               "item_id": doc_id, "template": "harness", "sample": 0, "option_order": "", "raw_output": raw,
               "parsed_choice": None, "valid": True, "invalid_reason": "", "attempts": 1, "failed_outputs": [],
               "score": points, "extras": {}, "latency_s": 0.0, "at": datetime.now(timezone.utc).isoformat()}
        out_file.write(json.dumps(row) + "\n")
        stats["written"] += 1
    out_file.flush()


class OutOfTime(RuntimeError):
    """This turn's --minutes are used up. Everything so far is saved."""


def write_summary(out):
    """A small table per (arm, instrument, template, seed). results.jsonl stays the source of truth."""
    rows = read_results(out)
    if not rows:
        return None
    frame = pd.DataFrame([{key: row[key] for key in ("arm", "instrument", "template", "seed", "valid", "score")} for row in rows])
    frame["score"] = pd.to_numeric(frame["score"])
    summary = frame.groupby(["arm", "instrument", "template", "seed"], as_index=False).agg(
        n=("valid", "size"), n_valid=("valid", "sum"), mean_score=("score", "mean"), sd_score=("score", "std"))
    path = Path(out) / SUMMARY
    summary.to_parquet(path, index=False)
    return path


def refusals(args, arms, instruments, backend_is_real):
    """Every reason this run mustn't go ahead. Each rule protects the meaning of a real result."""
    if backend_is_real and not args.real:
        raise Refused(f"Backend {args.backend} runs a real model. Pass --real to confirm.")
    if args.real and not backend_is_real:
        raise Refused("--real was passed with the mock backend. That would label pretend results as real.")
    if args.exploratory and not args.real:
        raise Refused("--exploratory only means something for real runs. Mock runs don't need it.")
    if args.exploratory:
        # Noise checks can run before the pre-registration is locked, but no result about training can sneak through this door.
        trained = [arm.name for arm in arms if arm.is_trained]
        if trained:
            raise Refused(f"--exploratory is for the base model only, so no effect can be peeked at. These are trained: {trained}")
    if args.real and not args.exploratory:
        # A locked pre-registration covers only the arms it names. Testing another one is the owner's decision.
        registered = {name for contrast in load_contrasts()["contrasts"] for name in (contrast["a"], contrast["b"])}
        unregistered = [arm.name for arm in arms if arm.is_trained and arm.name not in registered]
        if unregistered:
            raise Refused(f"{unregistered} aren't in configs/contrasts.yaml, so the pre-registration doesn't cover them. Adding an arm is the owner's decision.")
    has_prefix = [arm.name for arm in arms if arm.prompt_prefix]
    if has_prefix and args.real and not args.exploratory:
        raise Refused(f"{has_prefix} change the prompt, which breaks the rule that prompts match across arms. They are controls, for --exploratory only.")
    if args.real:
        stubs = [i.name for i in instruments if i.stub]
        if stubs:
            raise Refused(f"{stubs} are stubs and can't produce real results yet. See HANDOFF.md.")
        if args.items_override:
            raise Refused("--items-override is for tests with throwaway items. Real runs use only the proper item files.")
        unverified = [i.name for i in instruments if i.meta.get("verified") is False]
        if unverified:
            raise Refused(f"{unverified} have items marked verified: false.")


def run(args):
    args.out = Path(args.out) if args.out else BENCHMARKS / "results" / args.run_id
    arms = [load_arm(name, [args.arms_dir] if args.arms_dir else None) for name in args.arms]
    overrides = dict(pair.split("=", 1) for pair in args.items_override)
    instruments = [load_instrument(name, overrides.get(name)) for name in args.instruments]
    sampling = {**load_sampling(), **{k: v for k, v in (("temperature", args.temperature), ("max_tokens", args.max_tokens)) if v is not None}}
    backend_is_real = args.backend != "mock"
    refusals(args, arms, instruments, backend_is_real)

    prereg_state = {"status": "not checked: mock run"}
    if args.real and args.exploratory:
        prereg_state = {"status": "exploratory: base-model check, not a test of any hypothesis"}
    elif args.real:
        prereg_state = {"status": "checked", **prereg.check(args.amend_prereg)}
        problems = freeze.verify()
        if problems:
            raise Refused("Frozen items don't match their hashes: " + "; ".join(problems))

    # Check training text for every run, but only let a missing file block a real one.
    seeds_by_arm = {arm.name: args.seeds or [arm.seed] for arm in arms}
    hits = []
    for arm in arms:
        found, missing = leakage.check_arms([arm], seeds_by_arm[arm.name], instruments)
        hits += found
        if missing and args.real and not args.exploratory:
            raise Refused(f"Training text is missing, so leakage can't be checked: {missing}")
    if hits:
        print(json.dumps(hits[:10], indent=2), file=sys.stderr)
        print(f"LEAKAGE: {len(hits)} eval prompts overlap training text. Refusing to run.", file=sys.stderr)
        return EXIT_LEAK

    args.deadline = time.time() + args.minutes * 60 if args.minutes else None
    backend = get_backend(args.backend, base_url=args.base_url, model=args.model)
    effective = backend.effective_sampling(sampling)
    args.out.mkdir(parents=True, exist_ok=True)
    write_record(args.out, {
        "run_id": args.run_id, "backend": args.backend, "real": bool(args.real), "exploratory": bool(args.exploratory),
        "arms": args.arms, "instruments": args.instruments, "seeds": sorted({s for v in seeds_by_arm.values() for s in v}),
        "samples": args.samples, "sampling": effective, "item_hashes": item_hashes(instruments), "prereg": prereg_state,
        "arm_configs": {arm.name: {k: v for k, v in vars(arm).items() if k != "mock"} for arm in arms},
        "sessions": [{"started": datetime.now(timezone.utc).isoformat(), "argv": sys.argv, "git": git_state()}],
    })

    done = {result_key(row) for row in read_results(args.out)}
    stats = {"written": 0, "invalid": 0}
    started = time.time()
    code = 0
    with open_append(args.out) as out_file:
        try:
            for arm in arms:
                for seed in seeds_by_arm[arm.name]:
                    info = backend.prepare_arm(arm, seed)
                    random.seed(stable_int("run", arm.name, seed))
                    for instrument in instruments:
                        runner = run_harness if instrument.kind == "harness" else run_prompts
                        runner(arm, seed, instrument, backend, info, args, effective, done, out_file, stats)
        except OutOfTime:
            print(f"Time budget used. Rerun with the same --out to continue. Exit code {EXIT_MORE_TO_DO}.", file=sys.stderr)
            code = EXIT_MORE_TO_DO
        finally:
            out_file.flush()
            backend.close()
    write_summary(args.out)
    print(f"{args.out}: wrote {stats['written']} results, {stats['invalid']} invalid, in {time.time() - started:.1f}s")
    return code


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arms", nargs="+", required=True)
    p.add_argument("--instruments", nargs="+", required=True)
    p.add_argument("--samples", type=int, default=20, help="Samples per (arm, seed, item, template)")
    p.add_argument("--seeds", nargs="+", type=int, help="Defaults to the seed in each arm's config")
    p.add_argument("--out", help="Defaults to experiments/benchmarks/results/<run_id>")
    p.add_argument("--run-id", dest="run_id", default=None)
    p.add_argument("--backend", default="mock", choices=["mock", "llm_model", "api", "vllm"])
    p.add_argument("--base-url", help="For the api backend")
    p.add_argument("--model", help="Model path or id, for the vllm backend")
    p.add_argument("--real", action="store_true", help="Confirm this is a real run. Refused unless PREREG.md is locked and unchanged.")
    p.add_argument("--exploratory", action="store_true", help="Base-model checks before the pre-registration is locked. No adapters allowed.")
    p.add_argument("--amend-prereg", dest="amend_prereg", help="Accept a changed PREREG.md, and log this reason")
    p.add_argument("--items-override", dest="items_override", nargs="*", default=[], metavar="NAME=PATH", help="Throwaway items, for mock runs only")
    p.add_argument("--temperature", type=float)
    p.add_argument("--max-tokens", dest="max_tokens", type=int)
    p.add_argument("--batch-size", dest="batch_size", type=int)
    p.add_argument("--arms-dir", dest="arms_dir", help="Look for arm configs here first. before_after.py uses this.")
    p.add_argument("--progress", type=int, default=0, help="Print progress every N samples")
    p.add_argument("--minutes", type=float, help="Stop cleanly after this long, with exit code 75, so others get a GPU turn")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    args.run_id = args.run_id or (Path(args.out).name if args.out else datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S"))
    try:
        return run(args)
    except (Refused, prereg.PreregError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
