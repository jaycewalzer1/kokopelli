"""Moved to kokopelli/ops/gpu.py. Kept so `python3 ops/gpu.py ...` keeps working."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("kokopelli.ops.gpu", run_name="__main__")
