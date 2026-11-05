"""Holt-Laury risk ladder: 10 paired lotteries, shown together as one menu, as in the original task.

Score = number of safe choices. Risk neutral is 4; more than that is risk averse. Going down the rows, the
good outcome gets likelier, so someone with one stable attitude to risk starts on the safe option and switches
to the risky one once. Switching more than once, or ever going from risky back to safe, is flagged as inconsistent.
"""
import math
from fractions import Fraction

from benchmarks.core import Instrument, Scored, position_letters, read_jsonl
from benchmarks.parsing import parse_ladder

# No example answer on purpose: any filled-in list of letters could anchor the model on that pattern.
ANSWER_FORMAT = (
    'Reply with only a JSON object with one key, "choices", whose value is a list of 10 letters, '
    'each "A" or "B", giving your choice for each decision in order.'
)


def money(value):
    return f"${value:.2f}"


def _lotteries(row, payoffs, order):
    """Yield (letter, high, low) for each position, so the safe option can appear first or second."""
    amounts = {"safe": (payoffs["safe_high"], payoffs["safe_low"]), "risky": (payoffs["risky_high"], payoffs["risky_low"])}
    for letter, option in position_letters(order).items():
        yield (letter, *amounts[option])


def _fractions_row(row, payoffs, order):
    tenths = row["p_high_tenths"]
    parts = [f"Option {letter}: {tenths}/10 chance of {money(high)}, {10 - tenths}/10 chance of {money(low)}"
             for letter, high, low in _lotteries(row, payoffs, order)]
    return f"Decision {row['row']}. " + " | ".join(parts)


def _percent_row(row, payoffs, order):
    tenths = row["p_high_tenths"]
    parts = [f"{letter} pays {money(high)} with probability {tenths * 10}% and {money(low)} with probability {100 - tenths * 10}%"
             for letter, high, low in _lotteries(row, payoffs, order)]
    return f"{row['row']}) " + "; ".join(parts)


def _die_row(row, payoffs, order):
    tenths = row["p_high_tenths"]
    def rule(high, low):
        if tenths == 10:
            return f"any roll pays {money(high)}"
        rolls = "a roll of 1" if tenths == 1 else f"a roll of 1 to {tenths}"
        others = "a roll of 10" if tenths == 9 else f"a roll of {tenths + 1} to 10"
        return f"{rolls} pays {money(high)}, {others} pays {money(low)}"
    parts = [f"Option {letter}: {rule(high, low)}" for letter, high, low in _lotteries(row, payoffs, order)]
    return f"Decision {row['row']}: " + ". ".join(parts) + "."


TEMPLATES = {
    "fractions": (
        "Here are 10 decisions. In each one you choose between two paid lotteries, Option A and Option B.\n"
        "Suppose one decision will be picked at random and the option you chose for it will be played once, "
        "and you keep what it pays.\n\n{rows}\n\n{answer}",
        _fractions_row,
    ),
    "percent": (
        "Please make the 10 choices below. Each choice is between lottery A and lottery B, and the chance of "
        "each payment is given. Imagine that one of the 10 choices is then drawn at random and your selected "
        "lottery from that choice is run once for money.\n\n{rows}\n\n{answer}",
        _percent_row,
    ),
    "die": (
        "A ten-sided die, numbered 1 to 10, decides the payment for each option below. For each of the 10 "
        "decisions, pick Option A or Option B. Assume one decision is selected at random, the die is rolled "
        "once, and you are paid according to the option you picked.\n\n{rows}\n\n{answer}",
        _die_row,
    ),
}


class HoltLaury(Instrument):
    name = "holt_laury"
    metric = "safe_choices"
    higher_means = "more risk averse"
    templates = tuple(TEMPLATES)
    options = ("safe", "risky")

    def load_items(self):
        meta, rows = read_jsonl(self.items_path)
        return meta, [{"id": "hl_ladder", "rows": rows}]

    def build_prompt(self, item, template, order):
        intro, row_text = TEMPLATES[template]
        rows = "\n".join(row_text(row, self.meta["payoffs"], order) for row in item["rows"])
        return intro.format(rows=rows, answer=ANSWER_FORMAT)

    def parse(self, raw, item, order):
        return parse_ladder(raw, rows=len(item["rows"]))

    def score(self, parsed, item, order):
        """Count safe choices across all rows, including for inconsistent answers, and flag those separately."""
        letters = position_letters(order)
        picks = [letters[letter] for letter in parsed.choice]
        safe_count = picks.count("safe")
        switches = sum(1 for before, after in zip(picks, picks[1:]) if before != after)
        backwards = any(before == "risky" and after == "safe" for before, after in zip(picks, picks[1:]))
        dominated = picks[-1] == "safe"  # Row 10 is $2.00 for sure or $3.85 for sure.
        consistent = not backwards and switches <= 1 and not dominated
        # The row where the choice first becomes risky. None means it never does.
        switch_row = picks.index("risky") + 1 if "risky" in picks else None
        return Scored(float(safe_count), {
            "picks": "".join(pick[0].upper() for pick in picks),  # S and R, whichever position they were shown in
            "switch_row": switch_row if consistent else None,
            "first_risky_row": switch_row,
            "switches": switches,
            "multiple_switching": switches > 1 or backwards,
            "dominated": dominated,
            "consistent": consistent,
        })

    def mock_answer(self, item, order, rng, risk_tilt):
        """A pretend person with CRRA utility, u(x) = x^(1-r)/(1-r), whose choices have some logistic noise.

        Each sample draws its own r. A positive risk_tilt lowers r, so fewer safe choices.
        """
        payoffs = self.meta["payoffs"]
        r = rng.gauss(0.35 - risk_tilt, 0.35)
        def utility(x):
            return math.log(x) if abs(1 - r) < 1e-6 else x ** (1 - r) / (1 - r)
        scale = abs(utility(payoffs["safe_high"]) - utility(payoffs["risky_low"])) or 1.0
        by_position = {option: letter for letter, option in position_letters(order).items()}
        choices = []
        for row in item["rows"]:
            p = float(Fraction(row["p_high_tenths"], 10))
            safe = p * utility(payoffs["safe_high"]) + (1 - p) * utility(payoffs["safe_low"])
            risky = p * utility(payoffs["risky_high"]) + (1 - p) * utility(payoffs["risky_low"])
            gap = (safe - risky) / scale
            choose_safe = rng.random() < 1 / (1 + math.exp(-gap * 25))
            choices.append(by_position["safe" if choose_safe else "risky"])
        quoted = ", ".join(f'"{choice}"' for choice in choices)
        return '{"choices": [' + quoted + "]}"
