"""Share this Mac's memory between model jobs and heavy work the GPU queue can't see, like an Unreal build or server.

The GPU queue (gpu.py) gives one model job a turn at a time, but it only knows about model jobs. Anything else heavy can
claim memory here, and a polite job (one that uses `Guard`) waits for room before loading a model and gives the memory
back if the room runs out, instead of pushing the other work into swap. Standard library only.

    python ram_share.py hold --name ue_build --gb 20 -- ./scripts/build.sh   # run a command with a claim, removed when it ends
    python ram_share.py claim --name ue_server --gb 12 --pid 4242           # claim for a running process, removed when it dies
    python ram_share.py status

A claim says how much a job may use at its peak. What it isn't using yet still counts as taken, so a polite job never loads a
model into memory the claimed job is about to need.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("KOKOPELLI_ROOT", Path(__file__).resolve().parent))
CLAIMS = ROOT / "out" / "ram" / "claims"
MARGIN_GB = 4      # left free on top of everything, for the system and the panel
FLOOR_GB = 2.5     # a polite job holding a model gives it back below this
POLL_SECONDS = 30
# Heavy work that may not have claimed anything. While one of these runs with no claim, it's assumed to need this much more.
UNCLAIMED = (re.compile(r"UnrealBuildTool|UnrealEditor(?!Services)|ShaderCompileWorker|UnrealHeaderTool|SimWorld.*-server|xcodebuild"), 12)


def total_gb():
    return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2 ** 30


def available_gb():
    """macOS's own share of memory still available, which counts what it can get back by compressing idle apps. Free pages
    alone undercount badly: with a browser and a few apps open they say 18 GB on a Mac that runs Qwen's 19 GB without strain."""
    level = int(subprocess.run(["sysctl", "-n", "kern.memorystatus_level"], capture_output=True, text=True).stdout)
    return level / 100 * total_gb()


def processes():
    rows = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,command="], capture_output=True, text=True).stdout.splitlines()
    found = []
    for row in rows:
        parts = row.split(None, 3)
        if len(parts) == 4:
            found.append({"pid": int(parts[0]), "parent": int(parts[1]), "rss_gb": int(parts[2]) / 2 ** 20, "command": parts[3]})
    return found


def tree_gb(pid, table):
    """Resident memory of a process and everything under it."""
    children, total, stack = {}, 0.0, [pid]
    for row in table:
        children.setdefault(row["parent"], []).append(row)
    by_pid = {row["pid"]: row for row in table}
    while stack:
        current = stack.pop()
        total += by_pid[current]["rss_gb"] if current in by_pid else 0
        stack += [row["pid"] for row in children.get(current, [])]
    return total


def claims(folder=CLAIMS, table=None):
    """Live claims, each with how much of it is still unused. A claim whose process has died is removed."""
    table = processes() if table is None else table
    alive = {row["pid"] for row in table}
    found = []
    for path in Path(folder).glob("*.json"):
        try:
            claim = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if claim.get("pid") not in alive:
            path.unlink(missing_ok=True)
            continue
        used = tree_gb(claim["pid"], table)
        found.append({**claim, "used_gb": round(used, 1), "unused_gb": round(max(0.0, claim["gb"] - used), 1)})
    return found


def unclaimed_heavy(table, found):
    claimed = set()
    for claim in found:
        claimed |= {row["pid"] for row in table if row["pid"] == claim["pid"] or row["parent"] == claim["pid"]}
    pattern, gb = UNCLAIMED
    heavy = [row for row in table if pattern.search(row["command"]) and row["pid"] not in claimed]
    return heavy, (gb if heavy else 0)


def room_gb(folder=CLAIMS):
    """What a polite job may take: available memory, less every claim's unused part, less the margin."""
    table = processes()
    found = claims(folder, table)
    heavy, extra = unclaimed_heavy(table, found)
    return available_gb() - sum(claim["unused_gb"] for claim in found) - extra - MARGIN_GB, found, heavy


class Guard:
    """Wraps a model a polite job loads. Call `before()` ahead of each use: it waits for room to load, and gives the model
    back (through `unload`) when the room runs out. The caller's next use loads it again once there's room."""

    def __init__(self, name, need_gb, unload=None, log=print, folder=CLAIMS, poll=POLL_SECONDS):
        self.name, self.need_gb, self.unload, self.log, self.folder, self.poll = name, need_gb, unload, log, folder, poll
        self.loaded = False
        self.waited = 0.0

    def before(self):
        if self.loaded:
            room, found, heavy = room_gb(self.folder)
            # Holding the model, the room left only has to stay above the floor.
            if room + MARGIN_GB >= FLOOR_GB:
                return
            self.log(f"ram_share: {self.name} gives back its model, {room + MARGIN_GB:.1f} GB left for {describe(found, heavy)}")
            if self.unload:
                self.unload()
            self.loaded = False
        started = time.monotonic()
        while True:
            room, found, heavy = room_gb(self.folder)
            if room >= self.need_gb:
                break
            self.log(f"ram_share: {self.name} waits for {self.need_gb} GB, {max(0, room):.1f} GB free after {describe(found, heavy)}")
            time.sleep(self.poll)
        self.waited += time.monotonic() - started
        self.loaded = True


def describe(found, heavy):
    parts = [f"{claim['name']} ({claim['used_gb']} of {claim['gb']} GB)" for claim in found]
    parts += [f"unclaimed {Path(row['command'].split()[0]).name}" for row in heavy[:3]]
    return ", ".join(parts) or "other programs"


def write_claim(name, gb, pid, note="", folder=CLAIMS):
    Path(folder).mkdir(parents=True, exist_ok=True)
    path = Path(folder) / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json"
    path.write_text(json.dumps({"name": name, "gb": gb, "pid": pid, "note": note, "at": time.time()}))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    hold = commands.add_parser("hold", help="run a command with a claim")
    hold.add_argument("--name", required=True)
    hold.add_argument("--gb", type=float, required=True)
    hold.add_argument("command", nargs="+")
    claim = commands.add_parser("claim", help="claim memory for a process that's already running")
    claim.add_argument("--name", required=True)
    claim.add_argument("--gb", type=float, required=True)
    claim.add_argument("--pid", type=int, required=True)
    commands.add_parser("status")
    args = parser.parse_args()
    if args.action == "hold":
        process = subprocess.Popen(args.command)
        path = write_claim(args.name, args.gb, process.pid)
        try:
            return process.wait()
        finally:
            path.unlink(missing_ok=True)
    if args.action == "claim":
        print(write_claim(args.name, args.gb, args.pid))
        return 0
    room, found, heavy = room_gb()
    print(f"available {available_gb():.1f} GB, room for a polite job {room:.1f} GB (after a {MARGIN_GB} GB margin)")
    for item in found:
        print(f"claim {item['name']}: {item['gb']} GB, using {item['used_gb']}, pid {item['pid']}")
    for row in heavy:
        print(f"unclaimed heavy pid {row['pid']}: {row['command'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
