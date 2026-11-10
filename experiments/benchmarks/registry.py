"""Load configs: which instruments exist, and what each arm is. Adding either one shouldn't need a code change here."""
import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from experiments.benchmarks.core import BENCHMARKS, REPO

CONFIGS = BENCHMARKS / "configs"
ARM_DIRS = [CONFIGS / "arms", CONFIGS / "arms" / "fake", CONFIGS / "arms" / "controls"]


@dataclass
class Arm:
    name: str
    model: str
    adapter: str | None = None
    seed: int = 0
    notes: str = ""
    training_text: list = field(default_factory=list)
    mock: dict = field(default_factory=dict)
    api_model: str | None = None
    later: bool = False
    prompt_prefix: str = ""     # Positive controls only. run.py refuses it outside exploratory runs.
    weights: str | None = None  # A folder of full weights, such as fused/ from homeostatic.export, used instead of an adapter.

    def adapter_for(self, seed):
        """Adapter paths can hold {seed}, because each seed is its own trained adapter."""
        return self._path(self.adapter, seed)

    def weights_for(self, seed):
        return self._path(self.weights, seed)

    @property
    def is_trained(self):
        return bool(self.adapter or self.weights)

    def _path(self, value, seed):
        if not value:
            return None
        path = Path(value.format(seed=seed))
        return str(path if path.is_absolute() else REPO / path)


def load_arm(name, arm_dirs=None):
    for folder in [*(arm_dirs or []), *ARM_DIRS]:
        path = Path(folder) / f"{name}.yaml"
        if path.exists():
            return Arm(**yaml.safe_load(path.read_text()))
    raise FileNotFoundError(f"No arm config called {name} in {arm_dirs or ARM_DIRS}")


def instrument_entries():
    return yaml.safe_load((CONFIGS / "instruments.yaml").read_text())["instruments"]


def load_instrument(name, items_path=None):
    entries = instrument_entries()
    if name not in entries:
        raise KeyError(f"No instrument called {name} in configs/instruments.yaml. Known: {sorted(entries)}")
    module_name, class_name = entries[name]["class"].rsplit(":", 1)
    return getattr(importlib.import_module(module_name), class_name)(items_path=items_path)


def load_norms(name):
    """Published human results for an instrument, or None. Used by reports only, never by scoring."""
    entry = instrument_entries().get(name, {})
    path = BENCHMARKS / entry["norms"] if entry.get("norms") else None
    return yaml.safe_load(path.read_text()) if path and path.exists() else None


def load_contrasts(path=None):
    return yaml.safe_load(Path(path or CONFIGS / "contrasts.yaml").read_text())


def load_sampling(path=None):
    return yaml.safe_load(Path(path or CONFIGS / "sampling.yaml").read_text())
