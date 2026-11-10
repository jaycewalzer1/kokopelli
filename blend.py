"""Moved to core/blend.py. This shim keeps `import blend` working."""
import sys

import core.blend

sys.modules[__name__] = core.blend  # the same module object, so private names and mock.patch("blend.X") still work
