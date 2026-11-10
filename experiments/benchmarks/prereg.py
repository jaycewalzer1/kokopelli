"""The pre-registration guard: `run.py --real` won't run unless PREREG.md is locked and unchanged.

Why? A pre-registration only means something if it was written before the results and not edited afterward. The lock
stores a hash of PREREG.md and contrasts.yaml. Any edit changes the hash, so a real run stops. A legitimate change can
go ahead with --amend-prereg "reason", which leaves a permanent line in the amendment log. Changes stay possible, but never silent.

The lock doesn't exist yet: PREREG.md is a DRAFT, and the owner locks it after approving it:
    python -m experiments.benchmarks.prereg lock
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from experiments.benchmarks.core import BENCHMARKS, sha256_file

PREREG = BENCHMARKS / "PREREG.md"
CONTRASTS = BENCHMARKS / "configs" / "contrasts.yaml"
LOCK = BENCHMARKS / "prereg.lock.json"
AMENDMENTS = BENCHMARKS / "prereg_amendments.jsonl"
DRAFT_MARK = "STATUS: DRAFT"


class PreregError(RuntimeError):
    pass


def current_hashes(prereg=PREREG, contrasts=CONTRASTS):
    return {"prereg_sha256": sha256_file(prereg), "contrasts_sha256": sha256_file(contrasts)}


def lock(prereg=PREREG, contrasts=CONTRASTS, lock_path=LOCK):
    if DRAFT_MARK in Path(prereg).read_text():
        raise PreregError(f"{prereg} is still marked DRAFT. Remove '{DRAFT_MARK}' once you approve it, then lock.")
    if Path(lock_path).exists():
        raise PreregError(f"{lock_path} already exists. To change a locked pre-registration, use --amend-prereg.")
    record = {**current_hashes(prereg, contrasts), "locked_at": datetime.now(timezone.utc).isoformat()}
    Path(lock_path).write_text(json.dumps(record, indent=2) + "\n")
    return record


def check(amend_reason=None, prereg=PREREG, contrasts=CONTRASTS, lock_path=LOCK, amendments=AMENDMENTS):
    """Return the hashes a real run should record, or raise PreregError if the run must not go ahead."""
    if DRAFT_MARK in Path(prereg).read_text():
        raise PreregError(f"{prereg} is marked DRAFT, so real runs are refused. Approve it and run `python -m experiments.benchmarks.prereg lock`. "
                          "A base-model noise check can run with --exploratory instead.")
    if not Path(lock_path).exists():
        raise PreregError(f"No lock at {lock_path}. Run `python -m experiments.benchmarks.prereg lock` first.")
    locked = json.loads(Path(lock_path).read_text())
    now = current_hashes(prereg, contrasts)
    changed = [key for key in now if now[key] != locked[key]]
    if not changed:
        return {**now, "amended": False}
    if not amend_reason:
        raise PreregError(f"The pre-registration changed after it was locked ({', '.join(changed)}). "
                          'If this is intended, rerun with --amend-prereg "why it changed", which logs the amendment.')
    entry = {"at": datetime.now(timezone.utc).isoformat(), "reason": amend_reason, "from": {k: locked[k] for k in now}, "to": now}
    with Path(amendments).open("a") as file:
        file.write(json.dumps(entry) + "\n")
    Path(lock_path).write_text(json.dumps({**locked, **now, "last_amended_at": entry["at"]}, indent=2) + "\n")
    return {**now, "amended": True, "amendment_reason": amend_reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["lock", "check"])
    args = parser.parse_args()
    try:
        print(json.dumps(lock() if args.command == "lock" else check(), indent=2))
    except PreregError as error:
        print(error, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
