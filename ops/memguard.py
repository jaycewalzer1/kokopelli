"""Moved to kokopelli/ops/memguard.py. Kept so `python3 ops/memguard.py ...` and the Bash hook's fallback keep working."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("kokopelli.ops.memguard", run_name="__main__")
