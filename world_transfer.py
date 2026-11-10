"""Moved to core/world_transfer.py. This shim keeps `import world_transfer` and `python world_transfer.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_transfer", run_name="__main__")
else:
    import core.world_transfer
    sys.modules[__name__] = core.world_transfer  # the same module object, so private names and mock.patch("world_transfer.X") still work
