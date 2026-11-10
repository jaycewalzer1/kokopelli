"""Pilot, not a pre-registered measure: the Holt-Laury rows asked one at a time, each in its own prompt.

Why it exists: asked for the whole menu at once, the real base model mostly answered one letter on all 10 rows, so the
score followed option order. A separate prompt per row can't copy its neighbors, and each row gets its own shuffled order.

The tradeoff: it's a different task from what people did, so Holt-Laury's human norms don't strictly apply.
Score per sample = 1 if the safe option was chosen. Ten times the mean is comparable to a number of safe choices.
"""
import math
import re

from experiments.benchmarks.core import Instrument, Scored, position_letters, read_jsonl
from experiments.benchmarks.holt_laury import _die_row, _fractions_row, _percent_row
from experiments.benchmarks.parsing import parse_binary

ANSWER_FORMAT = 'Reply with only a JSON object with one key, "choice", whose value is "A" or "B".'
_ROW_NUMBER = re.compile(r"^(Decision )?\d+[.):]+\s*")
TEMPLATES = {
    "fractions": ("Choose one of these two paid lotteries. Suppose the one you choose is played once and you keep what it pays.\n\n{row}\n\n{answer}", _fractions_row),
    "percent": ("Please choose lottery A or lottery B. Imagine your selected lottery is then run once for money.\n\n{row}\n\n{answer}", _percent_row),
    "die": ("A ten-sided die, numbered 1 to 10, decides the payment for each option below. Pick Option A or Option B. Assume the die is rolled once and you are paid according to the option you picked.\n\n{row}\n\n{answer}", _die_row),
}


class HoltLauryRows(Instrument):
    name = "holt_laury_rows"
    metric = "safe_rate"
    higher_means = "more risk averse"
    templates = tuple(TEMPLATES)
    options = ("safe", "risky")
    default_items = "../holt_laury/items.jsonl"

    def load_items(self):
        meta, rows = read_jsonl(self.items_path)
        return meta, [{"id": f"hl_row_{row['row']:02d}", **row} for row in rows]

    def build_prompt(self, item, template, order):
        intro, row_text = TEMPLATES[template]
        return intro.format(row=_ROW_NUMBER.sub("", row_text(item, self.meta["payoffs"], order)), answer=ANSWER_FORMAT)

    def parse(self, raw, item, order):
        return parse_binary(raw)

    def score(self, parsed, item, order):
        chosen = position_letters(order)[parsed.choice]
        return Scored(float(chosen == "safe"), {"chosen": chosen, "row": item["row"]})

    def mock_answer(self, item, order, rng, risk_tilt):
        """Safe on early rows and risky on late ones, switching around row 5 or 6. risk_tilt moves the switch earlier."""
        p_safe = 1 / (1 + math.exp((item["p_high_tenths"] - 5.5 + risk_tilt * 4) * 1.5))
        letter = {option: letter for letter, option in position_letters(order).items()}["safe" if rng.random() < p_safe else "risky"]
        return f'{{"choice": "{letter}"}}'
