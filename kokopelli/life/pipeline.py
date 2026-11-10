"""What the Pipeline view shows: every part of the 30-minute system, read from the files each part leaves behind.

Only reads. These folders belong to other sessions and change while we read them, so a half-written line is skipped, a missing
file is empty, and a worktree can vanish. Whether a run is mock or real comes from its config's fields, never from its name.
Nothing here signals a process: a pid counts as alive if `ps` lists it.
"""
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

from kokopelli.life import watch
from kokopelli.settings import HOMEOSTATIC_OUT, PIPELINE_PATHS

# A process that has written nothing for this long isn't called moving, even while it's alive.
STALL_SECONDS = 15 * 60
RECENT_JOBS = 12
HISTORY_SHOWN = 12
TAIL_CHARS = 3000
# 60 ticks of 30 sim-seconds make the 30-minute life (see the agent loop's README), and a tick is only real if it renders about 30 seconds.
TARGET_TICKS = 60
FULL_TICK_SECONDS = 29
FPS = 24
MODEL_MODULES = {"experiments.homeostatic.train", "experiments.homeostatic.evaluate", "experiments.homeostatic.experiment", "kokopelli.life.overnight", "mlx_vlm.convert", "mlx_vlm.generate", "mlx_vlm.lora"}
MODEL_SCRIPTS = {"txt2video.py", "img2video.py", "collect.py"}
# Exit codes a job means as something other than failure.
KNOWN_EXITS = {75: "out of time, can resume"}
BLANK_MARK = "CHANGE_ME"
PREREG_DRAFT = "STATUS: DRAFT"

_parsed = {}


def read_json(path):
    try:
        found = json.loads(Path(path).read_text(errors="ignore"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def read_rows(path):
    """The whole rows of a log someone may be appending to. Any bad line is skipped. A file that hasn't changed isn't parsed again."""
    path = Path(path)
    try:
        info = path.stat()
        known = _parsed.get(path)
        if known and known[0] == (info.st_mtime_ns, info.st_size):
            return known[1]
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    _parsed[path] = ((info.st_mtime_ns, info.st_size), rows)
    return rows


def newest_write(paths):
    times = []
    for path in paths:
        try:
            times.append(Path(path).stat().st_mtime)
        except OSError:
            pass
    return max(times, default=None)


def subfolders(folder):
    try:
        return sorted((path for path in Path(folder).iterdir() if path.is_dir()), key=lambda path: path.name)
    except OSError:
        return []


def arguments(command):
    """A command line as words. `ps` drops quotes, so a prompt with an apostrophe can't be parsed strictly and is split on spaces."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def is_python(parts):
    return bool(parts) and Path(parts[0]).name.lower().startswith("python")


def python_lines(listing):
    """The `ps` lines that are Python itself, so a shell or grep that merely mentions a module is never taken for a run."""
    return [(line, parts) for line in listing.splitlines() if is_python(parts := arguments(line))]


def python_target(parts):
    """What this Python is running: ("module", name) or ("script", file). Words after that are its own arguments, however they read."""
    words = iter(parts[1:])
    for word in words:
        if word == "-m":
            return "module", next(words, "")
        if word in ("-W", "-X"):
            next(words, None)
        elif not word.startswith("-"):
            return "script", Path(word).name
    return None, ""


def runs_module(parts, module):
    return is_python(parts) and python_target(parts) == ("module", module)


def plural(number, thing):
    return f"{number:,} {thing}{'' if number == 1 else 's'}"


def option(parts, name):
    return parts[parts.index(name) + 1] if name in parts[:-1] else None


def ps_listing():
    return subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True).stdout


def process_table(listing=None):
    """Every process as {pid, parent, parts}. A given listing without pids, as in a test, gets pid 0."""
    if listing is None:
        listing = subprocess.run(["ps", "-Ao", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    table = []
    for line in listing.splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)", line)
        pid, parent, command = (int(match[1]), int(match[2]), match[3]) if match else (0, 0, line)
        table.append({"pid": pid, "parent": parent, "parts": arguments(command)})
    return table


def model_job(parts):
    """What this process is, if it holds a model. Mock runs of the loop, mind and benchmarks don't count."""
    if not is_python(parts):
        return None
    kind, target = python_target(parts)
    if kind == "script":
        return target if target in MODEL_SCRIPTS else None
    if target in MODEL_MODULES:
        return target
    if runs_module(parts, "kokopelli.loop.run") and ((option(parts, "--wm") or "mock") != "mock" or (option(parts, "--agent") or "mock") != "mock"):
        return "kokopelli.loop.run"
    if runs_module(parts, "kokopelli.loop.run_mind") and (option(parts, "--agent") or "mock") != "mock":
        return "kokopelli.loop.run_mind"
    if runs_module(parts, "experiments.benchmarks.run") and (option(parts, "--backend") or "mock") != "mock":
        return "experiments.benchmarks.run"
    return None


def is_queue_process(parts):
    return is_python(parts) and python_target(parts) == ("script", "gpu.py")


def read_tickets(folder, table):
    """Tickets in the queue, best first. One whose pid is dead, or is now some other program, is stale and never live."""
    by_pid = {row["pid"]: row for row in table}
    live, stale = [], []
    try:
        paths = list(Path(folder).glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        ticket = read_json(path)
        if not ticket or "pid" not in ticket:
            continue
        row = {"id": ticket.get("id", path.stem), "name": ticket.get("name", path.stem), "priority": ticket.get("priority"), "pid": ticket["pid"],
               "queued_at": ticket.get("queued_at"), "running": bool(ticket.get("running")), "command": ticket.get("command") or [], "cwd": ticket.get("cwd")}
        process = by_pid.get(ticket["pid"])
        (live if process and is_queue_process(process["parts"]) else stale).append(row)
    order = lambda row: (row["priority"] if row["priority"] is not None else 10 ** 6, row["queued_at"] or 0)
    return sorted(live, key=order), sorted(stale, key=order)


def outside_jobs(table, tickets):
    """Model processes not started by a live ticket. These use the GPU too, and the queue waits for them. A child of a job isn't a second job."""
    parents = {row["pid"]: row["parent"] for row in table}
    jobs = {row["pid"]: name for row in table if (name := model_job(row["parts"]))}
    queue_pids = {ticket["pid"] for ticket in tickets}
    found = []
    for pid, name in jobs.items():
        ancestor, seen, inside = parents.get(pid), {pid}, False
        while ancestor and ancestor not in seen:
            if ancestor in queue_pids or ancestor in jobs:
                inside = True
                break
            seen.add(ancestor)
            ancestor = parents.get(ancestor)
        if not inside:
            found.append({"pid": pid, "name": name})
    return sorted(found, key=lambda job: job["pid"])


def ledger_jobs(rows, live_ids):
    """One line per job from the ledger's events. A job that started and neither finished nor still has a live ticket is lost."""
    jobs = {}
    for event in rows:
        if "id" not in event:
            continue
        job = jobs.setdefault(event["id"], {"id": event["id"], "name": event.get("name", "?"), "state": "queued"})
        job["state"] = event.get("event", job["state"])
        job["at"] = event.get("at")
        for key in ("priority", "waited", "exit_code", "timed_out", "seconds", "peak_rss_gb", "stopped", "peak_job_gb", "peak_swap_gb", "swap_grew_gb", "gpu_busy_mean", "watts_mean", "gpu_temp_max"):
            if key in event:
                job[key] = event[key]
        if event.get("log"):
            job["log"] = Path(str(event["log"])).name
    for job in jobs.values():
        if job["state"] in ("queued", "moved", "started") and job["id"] not in live_ids:
            job["state"] = "lost"
        code = job.get("exit_code")
        job["meaning"] = KNOWN_EXITS.get(code)
        job["failed"] = job["state"] in ("lost", "gave_up") or bool(job.get("timed_out")) or (job["state"] == "finished" and bool(code) and code not in KNOWN_EXITS)
    return list(jobs.values())


def gpu_section(paths, table, now):
    tickets, stale = read_tickets(Path(paths["ops"]) / "queue", table)
    outside = outside_jobs(table, tickets)
    rows = read_rows(Path(paths["ops"]) / "gpu_ledger.jsonl")
    jobs = ledger_jobs(rows, {ticket["id"] for ticket in tickets})
    running = [ticket for ticket in tickets if ticket["running"]]
    finished = [job for job in jobs if job["state"] == "finished"]
    return {"tickets": tickets, "stale": stale, "outside": outside, "running": running, "waiting": [ticket for ticket in tickets if not ticket["running"]],
            "busy": bool(running or outside), "jobs": sorted(jobs, key=lambda job: job.get("at") or 0, reverse=True)[:RECENT_JOBS],
            "events": len(rows), "finished": len(finished), "failed": sum(1 for job in jobs if job["failed"]),
            "available": Path(paths["ops"]).is_dir()}


def tests_section(paths, now):
    latest = read_json(Path(paths["ops"]) / "tests_latest.json")
    history = read_rows(Path(paths["ops"]) / "tests_history.jsonl")
    if latest is None:
        return {"available": False, "suites": []}
    suites = []
    for name, row in latest.items():
        if not isinstance(row, dict):
            continue
        past = [entry[name] for entry in history if name in entry]
        suites.append({"name": name, "ok": row.get("ok"), "summary": row.get("summary", ""), "seconds": row.get("seconds"), "at": row.get("at"),
                       "tail": str(row.get("tail") or "")[-TAIL_CHARS:], "history": past[-HISTORY_SHOWN:]})
    return {"available": True, "suites": suites, "failing": [suite["name"] for suite in suites if suite["ok"] is False]}


def loop_mode(config):
    """Mock or real, from what the run was configured to use."""
    if not config:
        return "unknown"
    uses = [config.get(part, "?") for part in ("sim", "wm", "agent")]
    if "?" in uses:
        return "unknown"
    mocks = sum(1 for use in uses if use == "mock")
    return "mock" if mocks == 3 else "real" if mocks == 0 else "mixed"


def rendered_seconds(events, config):
    """Seconds of video per tick, from the frames the last rendered tick really logged. Chunks share their conditioning frames."""
    chunks = [event for event in events if event.get("kind") == "wm_chunk" and isinstance(event.get("data"), dict)]
    if not chunks:
        return None
    last = chunks[-1].get("tick")
    frames = [event["data"].get("frames") or 0 for event in chunks if event.get("tick") == last]
    return round(max(0, sum(frames) - (config.get("cond_frames") or 0) * (len(frames) - 1)) / FPS, 1)


def module_processes(table, module):
    return [row["parts"] for row in table if runs_module(row["parts"], module)]


def run_is_alive(folder, processes):
    """Whether a process is writing this run. One that names a folder must name this one; one that names none could be any run."""
    for parts in processes:
        named = option(parts, "--out") or option(parts, "--resume")
        if named is None or Path(named).name == Path(folder).name:
            return True
    return False


def read_loop_run(folder, processes, now):
    """A run of the agent loop, including the mind's, which has the same files."""
    folder = Path(folder)
    config = read_json(folder / "config.json")
    if config is None and not (folder / "events.jsonl").exists():
        return None
    config = config or {}
    events = read_rows(folder / "events.jsonl")
    checkpoint = read_json(folder / "checkpoint.json") or {}
    finished_ticks = {event.get("tick") for event in events if event.get("kind") == "tick_end"}
    done = len(finished_ticks)
    end = next((event.get("data") or {} for event in reversed(events) if event.get("kind") == "run_end"), None)
    wrote = newest_write([folder / "events.jsonl", folder / "checkpoint.json"])
    quiet = now - wrote if wrote else None
    alive = run_is_alive(folder, processes) and end is None
    state = "finished" if end is not None else ("moving" if quiet is not None and quiet < STALL_SECONDS else "alive, quiet") if alive else "stopped"
    return {"name": folder.name, "mode": loop_mode(config), "sim": config.get("sim"), "wm": config.get("wm"), "agent": config.get("agent"), "context": config.get("context"),
            "preset": config.get("wm_preset"), "target": config.get("ticks"), "done": done, "next_tick": checkpoint.get("next_tick"), "state": state, "at": wrote, "events": len(events),
            "rendered_s": rendered_seconds(events, config), "tick_seconds": config.get("tick_seconds"), "fallbacks": (end or {}).get("fallbacks"),
            "invalid": (end or {}).get("invalid_replies"), "total_s": ((end or {}).get("seconds") or {}).get("total"), "video": (folder / "final.mp4").is_file(),
            "alarms": sum(1 for event in events if event.get("kind") == "leak_alarm")}


def loop_runs(folder, table, now, module):
    processes = module_processes(table, module)
    runs = [run for path in subfolders(folder) if (run := read_loop_run(path, processes, now))]
    return sorted(runs, key=lambda run: run["at"] or 0, reverse=True)


def agent_section(paths, table, now):
    worktree = Path(paths["agent_loop"])
    return {"available": worktree.is_dir(), "runs": loop_runs(worktree / "runs", table, now, "kokopelli.loop.run")}


def mind_section(paths, table, now):
    runs = loop_runs(paths["mind"], table, now, "kokopelli.loop.run_mind")
    for run in runs:
        folder = Path(paths["mind"]) / run["name"]
        rows = read_rows(folder / "feelings.jsonl")
        appraisals = [row for row in rows if row.get("kind") == "appraisal"]
        felt = [row["feeling"] for row in appraisals if row.get("feeling")]
        summary = read_json(folder / "mind_summary.json") or {}
        run.update({"feelings": len(rows), "appraisals": len(appraisals), "invalid_appraisals": len(appraisals) - len(felt), "last_feeling": felt[-1] if felt else None,
                    "points": summary.get("points"), "felt": summary.get("feelings")})
    return {"available": Path(paths["mind"]).is_dir(), "runs": runs}


def benchmark_folders(paths):
    return [*subfolders(Path(paths["evals"]) / "benchmarks" / "results"), *subfolders(paths["benchmarks_out"])]


def benchmarks_section(paths, table, now):
    evals = Path(paths["evals"])
    processes = module_processes(table, "experiments.benchmarks.run")
    runs = []
    for folder in benchmark_folders(paths):
        record = read_json(folder / "run_record.json") or {}
        rows = read_rows(folder / "results.jsonl")
        if not record and not rows:
            continue
        wrote = newest_write([folder / "results.jsonl", folder / "run_record.json"])
        moving = run_is_alive(folder, processes) and wrote is not None and now - wrote < STALL_SECONDS
        runs.append({"name": folder.name, "real": bool(record.get("real")), "exploratory": bool(record.get("exploratory")), "backend": record.get("backend"), "known": bool(record),
                     "instruments": record.get("instruments") or [], "arms": record.get("arms") or [], "rows": len(rows), "valid": sum(1 for row in rows if row.get("valid")), "at": wrote, "moving": moving})
    try:
        instruments = sorted(path.parent.name for path in (evals / "benchmarks").glob("*/items.jsonl"))
    except OSError:
        instruments = []
    prereg = None
    try:
        prereg = "draft" if PREREG_DRAFT in (evals / "benchmarks" / "PREREG.md").read_text(errors="ignore") else "written"
        if prereg == "written" and (evals / "benchmarks" / "prereg.lock.json").exists():
            prereg = "locked"
    except OSError:
        pass
    real = [run for run in runs if run["real"] and not run["exploratory"] and run["rows"]]
    return {"available": evals.is_dir(), "instruments": instruments, "prereg": prereg, "runs": sorted(runs, key=lambda run: run["at"] or 0, reverse=True), "real_results": len(real),
            "exploratory": sum(1 for run in runs if run["real"] and run["exploratory"] and run["rows"]), "rows": sum(run["rows"] for run in runs), "moving": any(run["moving"] for run in runs)}


def best_validation(out):
    """The lowest validation drive among runs that really replied. A run replying nothing scores what doing nothing scores."""
    best, broken = None, []
    for name, folder in watch.run_folders(out).items():
        for row in read_rows(folder / "validation.jsonl"):
            if "mean_drive" not in row:
                continue
            if row.get("invalid", 0) > 0.5:
                broken.append({"run": name, "iteration": row.get("iteration"), "drive": row["mean_drive"]})
            elif best is None or row["mean_drive"] < best["drive"]:
                best = {"run": name, "iteration": row.get("iteration"), "drive": row["mean_drive"]}
    return best, broken


def training_section(out, table, now):
    if not Path(out).is_dir():
        return {"available": False, "runs": []}
    running = watch.trainers("\n".join(" ".join(row["parts"]) for row in table if runs_module(row["parts"], "experiments.homeostatic.train")))
    best, broken = best_validation(out)
    baselines = watch.baselines(out)
    runs = []
    for name, folder in watch.run_folders(out).items():
        train = read_rows(folder / "train.jsonl")
        checks = [row["mean_drive"] for row in read_rows(folder / "validation.jsonl") if "mean_drive" in row]
        state = watch.state_of(folder, running)
        wrote = newest_write(folder.iterdir())
        runs.append({"name": name, "state": state, "done": train[-1].get("iteration", 0) if train else 0, "total": running.get(folder.resolve()),
                     "latest": checks[-1] if checks else None, "at": wrote, "moving": state == "training" and wrote is not None and now - wrote < STALL_SECONDS})
    base, idle = (baselines.get("base") or {}).get("mean_drive"), (baselines.get("idle") or {}).get("mean_drive")
    return {"available": True, "runs": runs[:6], "total_runs": len(runs), "best": best, "broken": broken, "base": base, "idle": idle,
            "beaten": beats_baselines(best, base, idle), "held_out": len(watch.held_out_results(out))}


def beats_baselines(best, base, idle):
    """Better than the untrained model and better than doing nothing. A model that learned to do nothing scores what idle scores, and hasn't learned this."""
    if not best or base is None or best["drive"] >= base:
        return False
    return idle is None or best["drive"] < idle - 1e-6


def blank_lines(paths):
    """How many settings on the PACE scripts haven't been filled in. None if the scripts aren't there to read."""
    scripts = Path(paths["agent_loop"]) / "scripts" / "pace"
    found = []
    for name in ("env.sh", "wmloop_run.sbatch"):
        try:
            found.append((scripts / name).read_text(errors="ignore").count(BLANK_MARK))
        except OSError:
            return None
    return sum(found)


def gate(name, state, evidence, required=True):
    return {"name": name, "state": state, "evidence": evidence, "required": required}


def uses_real(run, part):
    return run[part] not in (None, "mock") and run["done"] > 0


def used_gate(name, runs, part, available):
    """Whether any run has finished a tick with this part real."""
    if not available:
        return gate(name, "unknown", "The agent loop worktree isn't there to read.")
    used = [run for run in runs if uses_real(run, part)]
    if used:
        return gate(name, "pass", f"{used[0]['name']} ran {used[0]['done']} ticks on {used[0][part]}.")
    return gate(name, "fail", f"No run has finished a tick without the mock, out of {plural(len(runs), 'run')}.")


def goal_section(paths, gpu, tests, agent, mind, benchmarks, training):
    """Is the real 30-minute run possible yet? Each gate is read from files, and a gate that can't be read is unknown, not passed."""
    runs, available = agent["runs"], agent["available"]
    suite = next((suite for suite in tests["suites"] if suite["name"] == "agent loop"), None)
    loop_code = (Path(paths["agent_loop"]) / "runtime" / "loop.py").is_file()
    long_mock = [run for run in runs if run["state"] == "finished" and run["done"] >= TARGET_TICKS]
    rendered = [run for run in runs if run["wm"] not in (None, "mock") and (run["rendered_s"] or 0) >= FULL_TICK_SECONDS]
    finished_real = [run for run in runs if run["mode"] == "real" and run["state"] == "finished" and run["done"] >= TARGET_TICKS and (run["rendered_s"] or 0) >= FULL_TICK_SECONDS]
    blanks = blank_lines(paths)
    gates = [
        gate("Loop code", "pass" if loop_code else "unknown" if not available else "fail", "On the feat/wm-agent-loop worktree only, not merged." if loop_code else "kokopelli/loop/loop.py isn't there to read."),
        gate("Loop tests", "unknown" if suite is None or suite["ok"] is None else "pass" if suite["ok"] else "fail", suite["summary"] if suite else "No result for this suite."),
        gate(f"{TARGET_TICKS} ticks, even on mocks", "pass" if long_mock else "unknown" if not available else "fail", f"{long_mock[0]['name']} finished {long_mock[0]['done']} ticks ({long_mock[0]['mode']})." if long_mock else "No run has finished that many ticks."),
        used_gate("Real SimWorld in the loop", runs, "sim", available),
        used_gate("Real Cosmos in the loop", runs, "wm", available),
        used_gate("Real Qwen in the loop", runs, "agent", available),
        gate("Full-length ticks", "pass" if rendered else "unknown" if not available else "fail", f"{rendered[0]['name']} rendered {rendered[0]['rendered_s']} s a tick." if rendered else f"No real run has rendered {FULL_TICK_SECONDS}+ s of video a tick."),
        gate("A machine that can run it", "unknown" if blanks is None else "pass" if blanks == 0 else "fail", "The PACE scripts aren't there to read." if blanks is None else "The PACE scripts are filled in. That doesn't show a job has run." if blanks == 0 else f"The PACE scripts still have {blanks} {BLANK_MARK} settings. SimWorld has no Mac build."),
        gate("Finished for real", "pass" if finished_real else "unknown" if not available else "fail", f"{finished_real[0]['name']}." if finished_real else f"No run has finished {TARGET_TICKS} ticks with all three real."),
        # These don't stop the run, but it can't mean anything without them.
        gate("Feel-then-decide on real Qwen", "pass" if any(uses_real(run, "agent") for run in mind["runs"]) else "fail", f"{plural(len(mind['runs']), 'run')}, none on a real model yet." if not any(uses_real(run, "agent") for run in mind["runs"]) else "A run has used real Qwen.", required=False),
        gate("Real benchmark results", "unknown" if not benchmarks["available"] else "pass" if benchmarks["real_results"] else "fail", f"{benchmarks['real_results']} real, {benchmarks['exploratory']} exploratory base-model checks, pre-registration {benchmarks['prereg'] or 'unknown'}.", required=False),
        gate("Training beats the untrained model", "unknown" if not training["available"] or training["base"] is None else "pass" if training["beaten"] else "fail", training_evidence(training), required=False),
    ]
    required = [row for row in gates if row["required"]]
    blockers = [row["name"] for row in required if row["state"] == "fail" and row["name"] != "Finished for real"]
    unknown = [row["name"] for row in required if row["state"] == "unknown"]
    if finished_real:
        verdict, line = "done", "The real 30-minute run has finished."
    elif blockers:
        verdict, line = "blocked", "Real 30-minute run: not possible yet."
    elif unknown:
        verdict, line = "unknown", "Real 30-minute run: unknown."
    else:
        verdict, line = "possible", "Real 30-minute run: nothing known is blocking it."
    held_by = [job["name"] for job in gpu["outside"]] + [ticket["name"] for ticket in gpu["running"]]
    next_up = gpu["waiting"][0]["name"] if gpu["waiting"] else None
    notes = None
    try:
        notes = (Path(paths["agent_loop"]) / "runtime" / "THIRTY_MIN.md").read_text(errors="ignore")[:6000]
    except OSError:
        pass
    return {"verdict": verdict, "line": line, "blockers": blockers, "unknown": unknown, "gates": gates, "target_ticks": TARGET_TICKS,
            "next_up": next_up, "held_by": held_by, "notes": notes, "best_real_ticks": max((run["done"] for run in runs if run["mode"] == "real"), default=0)}


def training_evidence(training):
    if not training["available"]:
        return "out/homeostatic isn't there to read."
    if training["base"] is None:
        return "No untrained baseline measured."
    best = f"{training['best']['drive']:.1f}" if training["best"] else "none"
    idle = f", doing nothing {training['idle']:.1f}" if training["idle"] is not None else ""
    return f"Best trained {best}, untrained {training['base']:.1f}{idle}. Lower is healthier."


def safely(reader, empty, *args):
    """One unreadable section shouldn't take down the page. It says so instead."""
    try:
        return reader(*args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        return {**empty, "available": False, "error": f"{type(error).__name__}: {error}"}


def collect(paths=PIPELINE_PATHS, listing=None, out=HOMEOSTATIC_OUT, now=None):
    """Everything measured right now."""
    now = time.time() if now is None else now
    table = process_table(listing)
    gpu = safely(gpu_section, {"tickets": [], "stale": [], "outside": [], "running": [], "waiting": [], "jobs": [], "busy": False, "events": 0, "finished": 0, "failed": 0}, paths, table, now)
    tests = safely(tests_section, {"suites": []}, paths, now)
    agent = safely(agent_section, {"runs": []}, paths, table, now)
    mind = safely(mind_section, {"runs": []}, paths, table, now)
    benchmarks = safely(benchmarks_section, {"runs": [], "instruments": [], "prereg": None, "real_results": 0, "exploratory": 0, "rows": 0, "moving": False}, paths, table, now)
    training = safely(training_section, {"runs": [], "best": None, "broken": [], "base": None, "idle": None, "beaten": False, "held_out": 0}, out, table, now)
    goal = goal_section(paths, gpu, tests, agent, mind, benchmarks, training)
    return {"now": now, "goal": goal, "gpu": gpu, "tests": tests, "agent": agent, "mind": mind, "benchmarks": benchmarks, "training": training}


def signals(collected):
    """What the architecture chart moves on. A mock run moves only the parts it really used, so a mock world model never lights Cosmos."""
    agent_moving = [run for run in collected["agent"]["runs"] if run["state"] == "moving"]
    mind_moving = [run for run in collected["mind"]["runs"] if run["state"] == "moving"]
    moving = agent_moving + mind_moving
    gpu = collected["gpu"]
    evals_running = any("experiments.benchmarks.run" in ticket["command"] for ticket in gpu["running"])
    uses = lambda part: any(run[part] not in (None, "mock") for run in moving)
    flags = {"loop.running": bool(agent_moving), "loop.sim_real": uses("sim"), "loop.wm_real": uses("wm"), "loop.agent_real": uses("agent"),
             "loop.life_real": any(run["context"] not in (None, "mock") for run in moving), "mind.running": bool(mind_moving),
             "queue.running": bool(gpu["running"]), "queue.evals": evals_running, "evals.running": collected["benchmarks"]["moving"]}
    # Finished ticks only, summed over the runs that exist, so a new run adds and never looks like a drop.
    counts = {"loop.ticks": sum(run["done"] for run in collected["agent"]["runs"]) + sum(run["done"] for run in collected["mind"]["runs"]),
              "mind.feelings": sum(run.get("feelings", 0) for run in collected["mind"]["runs"]), "queue.events": gpu["events"], "evals.rows": collected["benchmarks"]["rows"]}
    return {"flags": flags, "counts": counts}


VIDEO_ROOTS = {"agent": lambda paths: Path(paths["agent_loop"]) / "runs", "mind": lambda paths: Path(paths["mind"])}


def video_path(kind, run, paths=PIPELINE_PATHS):
    """A run's final.mp4. The name must be one we found by listing the folder, so a request can't name any other path."""
    root = VIDEO_ROOTS[kind](paths)
    folder = {path.name: path for path in subfolders(root)}[run]
    video = (folder / "final.mp4").resolve()
    if video.parent != folder.resolve() or not video.is_file():
        raise KeyError(run)
    return video
