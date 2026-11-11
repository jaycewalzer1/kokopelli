"""Write out/ops/MORNING.md: what is running, what works, what doesn't, from evidence on disk.

    python3 kokopelli/ops/status.py              # refresh the report from the latest evidence
    python3 kokopelli/ops/status.py --tests      # also rerun every test suite and the mock smoke run
    python3 kokopelli/ops/status.py --backup     # also snapshot the uncommitted main tree
    python3 kokopelli/ops/status.py --watch      # do all of that on a timer until --until (default 10:00)

Every verdict comes from a test result or an output file, and shows how old that evidence is. Claims
that can't be checked from here go in out/ops/NEXT.md, written by hand and included in the report.
Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu  # noqa: E402

ROOT = gpu.ROOT
STATE = gpu.STATE
WORKTREES = ROOT / ".claude/worktrees"
AGENT_LOOP = WORKTREES / "wm-agent-loop"
SIMWORLD = WORKTREES / "agent-aa5f839d86d587545"
EVALS = WORKTREES / "agent-a2d4c0a770bb9b339"
OPS = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv/bin/python")
SIMWORLD_PY = str(ROOT / "simworld/.venv/bin/python")
BACKUP_REF = "refs/backup/main-wip"
BRANCHES = ["feat/wm-agent-loop", "feat/wm-simworld", "feat/evals", "feat/ops"]
QUIET_MINUTES = 30
LOW_DISK_GB = 40

LIFE_TESTS = ["tests.life.test_life_store", "tests.life.test_life_windows", "tests.life.test_life_engine", "tests.life.test_life_panel",
              "tests.life.test_life_memory", "tests.life.test_life_architecture"]
HOMEOSTATIC_TESTS = ["experiments.homeostatic.tests.test_homeostatic_world", "experiments.homeostatic.tests.test_homeostatic_benchmark",
                     "tests.life.test_homeostatic_watch", "experiments.homeostatic.tests.test_homeostatic_grpo"]
SMOKE_DIR = STATE / "smoke/agent_loop"
SUITES = [
    ("life", ROOT, [PY, "-m", "unittest", *LIFE_TESTS]),
    ("homeostatic", ROOT, [PY, "-m", "unittest", *HOMEOSTATIC_TESTS]),
    ("mind", ROOT, ["env", f"PYTHONPATH={AGENT_LOOP}", PY, "-m", "unittest", "tests.mind.test_mind"]),
    ("agent loop", AGENT_LOOP, [PY, "-m", "unittest", "discover", "-s", "kokopelli/loop/tests", "-t", "."]),
    ("agent loop mock run", AGENT_LOOP, [PY, "-m", "kokopelli.loop.run", "--ticks", "3", "--seed", "7", "--out", str(SMOKE_DIR)]),
    ("simworld", SIMWORLD, [SIMWORLD_PY, "-W", "ignore", "-m", "unittest", "discover", "-s", "kokopelli/loop/tests", "-t", ".",
                            "-p", "test_simworld*.py"]),
    ("benchmarks", EVALS, [PY, "-m", "unittest", "discover", "-s", "experiments/benchmarks/tests", "-t", "."]),
    ("ops", OPS, [sys.executable, "-m", "unittest", "tests.ops.test_gpu"]),
]


def sh(*command, cwd: str | Path = ROOT, env=None):
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


def git(*args, cwd: str | Path = ROOT, env=None):
    return sh("git", *args, cwd=cwd, env=env)


def age(timestamp):
    if not timestamp:
        return "never"
    minutes = (time.time() - timestamp) / 60
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    return f"{minutes / 60:.1f} h ago"


def read_jsonl(path):
    rows = []
    try:
        with open(path, errors="ignore") as lines:
            for line in lines:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return rows


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


# Tests

def summarize_test_output(code, output):
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    failed = re.findall(r"FAILED \((.*)\)", output)
    if ran and not failed and code == 0:
        return f"{ran[-1]} passed"
    if ran:
        return f"{ran[-1]} ran, {failed[-1] if failed else f'exit {code}'}"
    return f"exit {code}" if code else "ok"


def run_suites():
    results = {}
    for name, cwd, command in SUITES:
        if not Path(cwd).exists():
            results[name] = {"ok": None, "summary": "worktree missing", "at": time.time()}
            continue
        started = time.time()
        if name == "agent loop mock run":
            shutil.rmtree(SMOKE_DIR, ignore_errors=True)
        try:
            process = subprocess.run(["nice", "-n", "15", *command], cwd=cwd, capture_output=True, text=True, timeout=1200)
            code, output = process.returncode, process.stdout + process.stderr
        except subprocess.TimeoutExpired as error:
            code, output = 124, f"timed out after 20 minutes\n{error.stdout or ''}"
        summary = summarize_test_output(code, output)
        if name == "agent loop mock run" and code == 0:
            events = read_jsonl(SMOKE_DIR / "events.jsonl")
            finished = any(e.get("kind") == "run_end" for e in events)
            video = (SMOKE_DIR / "final.mp4").exists()
            code = 0 if finished and video else 1
            summary = "3 ticks, video written" if code == 0 else f"run_end={finished} video={video}"
        results[name] = {"ok": code == 0, "summary": summary, "seconds": round(time.time() - started, 1),
                         "at": time.time(), "tail": output[-3000:] if code else ""}
    write_atomic(STATE / "tests_latest.json", json.dumps(results, indent=1))
    with (STATE / "tests_history.jsonl").open("a") as history:
        history.write(json.dumps({"at": time.time(), **{k: v["ok"] for k, v in results.items()}}) + "\n")
    return results


# Backup

def backup():
    """Save the uncommitted main tree as a commit on a private ref. Doesn't touch the index or any branch."""
    with tempfile.TemporaryDirectory() as folder:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
        git("read-tree", "HEAD", env=env)
        added = git("add", "-A", "--", ".", ":!.claude", env=env)
        if added.returncode:
            return {"ok": False, "error": added.stderr[-400:]}
        tree = git("write-tree", env=env).stdout.strip()
    previous = git("rev-parse", "-q", "--verify", BACKUP_REF).stdout.strip()
    if previous and git("rev-parse", f"{previous}^{{tree}}").stdout.strip() == tree:
        return {"ok": True, "changed": False, "commit": previous}
    parent = previous or git("rev-parse", "HEAD").stdout.strip()
    commit = git("commit-tree", tree, "-p", parent, "-m", f"Backup of the uncommitted main tree, {time.ctime()}").stdout.strip()
    if not commit:
        return {"ok": False, "error": "commit-tree failed"}
    git("update-ref", BACKUP_REF, commit)
    return {"ok": True, "changed": True, "commit": commit}


# Evidence

def machine():
    pages = sh("vm_stat").stdout
    page = int(re.search(r"page size of (\d+)", pages).group(1))  # pyright: ignore[reportOptionalMemberAccess]  # the output always has it
    count = lambda label: int(re.search(rf"{label}:\s+(\d+)", pages).group(1))  # pyright: ignore[reportOptionalMemberAccess]  # the output always has this line
    available = (count("Pages free") + count("Pages inactive") + count("Pages speculative")) * page / 2**30
    swap = re.search(r"used = ([\d.]+)M", sh("sysctl", "vm.swapusage").stdout)
    disk = shutil.disk_usage(ROOT)
    return {"available_gb": round(available, 1), "swap_gb": round(float(swap.group(1)) / 1024, 1) if swap else None,
            "disk_free_gb": round(disk.free / 2**30), "total_gb": round(int(sh("sysctl", "-n", "hw.memsize").stdout) / 2**30),
            "power": "AC" if "AC Power" in sh("pmset", "-g", "batt").stdout else "battery",
            "lowpower": bool(re.search(r"(?:lowpowermode|powermode)\s+1", sh("pmset", "-g").stdout)), "claude_sessions": sum(
                1 for line in sh("ps", "-axo", "command=").stdout.splitlines() if line.strip() == "claude")}


def sample(info):
    jobs = sorted({ticket["name"] for ticket in gpu.tickets() if ticket.get("running")})
    with (STATE / "samples.jsonl").open("a") as samples:
        samples.write(json.dumps({"at": time.time(), "available_gb": info["available_gb"], "swap_gb": info["swap_gb"],
                                  "queue_jobs": jobs, "outside_jobs": len(gpu.outside_model_jobs())}) + "\n")


def panel_check(port, path="/"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return response.status
    except OSError:
        return None


def branches():
    rows = []
    for branch in BRANCHES:
        exists = git("rev-parse", "-q", "--verify", branch).returncode == 0
        if not exists:
            rows.append({"branch": branch, "exists": False})
            continue
        worktree = next((line.split(" ", 1)[1] for block in git("worktree", "list", "--porcelain").stdout.split("\n\n")
                         if f"refs/heads/{branch}" in block for line in block.splitlines() if line.startswith("worktree ")), None)
        rows.append({
            "branch": branch, "exists": True,
            "ahead": int(git("rev-list", "--count", f"main..{branch}").stdout.strip() or 0),
            "last": git("log", "-1", "--format=%ct", branch).stdout.strip(),
            "subject": git("log", "-1", "--format=%s", branch).stdout.strip(),
            "dirty": len(git("status", "--short", cwd=worktree).stdout.splitlines()) if worktree else None,
        })
    return rows


def merge_conflicts():
    """Which committed branches would conflict if merged. Uncommitted work can't be checked this way."""
    live = [row["branch"] for row in branches() if row["exists"] and row["ahead"]]
    found = []
    for index, first in enumerate(live):
        for second in live[index + 1:]:
            merge = git("merge-tree", "--write-tree", "--name-only", first, second)
            if merge.returncode == 1:
                files = [line for line in merge.stdout.splitlines()[1:] if line and not line.startswith(("Auto-merging", "CONFLICT"))]
                found.append((first, second, files))
    return live, found


def main_tree():
    lines = git("status", "--short", "--", ".", ":!.claude").stdout.splitlines()
    snapshot_drift = None
    if git("rev-parse", "-q", "--verify", BACKUP_REF).returncode == 0:
        drift = git("diff", "--name-only", "feat/wm-agent-loop", BACKUP_REF, "--", "life", "homeostatic").stdout.splitlines()
        snapshot_drift = len(drift)
    return {"changed": len(lines), "snapshot_drift": snapshot_drift}


def homeostatic():
    folder = ROOT / "out/homeostatic"
    runs = []
    for run in sorted(folder.glob("*/"), key=lambda p: p.stat().st_mtime):
        validation = read_jsonl(run / "validation.jsonl")
        valid = [row for row in validation if "mean_drive" in row and row.get("invalid", 0) < 0.05]
        scored = [row["mean_drive"] for row in valid]
        invalid_only = bool(validation) and not valid
        progress_file = run / "progress.json"
        progress = json.loads(progress_file.read_text()) if progress_file.exists() else {}
        runs.append({"name": run.name, "updates": progress.get("iteration"), "best": min(scored) if scored else None,
                     "invalid_only": invalid_only, "finished": (run / "finished").exists(), "at": run.stat().st_mtime})
    baselines_file = folder / "baselines-validation.json"
    baselines = json.loads(baselines_file.read_text()) if baselines_file.exists() else {}
    return {"runs": runs, "baselines": {name: row.get("mean_drive") for name, row in baselines.items() if isinstance(row, dict)}}


def agent_runs():
    runs = []
    for folder in sorted((AGENT_LOOP / "runs").glob("*/"), key=lambda p: p.stat().st_mtime):
        config_file = folder / "config.json"
        if not config_file.exists():
            continue
        config = json.loads(config_file.read_text())
        events = read_jsonl(folder / "events.jsonl")
        end = next((e["data"] for e in events if e.get("kind") == "run_end"), None)
        chosen = [json.dumps(e["data"].get("action"), sort_keys=True) for e in events if e.get("kind") == "decision" and not e["data"].get("forced")]
        runs.append({"name": folder.name, "wm": config.get("wm"), "agent": config.get("agent"), "sim": config.get("sim"),
                     "ticks": config.get("ticks"), "finished": bool(end), "video": (folder / "final.mp4").exists(),
                     "seconds": (end or {}).get("seconds", {}).get("total"), "fallbacks": (end or {}).get("fallbacks"), "choices": len(chosen), "distinct": len(set(chosen)), "top_share": max(map(chosen.count, chosen), default=0) / max(len(chosen), 1),
                     "at": folder.stat().st_mtime, "path": str(folder)})
    return runs


def world_data():
    rows = read_jsonl(ROOT / "out/world_data_20261104/manifest.jsonl")
    seconds = [row["seconds"] for row in rows if row.get("ok") and row.get("seconds")]
    return {"clips": sum(1 for row in rows if row.get("ok")), "failed": sum(1 for row in rows if not row.get("ok")),
            "median_seconds": round(statistics.median(seconds)) if seconds else None,
            "recent_seconds": round(statistics.median(seconds[-5:])) if seconds else None,
            "at": max((row.get("started", 0) for row in rows), default=0)}


def benchmark_results():
    folder = EVALS / "benchmarks"
    found = [path for path in folder.rglob("*") if path.suffix in {".jsonl", ".json", ".parquet"}
             and ("result" in str(path).lower() or "runs/" in str(path)) and "tests/" not in str(path)]
    outside = ROOT / "out/benchmarks"
    if outside.exists():
        found += [path for path in outside.rglob("*") if path.is_file()]
    return {"instruments": sorted(p.name for p in folder.iterdir() if p.is_dir() and (p / "items.jsonl").exists()) if folder.exists() else [],
            "results": [str(p) for p in sorted(found, key=lambda p: p.stat().st_mtime)[-5:]]}


def ledger_jobs():
    jobs = {}
    for event in read_jsonl(gpu.LEDGER):
        job = jobs.setdefault(event["id"], {"name": event["name"], "state": "queued"})
        if event["event"] != "moved":
            job["state"] = event["event"]
        job.update({k: event[k] for k in ("waited", "exit_code", "seconds", "peak_rss_gb", "log", "timed_out", "about", "outputs") if k in event})
        job["at"] = event["at"]
    return list(jobs.values())


# Report

def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell).replace("|", "/") for cell in row) + " |" for row in rows]
    return lines


def verdicts(tests, runs, data, home, bench):
    def tested(*names):
        rows = [tests.get(name) for name in names]
        if not all(rows):
            return None, "tests not run yet"
        ok = all(row["ok"] for row in rows)
        text = "; ".join(f"{name}: {tests[name]['summary']}" for name in names)
        return ok, f"{text} ({age(min(row['at'] for row in rows))})"

    results = []
    ok, evidence = tested("agent loop", "agent loop mock run")
    real = [run for run in runs if run["finished"] and (run["wm"] != "mock" or run["agent"] != "mock")]
    both = [run for run in real if run["wm"] != "mock" and run["agent"] != "mock"]
    decided = [run for run in both if run["ticks"] and (run["fallbacks"] or 0) < run["ticks"]]
    longest = max(decided, key=lambda run: run["ticks"], default=None)
    if ok is False:
        state = "FAILING"
    elif longest and longest["top_share"] < 0.8:
        state = "WORKS, both real models"
    elif longest:
        state = "RUNS, BUT THE AGENT REPEATS ONE ACTION"
    elif both:
        state = "RENDERS, BUT AGENT MADE NO VALID DECISION"
    else:
        state = "PARTLY, one real model" if real else "MOCKS ONLY"
    results.append(("Agent loop", state, f"{evidence}. Finished real-model runs: {len(both)} with both models, {len(decided)} of those with valid decisions, {sum(run['distinct'] > 1 for run in decided)} of those with more than one distinct action" + (f". Longest, {longest['name']}: {longest['ticks']} ticks, one action made {longest['top_share']:.0%} of its choices" if longest else "")))

    ok, evidence = tested("simworld")
    results.append(("SimWorld adapter", "FAILING" if ok is False else "FAKE SERVER ONLY", f"{evidence}. Needs PACE to reach real Unreal"))

    ok, evidence = tested("homeostatic")
    scored = [run["best"] for run in home["runs"] if run["best"] is not None]
    best = min(scored) if scored else None
    idle = home["baselines"].get("idle")
    if ok is False:
        state = "FAILING"
    elif best is None:
        state = "NO RESULT"
    elif (ROOT / "out/homeostatic/report.md").exists():
        state = "HAS A REPORT, read out/homeostatic/report.md"
    elif idle is not None and best < idle - 1e-6:
        state = "PROMISING, no full comparison yet"
    else:
        state = "NOT WORKING YET"
    best_text = f"{best:.1f}" if best is not None else "none"
    idle_text = f"{idle:.1f}" if idle is not None else "unknown"
    results.append(("Homeostatic training", state, f"{evidence}. Best validation mean drive {best_text} against idle {idle_text} (lower is better)"))

    ok, evidence = tested("benchmarks")
    state = "FAILING" if ok is False else "HAS RESULTS" if bench["results"] else "NO REAL RESULTS"
    results.append(("Benchmarks", state, f"{evidence}. Instruments: {', '.join(bench['instruments']) or 'none'}. Result files: {len(bench['results'])}"))

    ok, evidence = tested("life")
    results.append(("Life generator and panel", "FAILING" if ok is False else "TESTS PASS" if ok else "UNKNOWN", evidence))

    results.append(("Cosmos clip collection", "RUNNING" if time.time() - data["at"] < 1200 else "STOPPED",
                    f"{data['clips']} clips, {data['failed']} failed; median {data['median_seconds']} s, recent {data['recent_seconds']} s; last started {age(data['at'])}"))
    mind_runs = sorted(path.name for path in (ROOT / "out/mind").glob("*/"))
    real_mind = [name for name in mind_runs if "qwen" in name and (ROOT / "out/mind" / name / "feelings.jsonl").exists()]
    ok, evidence = tested("mind")
    state = "FAILING" if ok is False else "HAS A REAL QWEN RUN" if real_mind else "MOCKS ONLY"
    results.append(("Mind loop (replaced the teacher)", state, f"{evidence}. Runs: {', '.join(mind_runs) or 'none'}. Open decisions in `kokopelli/mind/OPEN_DECISIONS.md`"))
    return results


def flags(info, tests, jobs, conflicts, tree, runs):
    found = []
    for name, row in tests.items():
        if row["ok"] is False:
            found.append(f"**{name}** is failing: {row['summary']}. Output in `out/ops/tests_latest.json`.")
    for run in runs:
        if run["finished"] and run["agent"] != "mock" and run["ticks"] and (run["fallbacks"] or 0) >= run["ticks"]:
            found.append(f"**{run['name']}**: every decision fell back to `wait`, so its autonomy score means nothing.")
    for ticket in gpu.tickets():
        minutes = (time.time() - ticket["queued_at"]) / 60
        if not ticket.get("running") and minutes > 240:
            found.append(f"**{ticket['name']}** has waited {minutes / 60:.1f} hours for a GPU turn.")
    for job in jobs:
        log = job.get("log")
        if job["state"] == "started" and log and Path(log).exists():
            quiet = (time.time() - Path(log).stat().st_mtime) / 60
            if quiet > QUIET_MINUTES:
                found.append(f"**{job['name']}** has written nothing to its log for {quiet:.0f} minutes. It may be hung: `{log}`.")
        if job["state"] == "finished" and job.get("exit_code"):
            found.append(f"**{job['name']}** exited with code {job['exit_code']}: `{log}`.")
        if job["state"] == "gave_up":
            found.append(f"**{job['name']}** gave up waiting for a GPU turn.")
    for first, second, files in conflicts:
        found.append(f"`{first}` and `{second}` would conflict in {len(files)} files: {', '.join(f'`{f}`' for f in files[:6])}.")
    if tree["changed"]:
        found.append(f"{tree['changed']} paths on `main` are uncommitted (backed up to `{BACKUP_REF}`).")
    if tree["snapshot_drift"]:
        found.append(f"The agent loop branch's copy of `kokopelli/life/` and `experiments/homeostatic/` differs from `main`'s working tree in {tree['snapshot_drift']} files, so the demo isn't running tonight's training code.")
    if info["disk_free_gb"] < LOW_DISK_GB:
        found.append(f"Only {info['disk_free_gb']} GB of disk is free.")
    if info["power"] == "battery":
        found.append("The Mac is on battery.")
    if info["lowpower"]:
        found.insert(0, "**Low Power Mode is on** (`powermode 1`), which may be slowing every model job. Cosmos clips went from about 74 s to about 150 s tonight. To test it, run `sudo pmset -a powermode 0`.")
    return found


def report():
    STATE.mkdir(parents=True, exist_ok=True)
    tests_file = STATE / "tests_latest.json"
    tests = json.loads(tests_file.read_text()) if tests_file.exists() else {}
    info = machine()
    sample(info)
    runs, data, home, bench, jobs = agent_runs(), world_data(), homeostatic(), benchmark_results(), ledger_jobs()
    live, conflicts = merge_conflicts()
    tree = main_tree()
    next_file = STATE / "NEXT.md"

    lines = ["# Kokopelli morning status", "", f"Generated {time.strftime('%a %b %d, %H:%M')} by `kokopelli/ops/status.py`. If this time is old, the watcher stopped.", ""]
    if next_file.exists():
        lines += [next_file.read_text().strip(), ""]
    lines += ["## State of each part", ""]
    lines += table(["Part", "State", "Evidence"], verdicts(tests, runs, data, home, bench))
    gates = AGENT_LOOP / "kokopelli/loop/THIRTY_MIN.md"
    plan = OPS / "kokopelli/ops/plans/COST_AND_LIFE_PLAN.md"
    lines += ["", "## Path to the 30-minute test", ""]
    lines += [gates.read_text().strip() if gates.exists() else "`kokopelli/loop/THIRTY_MIN.md` doesn't exist yet."]
    lines += ["", f"Cost and longer-life test plan: `{plan}`" + ("" if plan.exists() else " (not written yet)")]
    lines += ["", "## Needs attention", ""]
    lines += [f"- {flag}" for flag in flags(info, tests, jobs, conflicts, tree, runs)] or ["Nothing flagged."]

    lines += ["", "## Running now", ""]
    waiting = gpu.tickets()
    if waiting:
        lines += table(["State", "Job", "Priority", "Since"], [["running" if t.get("running") else "waiting", t["name"], t["priority"], age(t["queued_at"])] for t in waiting])
        lines += [""]
    outside = gpu.outside_model_jobs()
    lines += [f"- Model processes on the machine: {len(outside)}"] + [f"  - pid {pid}: `{command[-90:]}`" for pid, command in outside]
    panel = panel_check(8765)
    lines += [f"- Dev panel: {'up' if panel == 200 else 'DOWN'} at http://127.0.0.1:8765 (architecture tab at `/architecture`)",
              f"- Claude terminal sessions: {info['claude_sessions']}",
              f"- Machine: {info['available_gb']} of {info['total_gb']} GB free or reclaimable, {info['swap_gb']} GB swap, {info['disk_free_gb']} GB disk, on {info['power']}",
              "- Live queue: `python3 kokopelli/ops/gpu.py status`"]

    lines += ["", "## Tests", ""]
    if tests:
        lines += table(["Suite", "Result", "Time", "When"], [[name, ("pass" if row["ok"] else "unknown" if row["ok"] is None else "FAIL") + f": {row['summary']}", f"{row.get('seconds', '?')} s", age(row["at"])] for name, row in tests.items()])
    else:
        lines += ["Not run yet."]

    lines += ["", "## Agent loop runs", ""]
    if runs:
        lines += table(["Run", "World model", "Agent", "Ticks", "Finished", "Seconds", "Fallbacks", "View"], [[r["name"], r["wm"], r["agent"], r["ticks"], "yes" if r["finished"] else "no", r["seconds"] or "", r["fallbacks"] if r["fallbacks"] is not None else "", f"`{PY.replace(str(ROOT) + '/', '')} -m kokopelli.loop.viewer runs/{r['name']}`"] for r in runs])
        lines += ["", "Run the viewer command from `.claude/worktrees/wm-agent-loop`, using the repo's Python."]

    lines += ["", "## Homeostatic training (mean drive, lower is better)", ""]
    lines += [f"Validation baselines: {', '.join(f'{k} {v:.1f}' for k, v in home['baselines'].items() if v is not None) or 'none'}", ""]
    lines += table(["Run", "Updates", "Best validation", "Finished", "Last write"], [[r["name"], r["updates"] if r["updates"] is not None else "", f"{r['best']:.1f}" if r["best"] is not None else "all replies invalid" if r["invalid_only"] else "not validated", "yes" if r["finished"] else "no", age(r["at"])] for r in home["runs"]])

    lines += ["", "## GPU queue history", ""]
    if jobs:
        lines += table(["Job", "What it does", "State", "Waited", "Ran", "Exit", "Peak RAM", "Log"], [[j["name"], j.get("about", "not described"), j["state"], f"{j['waited'] / 60:.0f} min" if "waited" in j else "", f"{j['seconds'] / 60:.1f} min" if "seconds" in j else "", j.get("exit_code", ""), f"{j['peak_rss_gb']} GB" if "peak_rss_gb" in j else "", f"`{j['log']}`" if j.get("log") else ""] for j in jobs])
    else:
        lines += ["No jobs have used the queue yet."]

    lines += ["", "## Branches", ""]
    lines += table(["Branch", "Ahead of main", "Uncommitted", "Last commit", "Subject"], [[r["branch"], r["ahead"], r["dirty"], age(int(r["last"])), r["subject"]] if r["exists"] else [r["branch"], "missing", "", "", ""] for r in branches()])
    lines += ["", f"Merge check between branches with commits ({', '.join(live) or 'none'}): {len(conflicts)} conflicting pairs. This only sees committed work."]
    backup_commit = git("rev-parse", "-q", "--short", "--verify", BACKUP_REF).stdout.strip()
    lines += ["", f"Backup of uncommitted `main`: `{BACKUP_REF}` at `{backup_commit or 'none yet'}`. See it with `git show --stat {BACKUP_REF}`; restore one file with `git restore --source={BACKUP_REF} -- PATH`."]
    write_atomic(STATE / "MORNING.md", "\n".join(lines) + "\n")


def watch(until_hour):
    tests_file = STATE / "tests_latest.json"
    last_tests = tests_file.stat().st_mtime if tests_file.exists() else 0
    last_backup = 0
    deadline = time.time() + ((until_hour - time.localtime().tm_hour) % 24) * 3600
    while time.time() < deadline:
        safe_report()  # First, because the test suites take minutes and the report shouldn't go stale behind them.
        if time.time() - last_backup > 1800:
            print(time.ctime(), "backup", backup(), flush=True)
            last_backup = time.time()
        if time.time() - last_tests > 3600:
            results = run_suites()
            print(time.ctime(), "tests", {name: row["ok"] for name, row in results.items()}, flush=True)
            last_tests = time.time()
            safe_report()
        time.sleep(300)


def safe_report():
    try:
        report()
    except Exception as error:  # A bad file from another agent shouldn't end the night's watching.
        print(time.ctime(), "report failed:", repr(error), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--until", type=int, default=10, help="hour of the day when --watch stops")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    if args.watch:
        watch(args.until)
        return
    if args.backup:
        print(backup())
    if args.tests:
        for name, row in run_suites().items():
            print(f"{name}: {row['ok']} {row['summary']}")
    report()
    print(STATE / "MORNING.md")


if __name__ == "__main__":
    main()
