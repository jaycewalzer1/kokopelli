"""Test markers (registered in pyproject.toml). `make test-all` runs the tree twice: .venv with -m "not py310", simworld/.venv
with -m py310. This file is loaded by both, so it stays Python 3.10 compatible.

py310   the SimWorld tests (PY310_FILES): they import unrealcv, which only simworld/.venv has.
model   loads Qwen or Cosmos onto the GPU: skipped unless RUN_MODEL_TESTS is set (queue it through kokopelli/ops/gpu.py).
slow    takes hours: skipped unless RUN_LONG_TESTS is set.
unreal  needs a running Unreal server.
"""
import os
from fnmatch import fnmatch

import pytest

PY310_FILES = "test_simworld*.py"
OPT_IN = {"model": "RUN_MODEL_TESTS", "slow": "RUN_LONG_TESTS"}


def pytest_ignore_collect(collection_path, config):
    # A run for one interpreter doesn't import the other interpreter's files, whose tests -m would deselect anyway:
    # the SimWorld files skip themselves without unrealcv, and the rest don't import under Python 3.10.
    if collection_path.suffix != ".py" or not collection_path.name.startswith("test_"):
        return None
    py310 = fnmatch(collection_path.name, PY310_FILES)
    markexpr = config.getoption("markexpr").strip()
    if (markexpr == "py310" and not py310) or (markexpr == "not py310" and py310):
        return True
    return None


@pytest.hookimpl(tryfirst=True)  # before -m deselects by marker
def pytest_collection_modifyitems(config, items):
    for item in items:
        if fnmatch(item.path.name, PY310_FILES):
            item.add_marker(pytest.mark.py310)
        for name, variable in OPT_IN.items():
            marker = item.get_closest_marker(name)
            if marker and not os.environ.get(variable):
                reason = marker.kwargs.get("reason", f"marked {name}")
                item.add_marker(pytest.mark.skip(reason=f"{reason}; set {variable}=1"))
