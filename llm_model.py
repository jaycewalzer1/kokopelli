"""Moved to core/llm_model.py. This shim keeps `import llm_model` working."""
import sys

import core.llm_model

sys.modules[__name__] = core.llm_model  # the same module object, so private names and mock.patch("llm_model.X") still work
