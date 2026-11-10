"""Moved to core/world_multicontrol_base.py. This shim keeps `import world_multicontrol_base` and `python world_multicontrol_base.py` working."""
import sys

if __name__ == "__main__":
    import runpy
    runpy.run_module("core.world_multicontrol_base", run_name="__main__")
else:
    import core.world_multicontrol_base
    sys.modules[__name__] = core.world_multicontrol_base  # the same module object, so private names and mock.patch("world_multicontrol_base.X") still work
