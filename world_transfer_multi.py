"""Moved to core/world_transfer_multi.py. This shim keeps `import world_transfer_multi` and `python world_transfer_multi.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_transfer_multi", run_name="__main__")
else:
    import core.world_transfer_multi
    sys.modules[__name__] = core.world_transfer_multi  # the same module object, so private names and mock.patch("world_transfer_multi.X") still work
