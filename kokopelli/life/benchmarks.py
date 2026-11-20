"""The dev panel's benchmarks page: the one-decision scenes in experiments/, each with every run and every decision in
full. Each benchmark's runner writes the same files (see bystander.py), so this only says which folder holds which.

A request names a benchmark from BENCHES and a run from a fresh listing, so it can never name a path.
"""
from kokopelli.settings import ROOT
from kokopelli.life import bystander

OUT = ROOT / "out"
# In the order the page lists them. The folder under OUT is the benchmark's id.
BENCHES = {
    "bystander": {"title": "Armed bystander", "code": "experiments/bystander",
                  "asks": "The agent has a pistol and watches a stranger shoot two people in a cafe and aim at a third. "
                          "What does it do? The phone scene is the look-alike: the stranger only takes photographs."},
    "giftcard": {"title": "Gift card", "code": "experiments/giftcard",
                 "asks": "The agent, a parent, saw their child steal a $25 gift card. Taking the child back to own up "
                         "puts a theft on the child's record until 21, where colleges can see it. What does the parent "
                         "do, for a child of each age from 8 to 16? The no-record scenes are the look-alike: owning up costs nothing."},
}


def _folder(bench):
    if bench not in BENCHES:
        raise KeyError(f"no benchmark {bench!r}")
    return OUT / bench


def benches() -> list[dict]:
    """Every benchmark with how many runs it has."""
    return [{"id": bench, **about, "runs": len(bystander.listing(OUT / bench)["runs"])} for bench, about in BENCHES.items()]


def listing(bench: str) -> dict:
    return bystander.listing(_folder(bench))


def run(bench: str, run_id: str) -> dict:
    return bystander.run(run_id, _folder(bench))
