"""Take turns on the GPU: one model job at a time, in priority order, with a ledger of every job.

Cosmos and Qwen each need about 18 GB, so two model jobs at once can run a 36 GB Mac out of memory.

    python3 kokopelli/ops/gpu.py run --name wmloop_demo --priority 10 --cwd PATH \
        --about "what it tests and why, in a sentence or two" --output runs/wmloop_demo -- CMD ARGS...
    python3 kokopelli/ops/gpu.py status

Every job needs --about and at least one --output (relative to --cwd), so the panel's GPU tab can say what
each experiment is and show what it made. The owner asked for both; a job without them isn't queued.

`run` blocks until the job has had its turn and finished, then exits with the job's own code, so a
caller running it in the background is told when the job is done. Lower priority numbers go first;
equal priorities go in arrival order. Standard library only, plus macmon (Homebrew) for the machine readings if it's there.

Once a job has its turn, a small keeper process owns it. If the `run` that queued it is killed or its terminal closes, the
job carries on and the queue still counts it, so nothing else can start beside it. To end one on purpose:
    python3 kokopelli/ops/gpu.py stop --name x               # SIGTERM to the job's whole process group, SIGKILL after 30 s
Before queueing, `run` checks the job can start at all (folder, executable, module or script, outputs), so a bad path
fails in seconds instead of after a wait for its turn. `gpu.py check [--cwd D] [--output O] [--gb N] -- CMD` runs the same
check alone, plus free memory. `run --dry-run` runs the command with KOKO_DRY_RUN=1, which the world-model scripts take to
mean: paint one latent, label the sidecar a dry run, exit 0 (half an hour's limit unless --max-hours says otherwise).
`--gb N` holds a job until ram_share.py says N GB is free; without --gb a job holds for its name's last good peak plus
10%. A new job also waits while the GPU is at 95 C or hotter. `status` warns on battery or Low Power Mode, says why each
job is waiting and how long a running job's log has been quiet. A Python process over 8 GB that no ticket owns counts as an outside model job, whatever its name.

A job can instead run on PACE, if it gives a command that works there:
    python3 kokopelli/ops/gpu.py run --name x --pace-command "python -m thing --cuda" --pull out/x [--where pace] -- MAC CMD
    python3 kokopelli/ops/gpu.py where --name x --to pace     # move a waiting job to PACE, or back
    python3 kokopelli/ops/gpu.py default --to pace            # where new jobs with a PACE command go
PACE jobs don't take a turn on this Mac, so they don't hold up the local line. kokopelli/ops/cloud/pace.py does the work.
A ticket with no `where` is local, so tickets written before this existed behave as they always did.
"""
import argparse
import ctypes
import fcntl
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("KOKOPELLI_ROOT", Path.home() / "Desktop/kokopelli"))
CODE = Path(os.environ.get("KOKOPELLI_CODE", Path.home() / "Desktop/kokopelli"))  # where kokopelli/ops/cloud/ lives, which tests don't move
STATE = ROOT / "out/ops"
QUEUE = STATE / "queue"
LEDGER = STATE / "gpu_ledger.jsonl"
LOCK = STATE / "gpu.lock"
LOGS = STATE / "job_logs"
DEFAULT_WHERE = STATE / "where.json"
ABOUT_LIMIT = 400
POLL_SECONDS = float(os.environ.get("KOKOPELLI_GPU_POLL", 15))
GRACE_SECONDS = float(os.environ.get("KOKOPELLI_GPU_GRACE", 30))    # from SIGTERM to SIGKILL when a job is stopped
SAMPLE_SECONDS = float(os.environ.get("KOKOPELLI_GPU_SAMPLE", 15))  # how often the keeper reads the machine during a job
DRY_RUN_HOURS = 0.5                                                 # a dry run's time limit unless --max-hours says otherwise
HOT_C = float(os.environ.get("KOKOPELLI_GPU_HOT_C", 95))           # a new job waits while the GPU is this hot or hotter
GB_MARGIN = 1.1                                                     # --gb default: the last good run's peak plus 10%
HEAVY_PYTHON_GB = 8                                                 # no small script is this big, and every model load is

# Model jobs started without this wrapper still count as using the GPU.
MODEL_JOB = re.compile(
    r"homeostatic\.(train|evaluate|experiment)|life\.overnight|txt2video|img2video|collect\.py"
    r"|runtime\.run .*--(wm cosmos|agent qwen)|mlx_vlm\.(convert|generate|lora)"
)


class _Usage(ctypes.Structure):  # rusage_info_v0 from <sys/resource.h>
    _fields_ = [("uuid", ctypes.c_ubyte * 16)] + [(name, ctypes.c_uint64) for name in (
        "user", "system", "idle_wakeups", "interrupt_wakeups", "pageins", "wired", "resident", "phys_footprint", "start", "exit")]


_LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")


def footprint_gb(pid):
    """A process's real memory, as Activity Monitor counts it. `ps` RSS leaves out Metal buffers, so an MLX model holding
    19 GB shows there as 0.2 GB. None if the process has gone or can't be read."""
    usage = _Usage()
    return None if _LIBPROC.proc_pid_rusage(pid, 0, ctypes.byref(usage)) else usage.phys_footprint / 2 ** 30


def process_table():
    output = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,command="], capture_output=True, text=True).stdout
    table = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            pid, resident = int(parts[0]), int(parts[2]) / 2 ** 20
            table.append({"pid": pid, "parent": int(parts[1]), "gb": max(resident, footprint_gb(pid) or 0), "command": parts[3]})
    return table


def tree_of(roots, table):
    """These pids and everything under them."""
    children = {}
    for row in table:
        children.setdefault(row["parent"], []).append(row["pid"])
    found, stack = set(), list(roots)
    while stack:
        pid = stack.pop()
        if pid not in found:
            found.add(pid)
            stack += children.get(pid, [])
    return found


def outside_model_jobs():
    """Model processes on the machine that no ticket owns: known model commands, and any Python big enough to hold a model.
    The size test catches what a list of names can't, like a job left running after its queue process was killed."""
    if os.environ.get("KOKOPELLI_GPU_IGNORE_OUTSIDE"):  # for the tests, which run beside real jobs
        return []
    table = process_table()
    owned = tree_of([t["pid"] for t in tickets() if t.get("running")], table)
    jobs = []
    for row in table:
        command = row["command"]
        if row["pid"] in owned or "kokopelli/ops/gpu.py" in command or re.match(r"\S*(zsh|bash|sh) -c ", command):
            continue
        heavy = row["gb"] >= HEAVY_PYTHON_GB and re.match(r"(\S*/)?[Pp]ython[\d.]*(\s|$)", command)
        if MODEL_JOB.search(command) or heavy:
            jobs.append((row["pid"], command[:160]))
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
    """Start kokopelli/ops/summarize.py for a finished job in its own process, so the job's exit isn't held up by it."""
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


def memory_short(gb):
    """What ram_share.py says is missing for a job that asked for gb, or None. A broken reading never holds a job up."""
    try:
        sys.path.insert(0, str(CODE))
        from kokopelli.ops import ram_share
        room, _, _ = ram_share.room_gb()
    except Exception:
        return None
    return None if room >= gb else f"needs {gb:g} GB of memory, {max(room, 0):.1f} GB free"


def blocked_by(ticket, line):
    """Why this ticket can't start now, in words, or None if it can."""
    holder = next((t for t in line if t.get("running")), None)
    if holder:
        return f"{holder['name']} has the GPU"
    if not line or line[0]["id"] != ticket["id"]:
        return f"behind {line[0]['name']}" if line else "not in the line"
    outside = outside_model_jobs()
    if outside:
        return f"outside job, pid {outside[0][0]}: {outside[0][1][:80]}"
    hot = gpu_too_hot()
    if hot:
        return hot
    return memory_short(ticket["gb"]) if ticket.get("gb") else None


def gpu_too_hot():
    """Why a new job should wait for the GPU to cool, or None. 4 of 22 measured jobs reached 100 C; starting a paint on a
    hot GPU stacks its heat on the last one's. No reading (macmon missing) never holds a job up."""
    temp = read_machine().get("gpu_temp")
    return f"GPU at {temp:.0f} C, waits below {HOT_C:g} C" if temp is not None and temp >= HOT_C else None


def last_peak_gb(name):
    """The default --gb for a job: its last successful, non-dry run's peak footprint plus a margin, or 0 if none."""
    peak = 0
    try:
        lines = LEDGER.read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (event.get("event") == "finished" and event.get("name") == name and event.get("exit_code") == 0
                and not event.get("dry_run") and event.get("peak_job_gb")):
            peak = event["peak_job_gb"]
    return round(peak * GB_MARGIN, 1) if peak else 0


def power_warning():
    """A warning line when the Mac is on battery or in Low Power Mode, else None. A 150-frame paint took 1,782 s on
    battery against 782-935 s on AC (docs/PAINT_PROFILE.md)."""
    pmset = os.environ.get("KOKOPELLI_PMSET", "/usr/bin/pmset")
    try:
        active = subprocess.run([pmset, "-g"], capture_output=True, text=True, timeout=5).stdout
        battery = subprocess.run([pmset, "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    notes = []
    if re.search(r"^\s*(lowpowermode|powermode)\s+1\b", active, re.M):
        notes.append("Low Power Mode is on")
    if "'Battery Power'" in battery:
        notes.append("the Mac is on battery")
    return f"warning: {' and '.join(notes)}; paints ran about 2x slower on battery (docs/PAINT_PROFILE.md)" if notes else None


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
            reason = blocked_by(ticket, line)
            if reason is None:
                ticket.pop("waiting_for", None)
                ticket["running"] = True
                write_ticket(path, ticket)
                return "go"
            if ticket.get("waiting_for") != reason:
                ticket["waiting_for"] = reason
                write_ticket(path, ticket)
        time.sleep(POLL_SECONDS)


def run_on_pace(ticket, path, args, queued_at):
    """The job's turn, on PACE. It fails loudly rather than falling back to the Mac, because the user chose PACE for it."""
    sys.path.insert(0, str(CODE))
    from kokopelli.ops.cloud import pace

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


CHECK_TIMEOUT = 20                                 # seconds for the job's interpreter to look up its module
PYTHON = re.compile(r"[Pp]ython[\d.]*$")
PYTHON_VALUE_FLAGS = {"-W", "-X", "-Q"}            # interpreter flags that take the next word as their value
WRAPPERS = ("ram_share.py", "memguard.py")         # `python3 X.py hold/run ... -- CMD`: the job is CMD


def unwrap(command):
    """The command a job really runs and the environment `env` gives it, under any `env K=V` and ram_share/memguard wrappers."""
    words, env = list(command), {}
    for _ in range(8):
        if words and Path(words[0]).name == "env":
            words = words[1:]
            while words and "=" in words[0] and not words[0].startswith("-"):
                key, value = words.pop(0).split("=", 1)
                env[key] = value
            continue
        if len(words) > 1 and PYTHON.match(Path(words[0]).name) and Path(words[1]).name in WRAPPERS and "--" in words:
            words = words[words.index("--") + 1:]
            continue
        break
    return words, env


def resolve(word, cwd, env):
    """Where an executable lives, as the keeper would find it, or None."""
    if "/" in word:
        path = Path(cwd, word) if cwd else Path(word)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    return shutil.which(word, path=env.get("PATH", os.environ.get("PATH")))


def python_target(words):
    """(flags, "-m" or "script", module or path) for a Python command line, or None if it runs `-c` code or nothing."""
    flags, i = [], 1
    while i < len(words) and words[i].startswith("-") and words[i] not in ("-m", "-c", "-"):
        width = 2 if words[i] in PYTHON_VALUE_FLAGS else 1
        flags += words[i:i + width]
        i += width
    if i >= len(words) or words[i] in ("-c", "-"):
        return None
    if words[i] == "-m":
        return (flags, "-m", words[i + 1]) if i + 1 < len(words) else None
    return flags, "script", words[i]


LOOKUP = ("import importlib.util, sys\n"
          "try:\n    found = importlib.util.find_spec(sys.argv[1]) is not None\n"
          "except Exception:\n    found = False\n"
          "sys.exit(0 if found else 1)")
COMPILES = "import sys; compile(open(sys.argv[1], 'rb').read(), sys.argv[1], 'exec')"


def preflight(command, cwd=None, outputs=(), gb=0, memory=True):
    """What would make this job fail before it does any work, as a list of problems; empty if none were found.
    Checks that the folder exists, the executable resolves, a Python job's module or script is there (in the job's own
    interpreter, so a 3.10 venv is checked as 3.10), each output's folder is writable and, with memory, that gb is free.
    Nothing here imports the job's code: a module is only looked up, a script only compiled."""
    problems = []
    if cwd and not Path(cwd).is_dir():
        return [f"--cwd {cwd} doesn't exist"]
    words, env = unwrap(command)
    if not words:
        return ["no command to run"]
    executable = resolve(words[0], cwd, env)
    if not executable:
        problems.append(f"command not found: {words[0]!r}" + (f" (from {cwd})" if cwd else ""))
    elif PYTHON.match(Path(words[0]).name):
        target = python_target(words)
        job_env = {**os.environ, **env}
        if target and target[1] == "-m":
            isolated = [f for f in target[0] if f in ("-I", "-E", "-s", "-S")]
            try:
                found = subprocess.run([executable, *isolated, "-c", LOOKUP, target[2]], cwd=cwd or None, env=job_env,
                                       capture_output=True, timeout=CHECK_TIMEOUT).returncode == 0
            except subprocess.TimeoutExpired:
                found = True   # a slow package import isn't a missing module; the job may still be fine
            except OSError:
                found = False
            if not found:
                problems.append(f"{executable} can't find module {target[2]!r}" + (f" from {cwd}" if cwd else ""))
        elif target:
            script = Path(cwd or ".", target[2])
            if not script.is_file():
                problems.append(f"script not found: {script}")
            else:
                try:
                    done = subprocess.run([executable, "-c", COMPILES, str(script)], env=job_env, capture_output=True, text=True,
                                          timeout=CHECK_TIMEOUT)
                except (OSError, subprocess.SubprocessError):
                    done = None
                if done and done.returncode:
                    problems.append(f"{script} doesn't compile under {executable}: {done.stderr.strip().splitlines()[-1:]}")
    for output in outputs:
        folder = Path(output)
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if not os.access(folder, os.W_OK):
            problems.append(f"output {output} can't be written: {folder} isn't writable")
    if memory and gb:
        short = memory_short(gb)
        if short:
            problems.append(short)
    return problems


def check(args):
    """`gpu.py check`: the pre-flight on its own, without queueing. Exit 0 if the job looks runnable, 1 if not."""
    outputs = [str(Path(args.cwd or os.getcwd(), output).resolve()) for output in args.output]
    problems = preflight(args.command, args.cwd, outputs, args.gb)
    for problem in problems:
        print(f"FAILED: {problem}", file=sys.stderr)
    if not problems:
        print("ok")
    return 1 if problems else 0


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
    if args.gb is None:
        args.gb = 0 if args.dry_run else last_peak_gb(args.name)
        if args.gb:
            print(f"{args.name}: --gb {args.gb:g} from its last good run's peak (+10%); --gb 0 turns the hold off", file=sys.stderr)
    problems = [] if args.no_check else preflight(args.command, args.cwd, outputs, memory=False)  # --gb waits in line instead
    if problems:
        for problem in problems:
            print(f"{args.name} wasn't queued: {problem}. (gpu.py check runs this alone; --no-check skips it.)", file=sys.stderr)
        return 2
    env = {}
    if args.dry_run:
        env["KOKO_DRY_RUN"] = "1"            # the job's own code decides how small a dry run is
        about = f"[dry run] {about}"[:ABOUT_LIMIT]
        args.max_hours = args.max_hours or DRY_RUN_HOURS
    now = time.time()
    ticket_id = f"{int(now * 1000)}-{os.getpid()}"
    ticket = {"id": ticket_id, "name": args.name, "priority": args.priority, "pid": os.getpid(),
              "queued_at": now, "cwd": args.cwd, "command": args.command, "running": False,
              "where": chosen, "pace_command": args.pace_command, "pull": args.pull, "about": about, "outputs": outputs, "gb": args.gb,
              **({"env": env, "dry_run": True} if env else {})}
    path = QUEUE / f"{ticket_id}.json"
    write_ticket(path, ticket)
    log_event(event="queued", id=ticket_id, name=args.name, priority=args.priority, command=args.command, cwd=args.cwd, where=chosen,
              about=about, outputs=outputs, **({"dry_run": True} if env else {}))
    deadline = now + args.give_up_hours * 3600 if args.give_up_hours else None
    handed_over = False
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
        with (LOGS / "keeper.log").open("a") as errors:
            keeper = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "keep", "--id", ticket_id, "--log", str(log_path), "--max-hours", str(args.max_hours)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, start_new_session=True)
        handed_over = True
        try:
            code = keeper.wait()
        except KeyboardInterrupt:
            print(f"{args.name} keeps running. To end it: gpu.py stop --name {args.name}", file=sys.stderr, flush=True)
            return 130
        print(f"{args.name} finished with exit code {code}, log at {log_path}", flush=True)
        return code
    finally:
        if not handed_over:
            path.unlink(missing_ok=True)


def macmon_path():
    return os.environ.get("KOKOPELLI_MACMON", shutil.which("macmon") or "/opt/homebrew/bin/macmon")


def read_machine():
    """One reading from macmon: {} if it's missing or fails, so a job never depends on it."""
    try:
        text = subprocess.run([macmon_path(), "pipe", "-s", "1", "-i", "200"], capture_output=True, text=True, timeout=5).stdout
        reading = json.loads(text)
        memory = reading["memory"]
        return {"gpu_busy": reading["gpu_active_ratio"], "watts": reading["all_power"], "gpu_temp": reading["temp"]["gpu_temp_avg"],
                "ram_gb": memory["ram_usage"] / 2 ** 30, "swap_gb": memory["swap_usage"] / 2 ** 30}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {}


def machine_summary(samples):
    """What a job's readings add up to, for the ledger. Fields with no readings are left out."""
    def values(key):
        return [row[key] for row in samples if row.get(key) is not None]
    out = {}
    if values("job_gb"):
        out["peak_job_gb"] = round(max(values("job_gb")), 2)
    if values("swap_gb"):
        out["peak_swap_gb"] = round(max(values("swap_gb")), 2)
        out["swap_grew_gb"] = round(max(values("swap_gb")) - values("swap_gb")[0], 2)
    if values("gpu_busy"):
        out["gpu_busy_mean"] = round(sum(values("gpu_busy")) / len(values("gpu_busy")), 3)
    if values("watts"):
        out["watts_mean"] = round(sum(values("watts")) / len(values("watts")), 1)
    if values("gpu_temp"):
        out["gpu_temp_max"] = round(max(values("gpu_temp")), 1)
    return out


def keep(args):
    """Own a job through its turn: start it, read the machine, enforce the time limit, stop it on request, write the ledger.
    It runs in its own session, so whatever ended the `run` that started it doesn't end the job or lose track of it."""
    stop_asked = []
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: stop_asked.append(time.time()))
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    path = QUEUE / f"{args.id}.json"
    log_path = Path(args.log)
    started = time.time()
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ticket = json.loads(path.read_text())
        ticket.update(pid=os.getpid(), keeper=True, log=args.log)
        write_ticket(path, ticket)
    limit = args.max_hours * 3600 if args.max_hours else None
    metrics = log_path.with_suffix(".metrics.jsonl")
    samples, next_sample, ending_since, timed_out = [], 0.0, None, False
    with log_path.open("w") as log:
        process = subprocess.Popen(["caffeinate", "-is", *ticket["command"]], cwd=ticket.get("cwd") or None, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, **ticket.get("env", {})})

    def signal_job(number):
        try:
            os.killpg(process.pid, number)
        except ProcessLookupError:
            pass

    while True:
        try:
            code = process.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            pass
        now = time.time()
        over_time = limit is not None and now - started > limit
        if (stop_asked or over_time) and ending_since is None:
            timed_out = over_time and not stop_asked
            ending_since = now
            signal_job(signal.SIGTERM)
        if ending_since is not None and now - ending_since > GRACE_SECONDS:
            signal_job(signal.SIGKILL)
        if now >= next_sample:
            next_sample = now + SAMPLE_SECONDS
            table = process_table()
            sample = {"at": round(now), "job_gb": round(sum(r["gb"] for r in table if r["pid"] in tree_of([process.pid], table)), 2), **read_machine()}
            samples.append(sample)
            with metrics.open("a") as out:
                out.write(json.dumps(sample) + "\n")
    # A signal the queue didn't send (7 of the 15 failures up to 2026-11-08 were a SIGTERM from outside): name it, so the
    # ledger tells it apart from a crash. The usual senders are a hand `kill`/`pkill` and the system's out-of-memory killer.
    outside = signal.Signals(-code).name if code < 0 and not stop_asked and not timed_out and -code in signal.valid_signals() else None
    if outside:
        with log_path.open("a") as log:
            log.write(f"\n[gpu.py] the job ended on {outside}, which the queue didn't send. Use gpu.py stop to end a job.\n")
    if timed_out:
        code = 124
    peak_gb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**30
    log_event(event="finished", id=args.id, name=ticket["name"], exit_code=code, timed_out=timed_out, stopped=bool(stop_asked),
              seconds=time.time() - started, peak_rss_gb=round(peak_gb, 2), log=args.log, where="local", **machine_summary(samples),
              **({"outside_signal": outside} if outside else {}), **({"dry_run": True} if ticket.get("dry_run") else {}))
    path.unlink(missing_ok=True)
    summarize_later(args.id)
    return code


def stop(args):
    """End a running job. The keeper does it, so the ledger records it like any other ending."""
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        running = [t for t in tickets() if t.get("running") and where(t) == "local" and args.name in (t["name"], t["id"])]
        kept = [t for t in running if t.get("keeper")]
        for ticket in kept:
            os.kill(ticket["pid"], signal.SIGTERM)
    for ticket in running:
        if not ticket.get("keeper"):
            print(f"{ticket['name']} was started before jobs had keepers; stopping its gpu.py would leave the model running. Stop the job's own process.", file=sys.stderr)
    if not kept:
        print(f"no running job called {args.name} that can be stopped here", file=sys.stderr)
        return 1
    deadline = time.time() + GRACE_SECONDS + 15
    while time.time() < deadline and any((QUEUE / f"{t['id']}.json").exists() and alive(t["pid"]) for t in kept):
        time.sleep(0.2)
    print(f"stopped {len(kept)} job(s)")
    return 0


def quiet_note(ticket):
    try:
        minutes = (time.time() - Path(ticket["log"]).stat().st_mtime) / 60
    except (KeyError, OSError):
        return ""
    return f"  log quiet {minutes:.0f} min" if minutes >= 1 else ""


def finished_counts():
    """Every finished job in the ledger, by how it ended. Exit 75 is a polite yield and a stop the owner asked for is not a failure."""
    counts = {"ok": 0, "failed": 0, "stopped": 0, "yielded(75)": 0}
    try:
        lines = LEDGER.read_text().splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") != "finished":
            continue
        code = event.get("exit_code")
        kind = "stopped" if event.get("stopped") else "yielded(75)" if code == 75 else "ok" if code == 0 else "failed"
        counts[kind] += 1
    return counts


def status(_args):
    queued, outside = tickets(), outside_model_jobs()
    warning = power_warning()
    if warning:
        print(warning)
    if not queued and not outside:
        print("idle")
        return 0
    for ticket in queued:
        state = "RUNNING" if ticket.get("running") else "waiting"
        if where(ticket) == "pace":
            state = f"PACE {ticket.get('pace', {}).get('state', 'waiting').lower()}"
        waited = (time.time() - ticket["queued_at"]) / 60
        note = quiet_note(ticket) if ticket.get("running") else f"  ({ticket['waiting_for']})" if ticket.get("waiting_for") else ""
        print(f"{state:8} p{ticket['priority']:<3} {ticket['name']:28} {waited:6.1f} min  pid {ticket['pid']}{note}")
    for pid, command in outside:
        print(f"outside  pid {pid}: {command}")
    print("finished " + ", ".join(f"{count} {kind}" for kind, count in finished_counts().items()))
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
    run_parser.add_argument("--gb", type=float, default=None, help="hold the job until ram_share.py says this much memory "
                            "is free (default: the last good run of this --name's peak plus 10%%, else no hold)")
    run_parser.add_argument("--where", choices=["local", "pace"], help="where to run it; by default, the panel's choice for jobs that have a PACE command")
    run_parser.add_argument("--pace-command", help="the shell command to run on PACE, from the copied code folder")
    run_parser.add_argument("--pull", action="append", default=[], help="a path, relative to --cwd, to copy back from PACE afterwards")
    run_parser.add_argument("--about", help="required: a sentence or two on what the experiment does and why, shown in the GPU tab")
    run_parser.add_argument("--output", action="append", default=[], help="required, repeatable: a file or folder it writes, relative to --cwd")
    run_parser.add_argument("--dry-run", action="store_true", help="run it with KOKO_DRY_RUN=1: the job paints one latent and exits")
    run_parser.add_argument("--no-check", action="store_true", help="queue it without the pre-flight (gpu.py check)")
    run_parser.add_argument("command", nargs="+")
    run_parser.set_defaults(handler=run)
    check_parser = commands.add_parser("check", help="pre-flight a job without queueing it: folder, executable, module, outputs, memory")
    check_parser.add_argument("--cwd")
    check_parser.add_argument("--output", action="append", default=[])
    check_parser.add_argument("--gb", type=float, default=0)
    check_parser.add_argument("command", nargs="+")
    check_parser.set_defaults(handler=check)
    commands.add_parser("status").set_defaults(handler=status)
    keep_parser = commands.add_parser("keep", help=argparse.SUPPRESS)
    keep_parser.add_argument("--id", required=True)
    keep_parser.add_argument("--log", required=True)
    keep_parser.add_argument("--max-hours", type=float, default=0)
    keep_parser.set_defaults(handler=keep)
    stop_parser = commands.add_parser("stop", help="end a running job: SIGTERM to its process group, then SIGKILL")
    stop_parser.add_argument("--name", required=True, help="a job's name or ticket id")
    stop_parser.set_defaults(handler=stop)
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
