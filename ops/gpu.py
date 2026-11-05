"""Take turns on the GPU: one model job at a time, in priority order, with a ledger of every job.

Cosmos and Qwen each need about 18 GB, so two model jobs at once can run a 36 GB Mac out of memory.

    python3 ops/gpu.py run --name wmloop_demo --priority 10 --cwd PATH -- CMD ARGS...
    python3 ops/gpu.py status

`run` blocks until the job has had its turn and finished, then exits with the job's own code, so a
caller running it in the background is told when the job is done. Lower priority numbers go first;
equal priorities go in arrival order. Standard library only.
"""
import argparse
import fcntl
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("KOKOPELLI_ROOT", Path.home() / "Desktop/kokopelli"))
STATE = ROOT / "out/ops"
QUEUE = STATE / "queue"
LEDGER = STATE / "gpu_ledger.jsonl"
LOCK = STATE / "gpu.lock"
LOGS = STATE / "job_logs"
POLL_SECONDS = float(os.environ.get("KOKOPELLI_GPU_POLL", 15))

# Model jobs started without this wrapper still count as using the GPU.
MODEL_JOB = re.compile(
    r"homeostatic\.(train|evaluate|experiment)|life\.overnight|txt2video|img2video|collect\.py"
    r"|runtime\.run .*--(wm cosmos|agent qwen)|mlx_vlm\.(convert|generate|lora)"
)


def outside_model_jobs():
    """Model processes on the machine. A wrapped job only runs while its ticket says running."""
    if os.environ.get("KOKOPELLI_GPU_IGNORE_OUTSIDE"):  # for the tests, which run beside real jobs
        return []
    output = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    jobs = []
    for line in output.splitlines():
        pid, _, command = line.strip().partition(" ")
        shell_wrapper = re.match(r"\S*(zsh|bash|sh) -c ", command)
        if MODEL_JOB.search(command) and "ops/gpu.py" not in command and not shell_wrapper:
            jobs.append((int(pid), command[:160]))
    return jobs


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def tickets():
    """Waiting and running tickets, best first. Tickets of dead processes are removed."""
    found = []
    for path in QUEUE.glob("*.json"):
        try:
            ticket = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if alive(ticket["pid"]):
            found.append(ticket)
        else:
            path.unlink(missing_ok=True)
    return sorted(found, key=lambda t: (t["priority"], t["queued_at"]))


def log_event(**fields):
    with LEDGER.open("a") as ledger:
        ledger.write(json.dumps({"at": time.time(), **fields}) + "\n")


def wait_for_turn(ticket, path, deadline):
    while True:
        if deadline and time.time() > deadline:
            return "gave_up"
        with LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            line = tickets()
            first = line and line[0]["id"] == ticket["id"]
            nobody_running = not any(t.get("running") for t in line)
            if first and nobody_running and not outside_model_jobs():
                ticket["running"] = True
                path.write_text(json.dumps(ticket))
                return "go"
        time.sleep(POLL_SECONDS)


def run(args):
    for folder in (QUEUE, LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    ticket_id = f"{int(now * 1000)}-{os.getpid()}"
    ticket = {"id": ticket_id, "name": args.name, "priority": args.priority, "pid": os.getpid(),
              "queued_at": now, "cwd": args.cwd, "command": args.command, "running": False}
    path = QUEUE / f"{ticket_id}.json"
    path.write_text(json.dumps(ticket))
    log_event(event="queued", id=ticket_id, name=args.name, priority=args.priority, command=args.command)
    deadline = now + args.give_up_hours * 3600 if args.give_up_hours else None
    try:
        if wait_for_turn(ticket, path, deadline) == "gave_up":
            log_event(event="gave_up", id=ticket_id, name=args.name, waited=time.time() - now)
            print(f"GAVE UP: {args.name} got no turn in {args.give_up_hours} hours", file=sys.stderr)
            return 3
        started = time.time()
        log_path = LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.name}.log"
        log_event(event="started", id=ticket_id, name=args.name, waited=started - now, log=str(log_path))
        print(f"{args.name} started, log at {log_path}", flush=True)
        with log_path.open("w") as log:
            process = subprocess.Popen(["caffeinate", "-is", *args.command], cwd=args.cwd or None,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            timed_out = False
            try:
                code = process.wait(timeout=args.max_hours * 3600 if args.max_hours else None)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                code = 124
        peak_gb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**30
        log_event(event="finished", id=ticket_id, name=args.name, exit_code=code, timed_out=timed_out,
                  seconds=time.time() - started, peak_rss_gb=round(peak_gb, 2), log=str(log_path))
        print(f"{args.name} finished with exit code {code}, log at {log_path}", flush=True)
        return code
    finally:
        path.unlink(missing_ok=True)


def status(_args):
    for ticket in tickets():
        state = "RUNNING" if ticket.get("running") else "waiting"
        waited = (time.time() - ticket["queued_at"]) / 60
        print(f"{state:8} p{ticket['priority']:<3} {ticket['name']:28} {waited:6.1f} min  pid {ticket['pid']}")
    for pid, command in outside_model_jobs():
        print(f"outside  pid {pid}: {command}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--name", required=True)
    run_parser.add_argument("--priority", type=int, default=50)
    run_parser.add_argument("--cwd")
    run_parser.add_argument("--give-up-hours", type=float, default=0)
    run_parser.add_argument("--max-hours", type=float, default=0, help="stop the job after this long, so a hang can't hold the GPU all night")
    run_parser.add_argument("command", nargs="+")
    run_parser.set_defaults(handler=run)
    commands.add_parser("status").set_defaults(handler=status)
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    QUEUE.mkdir(parents=True, exist_ok=True)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
