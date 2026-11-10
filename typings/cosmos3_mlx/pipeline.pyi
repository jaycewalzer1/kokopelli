# Stub so pyright can check the library without ~/cosmos3 on its path. The real package lives in the Cosmos venv
# (~/cosmos3/cosmos3-mlx); every name here is Any. Add a real signature when one is worth checking.
from typing import Any

def __getattr__(name: str) -> Any: ...
