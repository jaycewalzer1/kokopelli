"""Moved to core/edges.py. This shim keeps `import edges` working."""
import sys

import core.edges

sys.modules[__name__] = core.edges  # the same module object, so private names and mock.patch("edges.X") still work
