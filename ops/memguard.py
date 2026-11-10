"""Keep heavy commands from running this Mac out of memory.

On 2026-11-09 four workers each started the full test suites at once, memory and swap ran out, and the Mac panicked. Nothing
had asked whether there was room. This is the gate for anything heavy that isn't a GPU queue job (gpu.py has its own turn-taking):
test suites, linters over the whole repo, builds. It builds on ram_share.py, so the GPU queue's `--gb` jobs see these claims too.

    python3 ops/memguard.py run --name tests --gb 6 -- make test-all   # wait for room, run, stop it if memory runs out
    python3 ops/memguard.py status                                     # one line: memory, swap, what's running
    python3 ops/memguard.py watch                                      # the overnight watchdog, one per Mac
    python3 ops/memguard.py hook                                       # Claude Code PreToolUse hook for Bash (reads JSON on stdin)

`run` waits until ram_share says `--gb` is free and fewer than MAX_JOBS guarded commands are running, then runs the command in
its own process group. It stops the whole group, with exit 75 (the queue's "gave way, try again later"), if the command uses
well over its claim, or if the Mac's available memory falls below FLOOR_GB or swap passes SWAP_KILL_GB. Standard library only.
"""
import argparse
import ctypes
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ram_share  # noqa: E402

STATE = Path(os.environ.get("KOKO_MEMGUARD_DIR", Path.home() / ".kokopelli" / "memguard"))
PREFIX = "memguard_"
MAX_JOBS = 2          # guarded commands running at once, however much room there is
FLOOR_GB = 3.0        # below this much available memory, guarded commands stop
SWAP_ADMIT_GB = 14    # no new guarded command starts above this much swap in use
SWAP_KILL_GB = 24     # guarded commands stop above this
OVER = 1.25           # a command may pass its claim by this factor, plus half a GB, before it's stopped
HOOK_FLOOR_GB = 5.0   # the hook refuses to start anything heavy below this
POLL_SECONDS = 2
GAVE_WAY = 75
SELFTEST = "memguard-hook-selftest"
# Commands that run tests. These must go through `run` (or `make test-all`, which guards itself).
TESTS = re.compile(r"-m\s+(unittest|pytest)\b|(^|[\s;&|(])pytest\b|\bmake\s+(-\S+\s+)*test\b")
GUARDED = re.compile(r"memguard|test_all\.sh|test-all")
HEAVY = re.compile(TESTS.pattern + r"|test_all\.sh|test-all|pre-commit|\bpyright\b|\buv\s+(sync|lock|run)\b|\bnpx\b|xcodebuild|gpu\.py\s+run")
# What the watchdog may stop when it isn't under a guard: only these programs, and only when started inside a worktree.
STRAY = re.compile(r"^(python[\d.]*|pytest|node|make|ruff|pyright|uv|npx)$", re.I)


def swap_gb():
    text = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    found = re.search(r"used = ([\d.]+)([MG])", text)
    return 0.0 if not found else float(found.group(1)) / (1024 if found.group(2) == "M" else 1)


def main_root():
    """The main checkout, also when this runs from a worktree. Claims live under its out/, so every checkout shares them."""
    here = Path(__file__).resolve().parents[1]
    done = subprocess.run(["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True)
    return Path(done.stdout.strip()).parent if done.returncode == 0 and done.stdout.strip() else here


def claims_folder():
    return Path(os.environ.get("KOKO_MEMGUARD_CLAIMS", main_root() / "out" / "ram" / "claims"))


def blocked(room, need, running, swap):
    """Why a command that needs `need` GB can't start yet, or None."""
    if running >= MAX_JOBS:
        return f"{running} guarded commands are already running (limit {MAX_JOBS})"
    if swap > SWAP_ADMIT_GB:
        return f"swap is at {swap:.1f} GB (limit {SWAP_ADMIT_GB})"
    if room < need:
        return f"{max(0, room):.1f} GB of room, {need} GB needed"
    return None


def stop(process):
    """End a command's whole process group: ask first, then force."""
    for sign, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sign)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def run(name, gb, command, wait_seconds=4 * 3600, log=lambda text: print(text, file=sys.stderr, flush=True)):
    if gb > ram_share.total_gb() - ram_share.MARGIN_GB:
        log(f"memguard: {name} asks for {gb} GB, more than this Mac can ever give")
        return 2
    STATE.mkdir(parents=True, exist_ok=True)
    folder, started, told, process = claims_folder(), time.monotonic(), 0.0, None
    while process is None:
        with open(STATE / "admit.lock", "w") as lock:  # one admission at a time, so two waiters can't both take the last room
            fcntl.flock(lock, fcntl.LOCK_EX)
            room, found, _ = ram_share.room_gb(folder)
            why = blocked(room, gb, sum(claim["name"].startswith(PREFIX) for claim in found), swap_gb())
            if why is None:
                process = subprocess.Popen(command, start_new_session=True, env={**os.environ, "MEMGUARD": "1"})
                claim = ram_share.write_claim(f"{PREFIX}{name}_{process.pid}", gb, process.pid, folder=folder)
        if process is None:
            waited = time.monotonic() - started
            if waited > wait_seconds:
                log(f"memguard: {name} gave up after waiting {waited:.0f} s: {why}")
                return GAVE_WAY
            if waited - told >= 60 or told == 0:
                log(f"memguard: {name} waits: {why}")
                told = waited or 0.001
            time.sleep(5)
    waited, began, peak, strikes, reason = time.monotonic() - started, time.monotonic(), 0.0, 0, None
    signal.signal(signal.SIGTERM, lambda *_: (stop(process), sys.exit(143)))
    try:
        while process.poll() is None:
            time.sleep(POLL_SECONDS)
            used = ram_share.tree_gb(process.pid, ram_share.processes())
            peak = max(peak, used)
            available, swap = ram_share.available_gb(), swap_gb()
            if used > gb * OVER + 0.5:
                reason = f"it used {used:.1f} GB against a claim of {gb} GB. Rerun with a larger --gb"
            elif available < FLOOR_GB or swap > SWAP_KILL_GB:
                strikes += 1  # two readings in a row, so one bad sample doesn't end a long run
                if strikes >= 2:
                    reason = f"the Mac was down to {available:.1f} GB available with {swap:.1f} GB of swap. Wait before running it again, and don't start anything else heavy"
            else:
                strikes = 0
            if reason:
                stop(process)
    except KeyboardInterrupt:
        stop(process)
    finally:
        claim.unlink(missing_ok=True)
    code = GAVE_WAY if reason else process.returncode
    seconds = time.monotonic() - began
    log(f"memguard: {name} {'STOPPED: ' + reason if reason else 'done'} (peak {peak:.1f} of {gb} GB, {seconds:.0f} s, waited {waited:.0f} s)")
    with open(STATE / "log.jsonl", "a") as out:
        out.write(json.dumps({"at": time.time(), "name": name, "gb": gb, "peak_gb": round(peak, 2), "seconds": round(seconds), "waited": round(waited),
                              "exit": code, "stopped": reason, "command": " ".join(command)[:200]}) + "\n")
    return code


def status_line():
    room, found, heavy = ram_share.room_gb(claims_folder())
    jobs = ", ".join(f"{claim['name'][len(PREFIX):]} {claim['used_gb']}/{claim['gb']} GB" for claim in found if claim["name"].startswith(PREFIX))
    others = ", ".join(f"{claim['name']} {claim['used_gb']}/{claim['gb']} GB" for claim in found if not claim["name"].startswith(PREFIX))
    return (f"available {ram_share.available_gb():.1f} GB, room {room:.1f} GB, swap {swap_gb():.1f} GB, guarded: {jobs or 'none'}"
            + (f", other claims: {others}" if others else "") + (f", unclaimed heavy: {len(heavy)}" if heavy else ""))


def cwd_of(pid):
    """A process's working folder, from libproc (proc_vnodepathinfo: the path starts 152 bytes in). Empty if it can't be read."""
    buffer = ctypes.create_string_buffer(2352)
    if ram_share._LIBPROC.proc_pidinfo(pid, 9, ctypes.c_uint64(0), buffer, 2352) <= 0:
        return ""
    return buffer.raw[152:152 + 1024].split(b"\0")[0].decode(errors="replace")


def strays(table, found, worktrees):
    """Processes an agent started in a worktree without a guard, largest first. The watchdog's last resort."""
    by_parent = {}
    for row in table:
        by_parent.setdefault(row["parent"], []).append(row["pid"])
    covered, stack = set(), [claim["pid"] for claim in found]
    while stack:
        pid = stack.pop()
        covered.add(pid)
        stack += by_parent.get(pid, [])
    rows = [row for row in table if row["pid"] not in covered and row["rss_gb"] > 0.5
            and STRAY.match(Path(row["command"].split()[0]).name) and cwd_of(row["pid"]).startswith(str(worktrees))]
    return sorted(rows, key=lambda row: -row["rss_gb"])


def watch(log_path=None, poll=5):
    """The watchdog. Each guarded command already stops itself at the floor. This catches what's left: a guard that died, or a
    heavy command an agent started in a worktree without one. It never touches anything outside the worktrees."""
    STATE.mkdir(parents=True, exist_ok=True)
    log_path, worktrees, last = Path(log_path or STATE / "watch.jsonl"), main_root() / ".claude" / "worktrees", 0.0
    with open(STATE / "watch.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("memguard: a watchdog is already running")
            return 0
        while True:
            available, swap, action = ram_share.available_gb(), swap_gb(), None
            if available < FLOOR_GB - 0.5 or swap > SWAP_KILL_GB + 2:
                table = ram_share.processes()
                found = ram_share.claims(claims_folder(), table)
                guarded = sorted((claim for claim in found if claim["name"].startswith(PREFIX)), key=lambda claim: -claim["at"])
                target = guarded[0]["pid"] if guarded else next((row["pid"] for row in strays(table, found, worktrees)), None)
                if target:
                    try:  # a guarded command leads its own group, a stray doesn't
                        os.killpg(target, signal.SIGKILL) if guarded else os.kill(target, signal.SIGKILL)
                        action = f"killed {'guarded ' + guarded[0]['name'] if guarded else 'stray'} pid {target}"
                    except OSError as error:
                        action = f"could not kill pid {target}: {error}"
                else:
                    action = "memory is critical and nothing here is the cause"
            if action or time.time() - last >= 60:
                last = time.time()
                with open(log_path, "a") as out:
                    out.write(json.dumps({"at": last, "available_gb": round(available, 1), "swap_gb": round(swap, 1), "action": action}) + "\n")
            time.sleep(poll)


def hook_verdict(command, cwd, available):
    """Why a Bash command should be refused, or None. Light commands always pass."""
    if SELFTEST in command:
        return "memguard hook is live"
    if not HEAVY.search(command):
        return None
    if main_root().name in cwd + command and TESTS.search(command) and not GUARDED.search(command):
        return ("Tests must run under the memory guard: use `make test-all`, or prefix the command with "
                "`python3 ops/memguard.py run --name <what> --gb <peak GB> --`. Unguarded parallel test runs crashed this Mac on 2026-11-09.")
    if available < HOOK_FLOOR_GB:
        return (f"Only {available:.1f} GB of memory is available, so nothing heavy may start. Wait a few minutes, check "
                "`python3 ops/memguard.py status`, and don't retry in a tight loop.")
    return None


def hook():
    try:
        event = json.load(sys.stdin)
        why = hook_verdict(event.get("tool_input", {}).get("command", ""), event.get("cwd", ""), ram_share.available_gb())
    except Exception:  # a broken guard must never block every command
        return 0
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    runner = commands.add_parser("run", help="wait for room, then run a command under the guard")
    runner.add_argument("--name", required=True)
    runner.add_argument("--gb", type=float, required=True, help="the command's peak memory")
    runner.add_argument("--wait", type=float, default=4 * 3600, help="seconds to wait for room before giving up with exit 75")
    runner.add_argument("command", nargs="+")
    commands.add_parser("status")
    commands.add_parser("watch")
    commands.add_parser("hook")
    args = parser.parse_args()
    if args.action == "run":
        return run(args.name, args.gb, args.command, args.wait)
    if args.action == "watch":
        return watch()
    if args.action == "hook":
        return hook()
    print(status_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
