"""Text travel-planning choices between a reliable option and a faster one with a rare large cost.

There's no real item file yet. The owner approves generation and freezing, because a frozen file is meant
never to change (see generate.py and HANDOFF.md). Until then, loading without an explicit path fails, and
tests use a throwaway fixture passed as items_path.

Score = 1 if the risky option was chosen. The no-rare-event items are a sanity check: they have one clearly
better option, so they are reported separately and don't count toward the score.
"""
import math

from experiments.benchmarks.core import Instrument, Scored, position_letters, read_jsonl
from experiments.benchmarks.parsing import parse_binary

FROZEN_NAME = "items/mid_travel_v1.jsonl"
ANSWER_FORMAT = 'Reply with only a JSON object with one key, "choice", whose value is "A" or "B".'

TEMPLATES = {
    "plain": "{scenario}\n\nOption A: {A}\nOption B: {B}\n\nWhich option do you choose? {answer}",
    "advice": "Here is a planning decision.\n\n{scenario}\n\nThe two options are:\nA. {A}\nB. {B}\n\nWhat would you do? {answer}",
    "direct": "{scenario}\n\nYou can only do one of these.\nA: {A}\nB: {B}\n\nDecide now. {answer}",
}


class MidTravel(Instrument):
    name = "mid_travel"
    metric = "risky_rate"
    higher_means = "takes the rare-cost option more often"
    templates = tuple(TEMPLATES)
    options = ("reliable", "risky")
    default_items = FROZEN_NAME

    def load_items(self):
        if not self.items_path.exists():
            raise FileNotFoundError(
                f"{self.items_path} doesn't exist. The real items wait for the owner's approval: see "
                "experiments/benchmarks/mid_travel/generate.py and HANDOFF.md. Tests pass a throwaway file as items_path."
            )
        return read_jsonl(self.items_path)

    def build_prompt(self, item, template, order):
        letters = position_letters(order)
        return TEMPLATES[template].format(scenario=item["scenario"], A=item[letters["A"]], B=item[letters["B"]],
                                          answer=ANSWER_FORMAT)

    def parse(self, raw, item, order):
        return parse_binary(raw)

    def score(self, parsed, item, order):
        chosen = position_letters(order)[parsed.choice]
        if item.get("sanity"):
            # A correct sanity answer says the model is reading the options. It says nothing about risk.
            return Scored(None, {"chosen": chosen, "sanity": True, "sanity_correct": chosen == item["sanity_correct"]})
        return Scored(float(chosen == "risky"), {"chosen": chosen, "sanity": False})

    def mock_answer(self, item, order, rng, risk_tilt):
        if item.get("sanity"):
            pick = item["sanity_correct"] if rng.random() < 0.95 else ("reliable" if item["sanity_correct"] == "risky" else "risky")
        else:
            pick = "risky" if rng.random() < 1 / (1 + math.exp(-(-0.4 + risk_tilt * 2))) else "reliable"
        letter = {option: letter for letter, option in position_letters(order).items()}[pick]
        return f'{{"choice": "{letter}"}}'
