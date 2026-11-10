"""Moved to core/ram_share.py. This shim keeps `import ram_share` and `python ram_share.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.ram_share", run_name="__main__")
else:
    import core.ram_share
    sys.modules[__name__] = core.ram_share  # the same module object, so private names and mock.patch("ram_share.X") still work
