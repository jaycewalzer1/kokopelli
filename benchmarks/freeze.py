"""Freeze an item file: copy it to its final name and record its SHA-256 hash, so any later edit is detectable.

Why freeze? If items could change after we've seen results, we could (even by accident) keep tweaking them until
an effect appears. A hash makes a promise checkable: change one character and it no longer matches.

Nothing has been frozen with this yet. The owner runs it after reviewing a draft:
    python -m benchmarks.freeze freeze mid_travel benchmarks/mid_travel/items/draft.jsonl
    python -m benchmarks.freeze verify
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.core import BENCHMARKS, sha256_file

MANIFEST = BENCHMARKS / "frozen_items.json"
FROZEN_FILES = {"mid_travel": BENCHMARKS / "mid_travel" / "items" / "mid_travel_v1.jsonl"}


class FreezeError(RuntimeError):
    pass


def _load(manifest):
    return json.loads(Path(manifest).read_text()) if Path(manifest).exists() else {}


def freeze(name, draft, target, manifest=MANIFEST):
    """Copy a draft to its frozen path once. A second freeze of the same name always refuses."""
    entries = _load(manifest)
    target = Path(target)
    if name in entries or target.exists():
        raise FreezeError(f"{name} is already frozen at {target}. Frozen items are never regenerated. Make a new version with a new name.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft, target)
    entries[name] = {"path": str(target), "sha256": sha256_file(target),
                     "frozen_at": datetime.now(timezone.utc).isoformat()}
    Path(manifest).write_text(json.dumps(entries, indent=2) + "\n")
    return entries[name]["sha256"]


def verify(manifest=MANIFEST):
    """Return a list of problems with frozen files. An empty list means they all still match."""
    problems = []
    for name, entry in _load(manifest).items():
        path = Path(entry["path"])
        if not path.exists():
            problems.append(f"{name}: {path} is missing")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"{name}: {path} changed since it was frozen")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("freeze")
    make.add_argument("name", choices=sorted(FROZEN_FILES))
    make.add_argument("draft", type=Path)
    commands.add_parser("verify")
    args = parser.parse_args()
    if args.command == "freeze":
        print(freeze(args.name, args.draft, FROZEN_FILES[args.name]))
        return
    problems = verify()
    print("\n".join(problems) or "All frozen items match their hashes.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
