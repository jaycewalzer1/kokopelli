"""Moved to core/world_stream.py. This shim keeps `import world_stream` and `python world_stream.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_stream", run_name="__main__")
else:
    import core.world_stream
    sys.modules[__name__] = core.world_stream  # the same module object, so private names and mock.patch("world_stream.X") still work
