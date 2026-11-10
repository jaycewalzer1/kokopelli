"""Moved to core/world_model.py. This shim keeps `import world_model` working."""
import sys

import core.world_model

sys.modules[__name__] = core.world_model  # the same module object, so private names and mock.patch("world_model.X") still work
