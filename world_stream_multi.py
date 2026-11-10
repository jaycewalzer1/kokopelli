"""Moved to core/world_stream_multi.py. This shim keeps `import world_stream_multi` and `python world_stream_multi.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_stream_multi", run_name="__main__")
else:
    import core.world_stream_multi
    sys.modules[__name__] = core.world_stream_multi  # the same module object, so private names and mock.patch("world_stream_multi.X") still work
