"""A repeatable number from some parts, for seeds and for choosing a cue's wording.

The same three lines as experiments/benchmarks/core.py's stable_int, copied because the library can't import an
experiment (the import wall in pyproject.toml). tests/body/test_hash.py holds the two equal, so the seeds a sweep and a
video run draw stay the same whichever copy made them.
"""
import hashlib


def stable_int(*parts: object) -> int:
    """A number that depends only on the parts. Python's hash() changes each run, so it can't make runs repeatable."""
    text = "|".join(str(part) for part in parts)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
