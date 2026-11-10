"""Moved to core/world_filter.py. This shim keeps `import world_filter` and `python world_filter.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_filter", run_name="__main__")
else:
    import core.world_filter
    sys.modules[__name__] = core.world_filter  # the same module object, so private names and mock.patch("world_filter.X") still work
