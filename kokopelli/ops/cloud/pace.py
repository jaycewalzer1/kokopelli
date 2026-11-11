"""Run one queued job on PACE: copy the code up, submit it to Slurm, follow it, and copy its results back.

kokopelli/ops/gpu.py calls run_job() for a ticket whose `where` is "pace". Standard library only, like gpu.py.

PACE logs in with Duo, so nothing here can log in by itself. You open one SSH connection that stays up
(ControlMaster, see kokopelli/ops/cloud/README.md), and every command here reuses it with BatchMode, so a missing
connection fails at once instead of waiting on a Duo prompt nobody will answer.

MLX only runs on Apple chips, so a job only goes to PACE with its own `--pace-command`, which has to
work with CUDA there. gpu.py never sends the Mac command.
"""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

CONFIG = Path(os.environ.get("KOKOPELLI_PACE_CONFIG", Path(__file__).with_name("pace.json")))
REQUIRED = ("host", "remote_root", "setup", "sbatch")
# Never copied up: environments built for the Mac, model weights, outputs, and other sessions' worktrees.
EXCLUDE = (".venv", ".git", ".claude", "out", "models", "__pycache__", "*.mp4", "*.safetensors", "*.db")
DONE = {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL", "DEADLINE"}
# Exit codes for ends that aren't the job's own, matching what gpu.py uses on the Mac where there is one.
EXITS = {"TIMEOUT": 124, "CANCELLED": 130, "OUT_OF_MEMORY": 137, "NODE_FAIL": 75, "PREEMPTED": 75, "BOOT_FAIL": 75, "DEADLINE": 124}
TAIL_BYTES = 4000


def load_config(path=CONFIG):
    """The settings, or None. A value still starting with CHANGE_ME counts as missing."""
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return config


def missing(config):
    """What still has to be filled in before a job can go to PACE."""
    if config is None:
        return [f"{CONFIG.name} (copy kokopelli/ops/cloud/pace.example.json)"]
    return [key for key in REQUIRED if key not in config or "CHANGE_ME" in json.dumps(config[key])]


class Remote:
    """The real connection, over the SSH connection you already opened. Tests swap in a fake."""

    def __init__(self, host):
        self.host = host
        self.ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]

    def connected(self):
        return subprocess.run(["ssh", "-O", "check", self.host], capture_output=True, timeout=5).returncode == 0

    def shell(self, script):
        """Run a bash script on the login node. Returns (exit code, output)."""
        done = subprocess.run([*self.ssh, "bash", "-l", "-s"], input=script, capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout + done.stderr

    def copy_up(self, local, remote):
        excludes = [f"--exclude={pattern}" for pattern in EXCLUDE]
        done = subprocess.run(["rsync", "-az", *excludes, "-e", " ".join(self.ssh[:-1]), f"{local}/", f"{self.host}:{remote}/"],
                              capture_output=True, text=True, timeout=1800)
        return done.returncode, done.stdout + done.stderr

    def copy_down(self, remote, local):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["rsync", "-az", "-e", " ".join(self.ssh[:-1]), f"{self.host}:{remote}", str(Path(local).parent) + "/"],
                              capture_output=True, text=True, timeout=1800)
        return done.returncode, done.stdout + done.stderr


def connection_state(config=None, remote=None):
    """For the panel: whether a job sent to PACE now could start. Never prompts, never waits long."""
    config = load_config() if config is None else config
    gaps = missing(config)
    if gaps:
        return {"ready": False, "configured": False, "connected": False, "missing": gaps}
    assert config is not None  # missing() reports a None config
    try:
        connected = (remote or Remote(config["host"])).connected()
    except (OSError, subprocess.SubprocessError):
        connected = False
    return {"ready": connected, "configured": True, "connected": connected, "missing": [], "host": config["host"]}


def batch_script(config, name, folder, command, max_hours):
    """The Slurm job. Every #SBATCH line comes from pace.json, because accounts and partitions differ by PACE cluster."""
    limit = max_hours or config.get("default_hours", 4)
    minutes = max(1, round(limit * 60))
    lines = ["#!/bin/bash", f"#SBATCH -J {name}", f"#SBATCH -t {minutes // 60:02d}:{minutes % 60:02d}:00",
             f"#SBATCH -o {folder}/out/pace_logs/{name}-%j.log", *(f"#SBATCH {option}" for option in config["sbatch"]),
             "set -e", *config["setup"], f"cd {shlex.quote(folder)}", command]
    return "\n".join(lines) + "\n"


def remote_folder(config, cwd):
    return f"{config['remote_root'].rstrip('/')}/{Path(cwd).name}"


def slurm_state(remote, job):
    """(state, exit code) from sacct. A job sacct doesn't list yet has only just been submitted."""
    code, output = remote.shell(f"sacct -j {job} -n -X -P -o State,ExitCode\n")
    line = next((line for line in output.splitlines() if "|" in line), "")
    if code != 0 or not line:
        return "PENDING", None
    state, _, exit_code = line.partition("|")
    state = state.split()[0] if state else "PENDING"  # "CANCELLED by 123" is still CANCELLED
    if state not in DONE:
        return state, None
    if state == "COMPLETED":
        return state, 0
    if state == "FAILED":
        return state, int(exit_code.split(":")[0] or 1) or 1
    return state, EXITS.get(state, 1)


def run_job(ticket, log_path, on_update, config=None, remote=None, poll=None, sleep=time.sleep):
    """Submit, follow and collect one job. Returns the exit code gpu.py should report, as the Mac would.

    on_update(fields) records progress on the ticket, so the queue view can show where a PACE job is.
    """
    config = load_config() if config is None else config
    gaps = missing(config)
    log = Path(log_path)
    if gaps:
        log.write_text(f"[pace] PACE isn't set up. Missing: {', '.join(gaps)}. See kokopelli/ops/cloud/README.md.\n")
        return 2
    assert config is not None  # missing() reports a None config
    remote = remote or Remote(config["host"])
    poll = config.get("poll_seconds", 60) if poll is None else poll
    folder = remote_folder(config, ticket["cwd"] or os.getcwd())
    def say(text):
        with log.open("a") as file:
            file.write(f"[pace] {text}\n")

    log.write_text("")
    on_update({"state": "COPYING"})
    code, output = remote.copy_up(ticket["cwd"] or os.getcwd(), folder)
    if code:
        say(f"copying the code up failed:\n{output}")
        return 2
    script = batch_script(config, ticket["name"], folder, ticket["pace_command"], ticket.get("max_hours"))
    code, output = remote.shell(f"mkdir -p {shlex.quote(folder)}/out/pace_logs\nsbatch --parsable <<'KOKOPELLI_JOB'\n{script}KOKOPELLI_JOB\n")
    job = output.strip().splitlines()[-1].split(";")[0] if code == 0 and output.strip() else ""
    if not job.isdigit():
        say(f"sbatch refused the job:\n{output}")
        return 2
    say(f"submitted as Slurm job {job} in {folder}")
    on_update({"state": "PENDING", "job": job, "folder": folder})
    remote_log = f"{folder}/out/pace_logs/{ticket['name']}-{job}.log"
    state, exit_code = "PENDING", None
    while exit_code is None:
        sleep(poll)
        state, exit_code = slurm_state(remote, job)
        on_update({"state": state, "job": job, "folder": folder})
        _, tail = remote.shell(f"tail -c {TAIL_BYTES} {shlex.quote(remote_log)} 2>/dev/null\n")
        if tail:
            (log.parent / f"{log.stem}.pace_tail").write_text(tail)
    say(f"Slurm says {state}")
    for path in ticket.get("pull") or []:
        code, output = remote.copy_down(f"{folder}/{path}", Path(ticket["cwd"] or os.getcwd()) / path)
        say(f"copied back {path}" if code == 0 else f"couldn't copy back {path}:\n{output}")
    remote.copy_down(remote_log, log.parent / log.name.replace(".log", ".pace.log"))
    on_update({"state": state, "job": job, "folder": folder, "exit_code": exit_code})
    return exit_code


def cancel(job, config=None, remote=None):
    config = load_config() if config is None else config
    return (remote or Remote(config["host"])).shell(f"scancel {int(job)}\n")[0]  # pyright: ignore[reportOptionalSubscript]  # only called once PACE is set up
