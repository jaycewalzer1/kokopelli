"""Take turns on the GPU: one model job at a time, in priority order, with a ledger of every job.

Cosmos and Qwen each need about 18 GB, so two model jobs at once can run a 36 GB Mac out of memory.

    python3 ops/gpu.py run --name wmloop_demo --priority 10 --cwd PATH \
        --about "what it tests and why, in a sentence or two" --output runs/wmloop_demo -- CMD ARGS...
    python3 ops/gpu.py status

Every job needs --about and at least one --output (relative to --cwd), so the panel's GPU tab can say what
each experiment is and show what it made. The owner asked for both; a job without them isn't queued.

`run` blocks until the job has had its turn and finished, then exits with the job's own code, so a
caller running it in the background is told when the job is done. Lower priority numbers go first;
equal priorities go in arrival order. Standard library only.

A job can instead run on PACE, if it gives a command that works there:
    python3 ops/gpu.py run --name x --pace-command "python -m thing --cuda" --pull out/x [--where pace] -- MAC CMD
    python3 ops/gpu.py where --name x --to pace     # move a waiting job to PACE, or back
    python3 ops/gpu.py default --to pace            # where new jobs with a PACE command go
PACE jobs don't take a turn on this Mac, so they don't hold up the local line. cloud/pace.py does the work.
A ticket with no `where` is local, so tickets written before this existed behave as they always did.
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
CODE = Path(os.environ.get("KOKOPELLI_CODE", Path.home() / "Desktop/kokopelli"))  # where cloud/ lives, which tests don't move
STATE = ROOT / "out/ops"
QUEUE = STATE / "queue"
LEDGER = STATE / "gpu_ledger.jsonl"
LOCK = STATE / "gpu.lock"
LOGS = STATE / "job_logs"
DEFAULT_WHERE = STATE / "where.json"
ABOUT_LIMIT = 400
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


def where(ticket):
    return ticket.get("where") or "local"


def default_where():
    try:
        return json.loads(DEFAULT_WHERE.read_text()).get("default", "local")
    except (OSError, ValueError):
        return "local"


def write_ticket(path, ticket):
    # Write then rename, so a reader never sees half a ticket.
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(ticket))
    os.replace(temp, path)


def summarize_later(ticket_id):
    """Start ops/summarize.py for a finished job in its own process, so the job's exit isn't held up by it."""
    if os.environ.get("KOKOPELLI_SUMMARIZE", "1") == "0":
        return
    try:
        with (LOGS / "summaries.log").open("a") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("summarize.py")), "--id", ticket_id],
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass  # A missing summary shows as one on the GPU tab; it never fails the job.


def log_event(**fields):
    with LEDGER.open("a") as ledger:
        ledger.write(json.dumps({"at": time.time(), **fields}) + "\n")


def wait_for_turn(ticket, path, deadline):
    while True:
        if deadline and time.time() > deadline:
            return "gave_up"
        with LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                ticket.update(json.loads(path.read_text()))  # `where` may have flipped this ticket to PACE while it waited
            except (OSError, ValueError):
                pass
            if where(ticket) == "pace":
                ticket.setdefault("pace", {})  # marks it as gone, so `where` can't flip it back once it's on its way
                write_ticket(path, ticket)
                return "pace"
            line = [t for t in tickets() if where(t) == "local"]
            first = line and line[0]["id"] == ticket["id"]
            nobody_running = not any(t.get("running") for t in line)
            if first and nobody_running and not outside_model_jobs():
                ticket["running"] = True
                write_ticket(path, ticket)
                return "go"
        time.sleep(POLL_SECONDS)


def run_on_pace(ticket, path, args, queued_at):
    """The job's turn, on PACE. It fails loudly rather than falling back to the Mac, because the user chose PACE for it."""
    sys.path.insert(0, str(CODE))
    from cloud import pace

    started = time.time()
    log_path = LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.name}.log"
    log_event(event="started", id=ticket["id"], name=args.name, waited=started - queued_at, log=str(log_path), where="pace")
    print(f"{args.name} sent to PACE, log at {log_path}", flush=True)

    def on_update(fields):
        with LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ticket["pace"] = {**ticket.get("pace", {}), **fields, "at": time.time()}
            write_ticket(path, ticket)

    try:
        code = pace.run_job({**ticket, "max_hours": args.max_hours}, log_path, on_update)
    except Exception as error:  # Anything unexpected still has to end in the ledger, not vanish.
        log_path.open("a").write(f"[pace] {type(error).__name__}: {error}\n")
        code = 2
    state = ticket.get("pace", {}).get("state")
    log_event(event="finished", id=ticket["id"], name=args.name, exit_code=code, timed_out=state == "TIMEOUT",
              seconds=time.time() - started, log=str(log_path), where="pace", slurm_job=ticket.get("pace", {}).get("job"), slurm_state=state)
    if code == 2 and state in (None, "COPYING"):
        print(f"FAILED: {args.name} couldn't be submitted to PACE. See {log_path}", file=sys.stderr, flush=True)
    print(f"{args.name} finished on PACE with exit code {code}, log at {log_path}", flush=True)
    summarize_later(ticket["id"])
    return code


def run(args):
    for folder in (QUEUE, LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    chosen = args.where or (default_where() if args.pace_command else "local")
    if chosen == "pace" and not args.pace_command:
        print(f"{args.name} can't go to PACE: it has no --pace-command, and the Mac command uses MLX.", file=sys.stderr)
        return 2
    about = " ".join((args.about or "").split())
    if not about or len(about) > ABOUT_LIMIT:
        print(f"{args.name} wasn't queued: --about must say briefly what the experiment does, in at most {ABOUT_LIMIT} characters.", file=sys.stderr)
        return 2
    if not args.output:
        print(f"{args.name} wasn't queued: give at least one --output, the file or folder it writes, so the GPU tab can show it.", file=sys.stderr)
        return 2
    outputs = [str(Path(args.cwd or os.getcwd(), output).resolve()) for output in args.output]
    now = time.time()
    ticket_id = f"{int(now * 1000)}-{os.getpid()}"
    ticket = {"id": ticket_id, "name": args.name, "priority": args.priority, "pid": os.getpid(),
              "queued_at": now, "cwd": args.cwd, "command": args.command, "running": False,
              "where": chosen, "pace_command": args.pace_command, "pull": args.pull, "about": about, "outputs": outputs}
    path = QUEUE / f"{ticket_id}.json"
    write_ticket(path, ticket)
    log_event(event="queued", id=ticket_id, name=args.name, priority=args.priority, command=args.command, cwd=args.cwd, where=chosen,
              about=about, outputs=outputs)
    deadline = now + args.give_up_hours * 3600 if args.give_up_hours else None
    try:
        turn = wait_for_turn(ticket, path, deadline)
        if turn == "gave_up":
            log_event(event="gave_up", id=ticket_id, name=args.name, waited=time.time() - now)
            print(f"GAVE UP: {args.name} got no turn in {args.give_up_hours} hours", file=sys.stderr)
            return 3
        if turn == "pace":
            return run_on_pace(ticket, path, args, now)
        started = time.time()
        log_path = LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.name}.log"
        log_event(event="started", id=ticket_id, name=args.name, waited=started - now, log=str(log_path), where="local")
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
                  seconds=time.time() - started, peak_rss_gb=round(peak_gb, 2), log=str(log_path), where="local")
        print(f"{args.name} finished with exit code {code}, log at {log_path}", flush=True)
        summarize_later(ticket_id)
        return code
    finally:
        path.unlink(missing_ok=True)


def status(_args):
    for ticket in tickets():
        state = "RUNNING" if ticket.get("running") else "waiting"
        if where(ticket) == "pace":
            state = f"PACE {ticket.get('pace', {}).get('state', 'waiting').lower()}"
        waited = (time.time() - ticket["queued_at"]) / 60
        print(f"{state:8} p{ticket['priority']:<3} {ticket['name']:28} {waited:6.1f} min  pid {ticket['pid']}")
    for pid, command in outside_model_jobs():
        print(f"outside  pid {pid}: {command}")
    return 0


def move(args):
    """Change a waiting job's priority. The queue reads priorities from the ticket files."""
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        matches = [t for t in tickets() if t["name"] == args.name and not t.get("running")]
        for ticket in matches:
            ticket["priority"] = args.priority
            write_ticket(QUEUE / f"{ticket['id']}.json", ticket)
            log_event(event="moved", id=ticket["id"], name=args.name, priority=args.priority)
    print(f"moved {len(matches)} waiting job(s)")
    return 0 if matches else 1


def flip(args):
    """Send a waiting job to PACE or back to the Mac. Only before it starts: a running job is never moved."""
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        waiting = [t for t in tickets() if (t["name"] == args.name or t["id"] == args.name) and not t.get("running") and "pace" not in t]
        refused = [t for t in waiting if args.to == "pace" and not t.get("pace_command")]
        for ticket in waiting:
            if ticket in refused:
                continue
            ticket["where"] = args.to
            write_ticket(QUEUE / f"{ticket['id']}.json", ticket)
            log_event(event="where", id=ticket["id"], name=ticket["name"], where=args.to)
    moved = len(waiting) - len(refused)
    if refused:
        print(f"{len(refused)} job(s) have no --pace-command, so they can only run on this Mac", file=sys.stderr)
    print(f"sent {moved} waiting job(s) to {args.to}")
    return 0 if moved else 1


def set_default(args):
    DEFAULT_WHERE.write_text(json.dumps({"default": args.to, "at": time.time()}))
    log_event(event="default_where", where=args.to)
    print(f"new jobs with a PACE command now go to {args.to}")
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
    run_parser.add_argument("--where", choices=["local", "pace"], help="where to run it; by default, the panel's choice for jobs that have a PACE command")
    run_parser.add_argument("--pace-command", help="the shell command to run on PACE, from the copied code folder")
    run_parser.add_argument("--pull", action="append", default=[], help="a path, relative to --cwd, to copy back from PACE afterwards")
    run_parser.add_argument("--about", help="required: a sentence or two on what the experiment does and why, shown in the GPU tab")
    run_parser.add_argument("--output", action="append", default=[], help="required, repeatable: a file or folder it writes, relative to --cwd")
    run_parser.add_argument("command", nargs="+")
    run_parser.set_defaults(handler=run)
    commands.add_parser("status").set_defaults(handler=status)
    move_parser = commands.add_parser("move")
    move_parser.add_argument("--name", required=True)
    move_parser.add_argument("--priority", type=int, required=True)
    move_parser.set_defaults(handler=move)
    where_parser = commands.add_parser("where")
    where_parser.add_argument("--name", required=True, help="a job's name or ticket id")
    where_parser.add_argument("--to", choices=["local", "pace"], required=True)
    where_parser.set_defaults(handler=flip)
    default_parser = commands.add_parser("default")
    default_parser.add_argument("--to", choices=["local", "pace"], required=True)
    default_parser.set_defaults(handler=set_default)
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    QUEUE.mkdir(parents=True, exist_ok=True)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
