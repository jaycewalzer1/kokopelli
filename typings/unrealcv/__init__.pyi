# Stub so pyright can check the library without simworld/.venv (Python 3.10, where unrealcv is installed) on its path.
# Every name here is Any. Add a real signature when one is worth checking.
from typing import Any

def __getattr__(name: str) -> Any: ...
