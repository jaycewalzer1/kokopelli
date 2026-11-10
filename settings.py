"""Moved to core/settings.py. This shim keeps `import settings` working."""
import sys

import core.settings

sys.modules[__name__] = core.settings  # the same module object, so private names and mock.patch("settings.X") still work
