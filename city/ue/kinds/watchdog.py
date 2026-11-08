#!/usr/bin/env python
"""Keep the 9003 editor healthy for the overnight kind authoring: every 10 min check the Metal shared-event leak
(lsmp IOSurfaceSharedEventReference count) and that 9003 answers; past 45k (or dead), take the editor lock,
restart it minimized, rebuild the city, re-claim RAM, release. Log: out/city_kinds/watchdog.log.

    ~/Desktop/kokopelli/simworld/.venv/bin/python -m city.ue.kinds.watchdog [--hours 13]
"""
import argparse
import fcntl
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "out" / "city_kinds" / ".editor.lock"
LOG = ROOT / "out" / "city_kinds" / "watchdog.log"
PY = str(ROOT / "simworld" / ".venv" / "bin" / "python")


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now():%m-%d %H:%M:%S} {msg}\n")


def editor_pid():
    out = subprocess.run(["lsof", "-nP", "-tiTCP:9003", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def leak(pid):
    out = subprocess.run(["lsmp", "-p", str(pid)], capture_output=True, text=True).stdout
    return out.count("IOSurfaceSharedEventReference")


def alive():
    try:
        with socket.create_connection(("127.0.0.1", 9003), timeout=5):
            return True
    except OSError:
        return False


def restart(old):
    if old:
        os.kill(old, 15)
        for _ in range(60):
            if editor_pid() is None:
                break
            time.sleep(2)
    subprocess.Popen(["scripts/relaunch.sh"], cwd=ROOT / "mac_server", env=dict(os.environ, CVPORT="9003", MINIMIZED="1"),
                     stdout=open(ROOT / "out" / "city_kinds" / "relaunch.log", "a"), stderr=subprocess.STDOUT)
    for _ in range(120):
        time.sleep(5)
        pid = editor_pid()
        if pid:
            break
    else:
        log("restart: editor did not come up")
        return
    time.sleep(40)
    subprocess.call(["python3", "ram_share.py", "claim", "--name", "city_kinds_9003", "--gb", "10", "--pid", str(pid)], cwd=ROOT)
    rc = subprocess.call([PY, "city/ue/build_city.py", "--port", "9003"], cwd=ROOT, stdout=subprocess.DEVNULL)
    log(f"restarted: pid {pid}, city build rc {rc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=13)
    ap.add_argument("--limit", type=int, default=45000)
    args = ap.parse_args()
    end = time.time() + args.hours * 3600
    log("watchdog start")
    while time.time() < end:
        pid = editor_pid()
        n = leak(pid) if pid else -1
        log(f"pid {pid} leak {n}")
        if pid is None or n > args.limit:
            with open(LOCK, "a+") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                lk.seek(0), lk.truncate(), lk.write(f"{os.getpid()} watchdog-restart {datetime.now():%H:%M:%S}\n"), lk.flush()
                try:
                    pid = editor_pid()
                    if pid is None or leak(pid) > args.limit:
                        log(f"restarting (pid {pid})")
                        restart(pid)
                finally:
                    lk.seek(0), lk.truncate(), lk.flush()
                    fcntl.flock(lk, fcntl.LOCK_UN)
        time.sleep(600)
    log("watchdog end")


if __name__ == "__main__":
    main()
