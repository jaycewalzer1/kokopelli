"""Jobs written out ahead of time and waiting for the Start button on the GPU queue page.

A staged job is a JSON file in out/staged holding everything `gpu.py run` needs. Nothing about it is in the GPU queue yet, so
it can't take a turn by itself. Start puts it in the queue: it launches `gpu.py run` in its own session, so restarting the
panel doesn't stop it, and from then on it's an ordinary waiting job with a priority. Only a name found by listing the
folder can be started, so a request can't name any other file.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from kokopelli.settings import GPU_QUEUE_SCRIPT, STAGED_JOBS

FIELDS = ("name", "priority", "max_hours", "cwd", "about", "outputs", "command")
LAUNCH_CHECK_SECONDS = 1.0


class StageError(ValueError):
    """A start the page refused, worded for it."""


def listing(folder=STAGED_JOBS):
    jobs = []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if all(field in job for field in FIELDS):
            jobs.append({**{field: job[field] for field in FIELDS}, "estimate": job.get("estimate"), "created_at": job.get("created_at"),
                         "self_queued": bool(job.get("self_queued")), "file": path.name})
    return jobs


def start(name, folder=STAGED_JOBS, script=GPU_QUEUE_SCRIPT, python=sys.executable):
    folder = Path(folder)
    job = next((job for job in listing(folder) if job["name"] == name), None)
    if job is None:
        raise StageError(f"Nothing called {name} is waiting to start.")
    if not Path(script).is_file():
        raise StageError(f"The queue's gpu.py isn't there: {script}")
    started = folder / "started"
    started.mkdir(exist_ok=True)
    record = started / f"{Path(job['file']).stem}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    # Moving the file first means a second click finds nothing to start, so the job can't be queued twice.
    try:
        (folder / job["file"]).rename(record)
    except FileNotFoundError:
        raise StageError(f"{name} has already been started.") from None
    # A self-queued job takes its own turns, giving way between them, so it's run as it is. Anything else gets one gpu.py ticket.
    command = job["command"] if job["self_queued"] else [
        python, str(script), "run", "--name", job["name"], "--priority", str(job["priority"]), "--max-hours", str(job["max_hours"]),
        "--cwd", job["cwd"], "--about", job["about"], *[part for output in job["outputs"] for part in ("--output", output)], "--", *job["command"]]
    log = started / f"{record.stem}.log"
    with log.open("w") as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, cwd=job["cwd"])
    time.sleep(LAUNCH_CHECK_SECONDS)
    if process.poll() is not None:
        record.rename(folder / job["file"])  # back on the shelf, so it can be fixed and started again
        raise StageError(f"gpu.py stopped straight away with code {process.returncode}: {log.read_text()[-400:].strip()}")
    record.write_text(json.dumps({**json.loads(record.read_text()), "started_at": time.time(), "gpu_pid": process.pid}, indent=1))
    return {"started": name, "pid": process.pid}
