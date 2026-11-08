"""What the GPU queue view shows: who has the GPU, who goes next, and how past turns ended.

The queue itself is ops/gpu.py, on the feat/ops worktree. The view reads it with the pipeline view's readers. A waiting job can
get a new priority (gpu.py's `move`), go to PACE or back (`where`), or be cancelled. A running job can only be stopped, through
gpu.py's `stop`, which has its keeper end the whole process group. A job started before keepers existed can't be stopped here,
since stopping its gpu.py would leave the model running. Where new jobs go by default is set through gpu.py's `default`.

For the pictures: a timeline of every job in the last hours, GPU readings kept while the panel runs, and each job's outputs.
gpu.py makes every job say what it does (`about`) and what it writes (`outputs`). Its images and videos are shown, other
files listed. A file is found again from the job's own record each time, so a request names a job and a number, never a
path. Jobs queued before that rule have neither, so the newest image in their --out folder is shown, marked not described.
"""
from collections import deque
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from life.pipeline import ledger_jobs, option, outside_jobs, process_table, read_rows, read_tickets, safely
from settings import GPU_QUEUE_SCRIPT, PIPELINE_PATHS, ROOT

sys.path.insert(0, str(ROOT))
from cloud import pace  # noqa: E402

LEDGER_SHOWN = 30
TAIL_BYTES = 4000
PRIORITY_RANGE = range(0, 1000)
STOP_SECONDS = 5
# gpu.py's own pattern for model jobs doesn't match these, so it will start a job beside one of them.
QUEUE_BLIND = {"mind.run", "benchmarks.run"}
TIMELINE_HOURS = 12
HISTORY = deque(maxlen=400)  # about 20 minutes of readings at the page's 3 second poll, kept while the panel runs
HISTORY_GAP = 2.5
STOP_TIMEOUT = 60  # gpu.py's stop allows the job its grace period, then SIGKILL
MACHINE_EVERY_MS = 3000
MACHINE_STALE_SECONDS = 15
_machine = {"reading": None, "at": 0.0, "feeding": False}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
MEDIA_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES}
IMAGE_SEARCH_LIMIT = 4000  # files looked at per folder, so a huge output folder can't stall the page
IMAGE_CACHE_SECONDS = 10
MEDIA_PER_OUTPUT = 4  # the newest images and videos shown from each output folder
FILES_PER_OUTPUT = 8  # other files listed from each output folder
PACE_CACHE_SECONDS = 30
SUMMARIZING_SECONDS = 900  # a job that finished more recently than this and has no summary yet is still being summarized
RESULT_FIELDS = ("summary", "rating", "rating_label", "rating_reason", "key_numbers", "caveats", "error", "model")
_cache = {"images": {}, "pace": (0, None)}
# Five groups, so each gets one categorical color in DESIGN.md order. Everything not named here is "other".
GROUPS = (("demo", ("wmloop",)), ("training", ("homeostatic",)), ("evals", ("evals",)), ("mind", ("mind",)))


class QueueError(ValueError):
    """A change the queue refused, worded for the page."""


def read_device(text=None):
    """How busy the GPU is and how much memory it has allocated, across every program on the Mac. A failed reading is None, never 0."""
    if text is None:
        try:
            text = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-w", "0"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            text = ""
    busy = re.search(r'"Device Utilization %"=(\d+)', text)
    memory = re.search(r'"Alloc system memory"=(\d+)', text)
    return {"busy_percent": int(busy[1]) if busy else None, "memory_gb": round(int(memory[1]) / 2 ** 30, 1) if memory else None,
            "total_gb": round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30)}


def parse_machine(line):
    """Swap, power and GPU temperature from one line of `macmon pipe`. None if it isn't a reading."""
    try:
        reading = json.loads(line)
        return {"swap_gb": round(reading["memory"]["swap_usage"] / 2 ** 30, 1), "watts": round(reading["all_power"]), "gpu_temp": round(reading["temp"]["gpu_temp_avg"])}
    except (ValueError, KeyError, TypeError):
        return None


def feed_machine():
    """Keep the latest macmon reading. It stops by itself if the panel goes, on its next write to the closed pipe."""
    try:
        process = subprocess.Popen([shutil.which("macmon") or "/opt/homebrew/bin/macmon", "pipe", "-i", str(MACHINE_EVERY_MS)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in process.stdout:
            if reading := parse_machine(line):
                _machine.update(reading=reading, at=time.time())
    except OSError:
        pass
    finally:
        _machine["feeding"] = False


def read_machine():
    """Swap, watts and GPU temperature, or None without macmon. A failed reading is None, never 0."""
    if not _machine["feeding"]:
        _machine["feeding"] = True
        threading.Thread(target=feed_machine, daemon=True).start()
    return _machine["reading"] if time.time() - _machine["at"] < MACHINE_STALE_SECONDS else None


def log_tail(ops, name):
    """The end of a job's log and when it was last written. Only a bare file name inside job_logs can be read."""
    if not name:
        return {"tail": None, "written_at": None}
    path = Path(ops) / "job_logs" / Path(name).name
    try:
        size = path.stat().st_size
        written_at = path.stat().st_mtime
        with path.open("rb") as file:
            file.seek(max(0, size - TAIL_BYTES))
            text = file.read().decode(errors="ignore")
    except OSError:
        return {"tail": None, "written_at": None}
    # A progress bar redraws itself with carriage returns, and only its last drawing means anything.
    return {"tail": "\n".join(line.rstrip("\r").rsplit("\r", 1)[-1] for line in text.split("\n")), "written_at": written_at}


def group(name):
    return next((label for label, prefixes in GROUPS if any(str(name).startswith(prefix) for prefix in prefixes)), "other")


def ticket_extras(ops, ticket):
    """What gpu.py's `where` added to a ticket, read from the file itself. A ticket written before that is local."""
    try:
        raw = json.loads((Path(ops) / "queue" / f"{Path(ticket['id']).name}.json").read_text())
    except (OSError, ValueError):
        raw = {}
    return {"where": raw.get("where") or "local", "pace": raw.get("pace"), "can_pace": bool(raw.get("pace_command")), "group": group(ticket["name"]),
            "about": raw.get("about"), "outputs": raw.get("outputs") or [], "waiting_for": raw.get("waiting_for"), "keeper": bool(raw.get("keeper"))}


def timeline(rows, tickets, now, hours=TIMELINE_HOURS):
    """One bar per job that overlaps the last hours: when it joined, when it got its turn, when it ended, and where."""
    since = now - hours * 3600
    jobs = {}
    for event in rows:
        if "id" not in event or event.get("at") is None:
            continue
        job = jobs.setdefault(event["id"], {"id": event["id"], "name": event.get("name", "?"), "queued": event["at"], "started": None,
                                            "ended": None, "where": "local", "state": "queued", "failed": False})
        kind = event.get("event")
        job["where"] = event.get("where", job["where"])
        if kind == "started":
            job["started"] = event["at"]
        elif kind in ("finished", "gave_up", "cancelled"):
            job["ended"], job["state"] = event["at"], kind
            code = event.get("exit_code")
            job["failed"] = kind == "gave_up" or bool(event.get("timed_out")) or bool(code)
    live = {ticket["id"]: ticket for ticket in tickets}
    shown = []
    for job in jobs.values():
        if job["ended"] is None and job["id"] not in live:
            continue  # lost: no end and no ticket, so there's no honest place to draw it
        if (job["ended"] or now) < since:
            continue
        ticket = live.get(job["id"])
        if ticket:
            job["where"] = ticket.get("where", job["where"])
            job["state"] = "running" if ticket["running"] or (ticket.get("pace") or {}).get("state") == "RUNNING" else "waiting"
        shown.append({**job, "group": group(job["name"])})
    return {"since": since, "now": now, "jobs": sorted(shown, key=lambda job: job["queued"])}


def remember(device, now):
    if not HISTORY or now - HISTORY[-1]["at"] >= HISTORY_GAP:
        HISTORY.append({"at": now, "busy": device.get("busy_percent"), "memory": device.get("memory_gb")})
    return list(HISTORY)


def newest_image(cwd, command, root=ROOT):
    """The newest picture in the folder a job's --out names, or None. Only folders inside the project are searched."""
    out = option(list(command or []), "--out")
    if not out:
        return None
    folder = (Path(cwd or root) / out).resolve()
    if not folder.is_relative_to(Path(root).resolve()) or not folder.is_dir():
        return None
    found = walk(folder, IMAGE_TYPES)
    return max(found, key=lambda item: item[1]) if found else None


def walk(folder, suffixes):
    """(path, modified) for files with these suffixes under a folder, looking at no more than IMAGE_SEARCH_LIMIT entries."""
    found, seen, stack = [], 0, [folder]
    while stack and seen < IMAGE_SEARCH_LIMIT:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            elif suffixes is None or Path(entry.name).suffix.lower() in suffixes:
                found.append((Path(entry.path), entry.stat().st_mtime))
    return found


def kind(path):
    suffix = Path(path).suffix.lower()
    return "image" if suffix in IMAGE_TYPES else "video" if suffix in VIDEO_TYPES else "file"


def output_files(source, root=ROOT):
    """What to show for a job: its declared outputs, or for an older job the newest image its --out folder holds.

    Each entry is {path, kind, name, at, size}, and a folder adds its newest media and a few other files.
    A missing output is listed as missing, since a job that wrote nothing is worth seeing too."""
    root = Path(root).resolve()
    if not source.get("outputs"):
        best = newest_image(source.get("cwd"), source.get("command"), root)
        return {"described": False, "files": [{"path": best[0], "kind": "image", "name": best[0].name, "at": best[1], "size": None}] if best else []}
    files = []
    for output in source["outputs"]:
        path = Path(output).resolve()
        if not path.is_relative_to(root):
            files.append({"path": None, "kind": "outside", "name": str(output), "at": None, "size": None})
        elif path.is_file():
            stat = path.stat()
            files.append({"path": path, "kind": kind(path), "name": path.name, "at": stat.st_mtime, "size": stat.st_size})
        elif path.is_dir():
            everything = sorted(walk(path, None), key=lambda item: item[1], reverse=True)
            media = [item for item in everything if item[0].suffix.lower() in MEDIA_TYPES][:MEDIA_PER_OUTPUT]
            other = [item for item in everything if item[0].suffix.lower() not in MEDIA_TYPES][:FILES_PER_OUTPUT]
            files.append({"path": None, "kind": "folder", "name": f"{path.name}/", "at": everything[0][1] if everything else None, "size": len(everything)})
            files += [{"path": item[0], "kind": kind(item[0]), "name": str(item[0].relative_to(path.parent)), "at": item[1], "size": None} for item in media + other]
        else:
            files.append({"path": None, "kind": "missing", "name": path.name, "at": None, "size": None})
    return {"described": True, "files": files}


def cached_files(job_id, source, now, finished=False):
    """A finished job's files don't change, so they're found once. A running job's are looked at again every few seconds."""
    found_at, files = _cache["images"].get(job_id, (0, None))
    if files is None or (not finished and now - found_at > IMAGE_CACHE_SECONDS):
        files = output_files(source)
        _cache["images"][job_id] = (now, files)
    return files


def shown_files(job_id, source, now, finished=False):
    """The same list, without paths, for the page. A file to fetch is named by its place in this list."""
    found = cached_files(job_id, source, now, finished)
    return {"described": found["described"], "files": [{key: value for key, value in item.items() if key != "path"} | {"n": index}
                                                       for index, item in enumerate(found["files"])]}


def job_sources(ops, tickets, rows):
    """Each job's folder, command, about and outputs, from its live ticket or else the ledger's queued event."""
    sources = {}
    for event in rows:
        if event.get("event") == "queued" and "id" in event:
            sources[event["id"]] = {"cwd": event.get("cwd"), "command": event.get("command") or [], "about": event.get("about"),
                                    "outputs": event.get("outputs") or [], "log": None}
        elif event.get("event") == "started" and event.get("id") in sources:
            sources[event["id"]]["log"] = Path(str(event.get("log"))).name if event.get("log") else None
    for ticket in tickets:
        known = sources.get(ticket["id"], {})
        sources[ticket["id"]] = {**known, "cwd": ticket.get("cwd"), "command": ticket.get("command") or [],
                                 "about": ticket.get("about") or known.get("about"), "outputs": ticket.get("outputs") or known.get("outputs") or []}
    return sources


def read_result(ops, job_id):
    """ops/summarize.py's summary of a finished job, by its ticket id. The id is only ever used as a file name inside results/."""
    name = Path(str(job_id)).name
    if not name or name in (".", "..") or name == "latest":
        return None
    try:
        result = json.loads((Path(ops) / "results" / f"{name}.json").read_text())
    except (OSError, ValueError):
        return None
    return {key: result.get(key) for key in RESULT_FIELDS}


def with_result(ops, job, now):
    """A past job with its summary and rating, or a note that one is on its way. Older jobs never got one."""
    result = read_result(ops, job["id"])
    recent = job.get("at") is not None and now - job["at"] < SUMMARIZING_SECONDS
    return {**job, "result": result, "summarizing": result is None and job.get("state") == "finished" and recent}


def last_result(ops, sources, now):
    """The newest summary, with the job's outputs so the card can show its first picture."""
    try:
        latest = json.loads((Path(ops) / "results" / "latest.json").read_text())
    except (OSError, ValueError):
        return None
    job_id = latest.get("id")
    source = sources.get(job_id, {"outputs": latest.get("outputs") or []})
    return {"id": job_id, "name": latest.get("name"), "group": group(latest.get("name", "")), "about": latest.get("about"),
            "exit_code": latest.get("exit_code"), "seconds": latest.get("seconds"), "at": latest.get("finished_at"),
            **{key: latest.get(key) for key in RESULT_FIELDS}, **shown_files(job_id, source, now, True)}


def past_page(offset=0, limit=LEDGER_SHOWN, paths=PIPELINE_PATHS):
    """Every finished job, newest first, a page at a time, so the page can keep loading as it scrolls."""
    ops = Path(paths["ops"])
    tickets, _ = read_tickets(ops / "queue", process_table())
    rows = read_rows(ops / "gpu_ledger.jsonl")
    live = {ticket["id"] for ticket in tickets}
    past = sorted((job for job in ledger_jobs(rows, live) if job["id"] not in live), key=lambda job: job.get("at") or 0, reverse=True)
    sources = job_sources(ops, tickets, rows)
    now = time.time()
    page = []
    for job in past[max(0, int(offset)):max(0, int(offset)) + max(1, min(int(limit), 100))]:
        source = sources.get(job["id"], {})
        page.append(with_result(ops, {**job, "group": group(job["name"]), "about": source.get("about"), **shown_files(job["id"], source, now, True),
                                      **(log_tail(ops, job.get("log")) if job["failed"] else {})}, now))
    return {"offset": int(offset), "jobs": page, "total": len(past)}


def output_file(job_id, n, paths=PIPELINE_PATHS):
    """One of a job's images or videos, by its place in the job's list. Returns (path, content type) or None."""
    ops = Path(paths["ops"])
    tickets, _ = read_tickets(ops / "queue", process_table())
    tickets = [{**ticket, **ticket_extras(ops, ticket)} for ticket in tickets]
    source = job_sources(ops, tickets, read_rows(ops / "gpu_ledger.jsonl")).get(job_id)
    if not source:
        return None
    files = cached_files(job_id, source, time.time())["files"]
    item = files[n] if 0 <= n < len(files) else None
    if not item or item["kind"] not in ("image", "video") or not item["path"]:
        return None
    return item["path"], MEDIA_TYPES[item["path"].suffix.lower()]


def job_log(job_id, paths=PIPELINE_PATHS):
    """The end of one job's log, found from the ledger, for a log opened on the page."""
    ops = Path(paths["ops"])
    source = job_sources(ops, [], read_rows(ops / "gpu_ledger.jsonl")).get(job_id) or {}
    return {"id": job_id, **log_tail(ops, source.get("log"))}


def pace_status(now):
    checked, state = _cache["pace"]
    if state is None or now - checked > PACE_CACHE_SECONDS:
        state = pace.connection_state()
        _cache["pace"] = (now, state)
    return state


def default_where(ops):
    try:
        return json.loads((Path(ops) / "where.json").read_text()).get("default", "local")
    except (OSError, ValueError):
        return "local"


def time_limit(parts):
    """The --max-hours a job's gpu.py process was started with, in seconds. Tickets don't record it."""
    try:
        return float(option(parts, "--max-hours") or 0) * 3600 or None
    except ValueError:
        return None


def quiet_seconds(log):
    """How long since a job last wrote to its log, so a hang shows. None if there's no log to read."""
    try:
        return max(0.0, time.time() - Path(log).stat().st_mtime)
    except (OSError, TypeError):
        return None


def holder(ticket, job, parts, ops):
    """A ticket with a turn, with what the ledger and its process add. Its ledger entry says "queued" until the job has really started."""
    started = job.get("state") == "started"
    return {**ticket, "started_at": job.get("at") if started else None, "waited": job.get("waited"), "log": job.get("log"),
            "limit_seconds": time_limit(parts), "quiet_seconds": quiet_seconds(job.get("log")), **log_tail(ops, job.get("log"))}


def queue_section(paths, table):
    ops = Path(paths["ops"])
    tickets, stale = read_tickets(ops / "queue", table)
    rows = read_rows(ops / "gpu_ledger.jsonl")
    live = {ticket["id"] for ticket in tickets}
    jobs = {job["id"]: job for job in ledger_jobs(rows, live)}
    processes = {row["pid"]: row["parts"] for row in table}
    tickets = [{**ticket, **ticket_extras(ops, ticket)} for ticket in tickets]
    running = [holder(ticket, jobs.get(ticket["id"], {}), processes.get(ticket["pid"], []), ops) for ticket in tickets if ticket["running"]]
    on_pace = [holder(ticket, jobs.get(ticket["id"], {}), processes.get(ticket["pid"], []), ops) for ticket in tickets
               if ticket["where"] == "pace" and ticket["pace"] is not None]
    outside = [{**job, "queue_waits": job["name"] not in QUEUE_BLIND} for job in outside_jobs(table, tickets)]
    past = sorted((job for job in jobs.values() if job["id"] not in live), key=lambda job: job.get("at") or 0, reverse=True)
    shown = [{**job, "group": group(job["name"]), **(log_tail(ops, job.get("log")) if job["failed"] else {})} for job in past[:LEDGER_SHOWN]]
    # Every job says what it is and shows what it made. Pictures for the gallery come from the same lists.
    sources = job_sources(ops, tickets, rows)
    now = time.time()
    for job in [*running, *on_pace, *shown]:
        source = sources.get(job["id"], {})
        job.update({"about": source.get("about"), **shown_files(job["id"], source, now, job in shown)})
    shown = [with_result(ops, job, now) for job in shown]
    for ticket in tickets:
        if not ticket["running"]:
            ticket["planned"] = [Path(output).name for output in ticket.get("outputs") or []]
    pictures = [{"id": job["id"], "name": job["name"], "group": group(job["name"]), "n": item["n"], "at": item["at"], "kind": item["kind"],
                 "live": job in running or job in on_pace, "described": job["described"]}
                for job in [*running, *on_pace, *shown]
                for item in [next((item for item in job["files"] if item["kind"] in ("image", "video")), None)] if item]
    waiting = [ticket for ticket in tickets if not ticket["running"] and ticket["pace"] is None]
    return {"running": running, "on_pace": on_pace, "outside": outside, "waiting": waiting, "stale": stale,
            "timeline": timeline(rows, tickets, now), "pictures": pictures[:12], "default_where": default_where(ops),
            "last_result": last_result(ops, sources, now),
            "past": shown, "past_total": len(past), "finished": sum(job["state"] == "finished" for job in past),
            "failed": sum(job["failed"] for job in past), "available": ops.is_dir()}


def waiting_ticket(ops, ticket_id):
    """The live ticket with this id, which must still be waiting, and the whole line."""
    tickets, _ = read_tickets(Path(ops) / "queue", process_table())
    ticket = next((ticket for ticket in tickets if ticket["id"] == ticket_id), None)
    if ticket is None:
        raise QueueError("That job isn't in the queue any more.")
    if ticket["running"]:
        raise QueueError(f"{ticket['name']} has its turn now. The panel only changes jobs that are waiting.")
    return ticket, tickets


def move(ticket_id, priority, paths=PIPELINE_PATHS, script=GPU_QUEUE_SCRIPT):
    """Give a waiting job a new priority. gpu.py moves every waiting job with a name, so a name shared by two is refused."""
    if isinstance(priority, bool) or not isinstance(priority, int) or priority not in PRIORITY_RANGE:
        raise QueueError(f"A priority is a whole number from {PRIORITY_RANGE.start} to {PRIORITY_RANGE.stop - 1}.")
    ops = Path(paths["ops"])
    ticket, tickets = waiting_ticket(ops, ticket_id)
    if sum(other["name"] == ticket["name"] and not other["running"] for other in tickets) > 1:
        raise QueueError(f"More than one waiting job is named {ticket['name']}, and gpu.py moves by name. Move them from the terminal.")
    if not Path(script).is_file():
        raise QueueError(f"The queue's gpu.py isn't there: {script}")
    # gpu.py finds out/ops from KOKOPELLI_ROOT, so it changes the same queue this page reads.
    done = subprocess.run([sys.executable, str(script), "move", "--name", ticket["name"], "--priority", str(priority)],
                          capture_output=True, text=True, timeout=30, env={**os.environ, "KOKOPELLI_ROOT": str(ops.parent.parent)})
    if done.returncode:
        raise QueueError(f"gpu.py didn't move it: {(done.stderr or done.stdout).strip() or 'no waiting job had that name'}")
    return {"moved": ticket["name"], "priority": priority}


def gpu(script, ops, *args, timeout=30):
    """Run one of gpu.py's own commands on the queue this page reads."""
    if not Path(script).is_file():
        raise QueueError(f"The queue's gpu.py isn't there: {script}")
    done = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "KOKOPELLI_ROOT": str(Path(ops).parent.parent)})
    if done.returncode:
        message = (done.stderr or done.stdout).strip()
        if "invalid choice" in message:
            message = "This gpu.py doesn't know about PACE yet. Its owner is applying that change."
        raise QueueError(message or f"gpu.py refused: {' '.join(args)}")
    return done.stdout.strip()


def send(ticket_id, where, paths=PIPELINE_PATHS, script=GPU_QUEUE_SCRIPT, state=None):
    """Send a waiting job to PACE or back to the Mac. PACE has to be set up and connected first, so the job doesn't just fail there."""
    if where not in ("local", "pace"):
        raise QueueError("A job runs either on this Mac or on PACE.")
    ops = Path(paths["ops"])
    ticket, _ = waiting_ticket(ops, ticket_id)
    if where == "pace":
        if not ticket_extras(ops, ticket)["can_pace"]:
            raise QueueError(f"{ticket['name']} has no PACE command. Its Mac command uses MLX, which PACE can't run.")
        state = state or pace.connection_state()
        if not state["ready"]:
            raise QueueError("PACE isn't ready: " + (f"fill in {', '.join(state['missing'])}." if state["missing"] else "open the SSH connection first (cloud/README.md)."))
    gpu(script, ops, "where", "--name", ticket["id"], "--to", where)
    return {"sent": ticket["name"], "where": where}


def set_default(where, paths=PIPELINE_PATHS, script=GPU_QUEUE_SCRIPT):
    if where not in ("local", "pace"):
        raise QueueError("New jobs go either to this Mac or to PACE.")
    gpu(script, paths["ops"], "default", "--to", where)
    return {"default": where}


def stop(ticket_id, paths=PIPELINE_PATHS, script=GPU_QUEUE_SCRIPT):
    """End a running job through gpu.py, so its keeper takes down the whole process group and writes the ledger."""
    ops = Path(paths["ops"])
    tickets, _ = read_tickets(ops / "queue", process_table())
    ticket = next((ticket for ticket in tickets if ticket["id"] == ticket_id and ticket["running"]), None)
    if ticket is None:
        raise QueueError("That job isn't running any more.")
    if not ticket_extras(ops, ticket)["keeper"]:
        raise QueueError(f"{ticket['name']} started before jobs had keepers. Stopping it here would leave the model running, so stop its own process.")
    gpu(script, ops, "stop", "--name", ticket_id, timeout=STOP_TIMEOUT)
    return {"stopped": ticket["name"]}


def stopped(pid):
    """Gone, or a zombie waiting for its parent to collect it. Either way it can't take a turn."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return not state or state.startswith("Z")


def cancel(ticket_id, paths=PIPELINE_PATHS):
    """Stop a waiting job's gpu.py before it gets a turn, and note it in the ledger."""
    ops = Path(paths["ops"])
    # gpu.py only marks a ticket running while it holds this lock, so holding it here means the job can't start in between.
    with (ops / "gpu.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ticket, _ = waiting_ticket(ops, ticket_id)
        os.kill(ticket["pid"], signal.SIGTERM)
        deadline = time.time() + STOP_SECONDS
        while not stopped(ticket["pid"]):
            if time.time() > deadline:
                raise QueueError(f"{ticket['name']} was asked to stop but is still there after {STOP_SECONDS} s.")
            time.sleep(0.1)
        # SIGTERM skips gpu.py's own cleanup, so its ticket and ledger line are written here.
        (ops / "queue" / f"{Path(ticket['id']).name}.json").unlink(missing_ok=True)
        with (ops / "gpu_ledger.jsonl").open("a") as ledger:
            ledger.write(json.dumps({"at": time.time(), "event": "cancelled", "id": ticket["id"], "name": ticket["name"], "by": "panel"}) + "\n")
    return {"cancelled": ticket["name"]}


def collect(paths=PIPELINE_PATHS, listing=None, device=None, now=None):
    """Everything measured right now."""
    now = time.time() if now is None else now
    empty = {"running": [], "on_pace": [], "outside": [], "waiting": [], "stale": [], "past": [], "past_total": 0, "finished": 0, "failed": 0,
             "timeline": {"since": now - TIMELINE_HOURS * 3600, "now": now, "jobs": []}, "pictures": [], "default_where": "local",
             "last_result": None}
    section = safely(queue_section, empty, paths, process_table(listing))
    reading = read_device(device)
    return {"now": now, "device": reading, "machine": read_machine() if device is None else None, "history": remember(reading, now), "pace": safely(pace_status, {"ready": False, "missing": []}, now), **section}
