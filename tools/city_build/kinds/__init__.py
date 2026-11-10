"""Building kinds for the varied city: one module per family, each exporting KINDS = {"name": build_fn}.

    build_fn(plot: Plot) -> Kit        (kit.py: draw in the plot's local frame, metres)

Every module in this package except kit/preview/registry helpers is imported by all_kinds(), so adding a kind is
adding a file. README.md (same folder) is the authoring guide: rules, the preview tool, the editor lock.
"""
import importlib
import pkgutil
import random
from dataclasses import dataclass, field

from .kit import Kit, plot_size  # noqa: F401  (re-exported for kind modules)

SKIP = {"kit", "preview", "locked", "watchdog"}


@dataclass
class Plot:
    w: float                     # m along the street frontage
    d: float                     # m away from the street
    h_max: float = 24.0          # height cap (m); kinds may go lower, never higher
    floors: int = 0              # suggested storeys (0 = kind decides)
    palette: list = field(default_factory=lambda: [(236, 226, 200), (150, 168, 128), (190, 156, 82)])
    seed: int = 1
    use: str = ""                # world.json program, e.g. "homes", "shops + homes", "studio"
    cell: str = ""

    @property
    def rng(self):
        return random.Random(self.seed)


def all_kinds():
    """name -> (module name, build fn) over every kind module in this package."""
    out = {}
    for m in pkgutil.iter_modules(__path__):
        if m.name in SKIP or m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{m.name}")
        for k, fn in getattr(mod, "KINDS", {}).items():
            if k in out:
                raise ValueError(f"kind {k} defined in both {out[k][0]} and {m.name}")
            out[k] = (m.name, fn)
    return out


def build(kind, plot):
    return all_kinds()[kind][1](plot)
