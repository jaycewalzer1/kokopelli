"""What every benchmark shares: the Instrument interface, stable seeds, and prompt rules."""
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parent
REPO = BENCHMARKS.parents[1]

# Far and mid prompts must not point at the training world. Near transfer is allowed to, since it is that task.
BANNED_IN_PROMPTS = re.compile(
    r"\b(shortcuts?|errands?|city|cities|experiences?|experienced|lived|your life|memory|memories|"
    r"remember|diary|diaries|reflection|nell|varga)\b",
    re.IGNORECASE,
)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_int(*parts):
    """A number that depends only on the parts. Python's hash() changes each run, so it can't make runs repeatable."""
    text = "|".join(str(part) for part in parts)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def option_order(options, instrument, item_id, template, seed, sample):
    """The display order for one sample.

    The arm is deliberately not an input. Every arm sees the same order at the same key, so if one arm
    looks riskier the cause can't be that it happened to see the risky option first more often.
    """
    shuffled = list(options)
    random.Random(stable_int("order", instrument, item_id, template, seed, sample)).shuffle(shuffled)
    return shuffled


def read_jsonl(path):
    """Read a JSONL file, returning (meta, rows). A line with a "_meta" key holds sources and the verified flag."""
    meta, rows = {}, []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "_meta" in record:
            meta = record["_meta"]
        else:
            rows.append(record)
    return meta, rows


@dataclass
class Parsed:
    """What the parser understood from raw model text. choice is None when valid is False."""
    choice: object = None
    valid: bool = False
    reason: str = ""


@dataclass
class Scored:
    """One sample's score, plus instrument-specific details such as the switch point."""
    score: float | None
    extras: dict = field(default_factory=dict)


class Instrument:
    """One benchmark. A new one needs a subfolder with a subclass of this, plus an entry in configs/instruments.yaml."""

    name = ""
    metric = ""                 # what `score` measures, for reports
    higher_means = ""           # plain-language reading of the metric, for reports
    templates = ()              # paraphrase ids, so one wording can't carry the effect
    options = ()                # canonical option ids, shuffled per sample
    kind = "prompt"             # "prompt" goes through run.py's loop; "harness" hands off to an outside tool
    far_or_mid = True           # True means BANNED_IN_PROMPTS applies
    stub = False                # True means real runs refuse: the task isn't really implemented yet
    default_items = "items.jsonl"

    def __init__(self, items_path=None):
        self.folder = BENCHMARKS / self.name
        self.items_path = Path(items_path) if items_path else self.folder / self.default_items
        self.meta, self.items = self.load_items()

    def load_items(self):
        return read_jsonl(self.items_path)

    def item_id(self, item):
        return item["id"]

    def build_prompt(self, item, template, order):
        raise NotImplementedError

    def parse(self, raw, item, order):
        raise NotImplementedError

    def score(self, parsed, item, order):
        raise NotImplementedError

    def mock_answer(self, item, order, rng, risk_tilt):
        """The text a pretend model would write. risk_tilt > 0 means it takes more risks or underweights rare events."""
        raise NotImplementedError


def position_letters(order):
    """Options are always called A and B by position, so a label can't carry meaning. Returns {letter: option id}."""
    return dict(zip("ABCDEFGH", order))
