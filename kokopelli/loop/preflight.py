"""Fail in the first minute, not the fifth hour. Checks everything a run needs, and prints every problem at once.

--offline skips what needs running servers, so it can run before a job is submitted.
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from kokopelli.loop.config import WM_PRESETS
from kokopelli.loop.leak_guard import LeakError, check as leak_check

GB = 1024 ** 3
MB_PER_FRAME = 0.15  # A cautious guess until runtime.plan has real numbers: 832x480 clips, the joined video, and samples.
REPO = Path(__file__).resolve().parents[2]


def _tools():
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    return not missing, f"missing {missing}" if missing else "ffmpeg and ffprobe found"


def _packages(names):
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    return not missing, f"missing {missing}" if missing else f"{', '.join(names)} import"


def required_gb(ticks, preset):
    return ticks * sum(WM_PRESETS[preset]["chunk_frames"]) * MB_PER_FRAME / 1024


def _disk(out, ticks, preset):
    folder = Path(out)
    while not folder.exists():
        folder = folder.parent
    free = shutil.disk_usage(folder).free / GB
    needed = required_gb(ticks, preset)
    return free >= needed, f"{free:.0f} GB free at {folder}, a {ticks}-tick {preset} run may need {needed:.0f} GB"


def _writable(out):
    try:
        Path(out).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=out):
            pass
        return True, f"{out} is writable"
    except OSError as error:
        return False, f"{out}: {error}"


def _life(life_db, life_run, start_time, ticks):
    from kokopelli.loop.adapters.life_db import LifeContext, copy_database
    if not Path(life_db).is_file():
        return False, f"{life_db} doesn't exist"
    with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
        try:
            copy = copy_database(life_db, Path(folder) / "life.db")
            context = LifeContext(copy, life_run, start_time)
            start = context.start_time()
            end = (datetime.fromisoformat(start) + timedelta(seconds=30 * ticks)).isoformat()
            texts = []
            for moment in (start, end):
                state = context.context_at(moment)
                leak_check(state, moment, "preflight")
                if not state["nodes"]:
                    return False, f"life run {life_run} has no node active at {moment}"
                texts.append(state["nodes"][-1]["setting"])
        except (KeyError, ValueError, LeakError) as error:
            return False, f"life run {life_run}: {error}"
    deepest = state["nodes"][-1]["level"]
    mock = " WARNING: the text is placeholder [mock] text" if any(text.startswith("[mock]") for text in texts) else ""
    return True, f"run {life_run} covers {start} to {end}, deepest node {deepest}, leak guard clean{mock}"


def _model_server(url, model):
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/v1/models", timeout=20) as response:
            served = [item["id"] for item in json.load(response)["data"]]
    except (OSError, ValueError, KeyError) as error:
        return False, f"{url}: {error}"
    return model in served, f"{url} serves {served}" if model in served else f"{url} serves {served}, not {model}"


def _gpus(wanted):
    if not shutil.which("nvidia-smi"):
        return False, "nvidia-smi not found"
    listed = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.strip().splitlines()
    return len(listed) >= wanted, f"{len(listed)} GPUs, {wanted} wanted"


def _simworld(port):
    try:
        from kokopelli.loop.adapters.simworld_wire import probe_server
        return bool(probe_server("127.0.0.1", port)), f"SimWorld answers on port {port}"
    except Exception as error:  # Any failure here is the answer: it isn't ready.
        return False, f"SimWorld on port {port}: {error}"


def run_checks(args):
    """Return (name, ok, detail) for every check that applies."""
    real = args.backend == "real"
    checks = [("tools", *_tools()), ("packages", *_packages(["pydantic", "numpy", "PIL"])),
              ("repo", (REPO / "kokopelli" / "wm" / "blend.py").exists(), f"kokopelli/wm/blend.py {'found' if (REPO / 'kokopelli' / 'wm' / 'blend.py').exists() else 'missing'} under {REPO}"),
              ("output folder", *_writable(args.out)), ("disk", *_disk(args.out, args.ticks, args.wm_preset))]
    if real:
        checks.append(("real packages", *_packages(["unrealcv", "requests"])))
        checks.append(("life tree", *_life(args.life_db, args.life_run, args.start_time, args.ticks)))
    if args.mind:
        checks.append(("mind", *_packages(["mind"])))
    if real and not args.offline:
        checks.append(("GPUs", *_gpus(args.gpus)))
        checks.append(("Cosmos server", *_model_server(args.wm_url, args.cosmos_model)))
        checks.append(("Qwen server", *_model_server(args.agent_url, args.qwen_model)))
        checks.append(("SimWorld server", *_simworld(args.sim_port)))
    return checks


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["mock", "real"], default="real")
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--wm-preset", choices=WM_PRESETS, default="gpu_full")
    parser.add_argument("--out", required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--mind", action="store_true")
    parser.add_argument("--life-db")
    parser.add_argument("--life-run", type=int, default=2)
    parser.add_argument("--start-time")
    parser.add_argument("--wm-url")
    parser.add_argument("--agent-url")
    parser.add_argument("--sim-port", type=int, default=9000)
    parser.add_argument("--gpus", type=int, default=3)
    parser.add_argument("--cosmos-model", default="nvidia/Cosmos3-Nano")
    parser.add_argument("--qwen-model", default="Qwen/Qwen3-VL-8B-Instruct")
    return parser


def main(argv=None):
    checks = run_checks(make_parser().parse_args(argv))
    for name, ok, detail in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name:18}{detail}")
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{'Ready.' if not failed else 'Not ready: ' + ', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
