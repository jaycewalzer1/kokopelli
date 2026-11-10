#!/usr/bin/env python
"""Run a command while holding the 9003 editor lock (the same one preview.py takes).

    ~/Desktop/kokopelli/simworld/.venv/bin/python -m tools.city_build.kinds.locked -- <command ...>

e.g. a whole-city rebuild + renders, so it never interleaves with another agent's preview:
    ... -m tools.city_build.kinds.locked -- simworld/.venv/bin/python tools/city_build/build_city.py --port 9003 --world data/city/world.json
"""
import fcntl
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOCK = Path(__file__).resolve().parents[3] / "out" / "city_kinds" / ".editor.lock"


def main():
    cmd = sys.argv[1:]
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if not cmd:
        sys.exit(__doc__)
    if any("9001" in a for a in cmd):
        sys.exit("port 9001 is the user's live server: never")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as lk:
        t = time.time()
        fcntl.flock(lk, fcntl.LOCK_EX)
        lk.seek(0), lk.truncate(), lk.write(f"{os.getpid()} locked:{Path(cmd[-1]).name} {datetime.now():%H:%M:%S}\n"), lk.flush()
        print(f"[lock] waited {time.time() - t:.0f}s", file=sys.stderr, flush=True)
        try:
            rc = subprocess.call(cmd)
        finally:
            lk.seek(0), lk.truncate(), lk.flush()
            fcntl.flock(lk, fcntl.LOCK_UN)
    sys.exit(rc)


if __name__ == "__main__":
    main()
