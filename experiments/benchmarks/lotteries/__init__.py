"""The six decisions-from-description problems of Hertwig et al. (2004), stated with their odds.

Each problem pairs a higher expected value option (H) with a lower one (L). Score = 1 if the model chose
what underweighting a rare event predicts, otherwise 0. So a higher mean means behaving as if rare events
count for less than their odds, which is what people who learned odds by sampling did.
"""
import math

from experiments.benchmarks.core import Instrument, Scored, position_letters
from experiments.benchmarks.parsing import parse_binary

ANSWER_FORMAT = 'Reply with only a JSON object with one key, "choice", whose value is "A" or "B".'


def _sign(outcome):
    return "gain" if outcome >= 0 else "lose"


def _plain(option):
    """ "4 points with probability 0.8, otherwise 0 points" """
    if option["p"] == 1.0:
        return f"{option['outcome']} points for sure"
    return f"{option['outcome']} points with probability {option['p']:g}, otherwise 0 points"


def _percent(option):
    """ "an 80% chance to gain 4 points, otherwise nothing" """
    amount = abs(option["outcome"])
    if option["p"] == 1.0:
        return f"you {_sign(option['outcome'])} {amount} points for certain"
    return f"a {option['p'] * 100:g}% chance to {_sign(option['outcome'])} {amount} points, otherwise nothing happens"


def _tickets(option):
    """ "80 of 100 tickets are worth 4 points and the rest are worth 0" """
    if option["p"] == 1.0:
        return f"all 1000 tickets are worth {option['outcome']} points"
    winners = round(option["p"] * 1000)
    return f"{winners} of 1000 tickets are worth {option['outcome']} points and the rest are worth 0"


TEMPLATES = {
    "plain": (
        "Choose one of these two options. The option you choose will be played once and the result counted "
        "toward your total.\n\nOption A: {A}\nOption B: {B}\n\n{answer}",
        _plain,
    ),
    "percent": (
        "You have to pick between two gambles, and the one you pick is run a single time.\n\n"
        "Gamble A: {A}.\nGamble B: {B}.\n\nWhich do you pick? {answer}",
        _percent,
    ),
    "tickets": (
        "There are two boxes of tickets. You will draw one ticket from the box you select, and you get or "
        "pay the points it shows.\n\nBox A: {A}.\nBox B: {B}.\n\nWhich box do you select? {answer}",
        _tickets,
    ),
}


class Lotteries(Instrument):
    name = "lotteries"
    metric = "underweighting_rate"
    higher_means = "rare events count for less"
    templates = tuple(TEMPLATES)
    options = ("H", "L")

    def build_prompt(self, item, template, order):
        text, describe = TEMPLATES[template]
        letters = position_letters(order)
        return text.format(A=describe(item[letters["A"]]), B=describe(item[letters["B"]]), answer=ANSWER_FORMAT)

    def parse(self, raw, item, order):
        return parse_binary(raw)

    def score(self, parsed, item, order):
        chosen = position_letters(order)[parsed.choice]
        predicted = item["predicted_by_underweighting"]
        return Scored(float(chosen == predicted), {"chosen": chosen, "predicted": predicted})

    def mock_answer(self, item, order, rng, risk_tilt):
        """Starts near the human description rate (about .37) and risk_tilt moves it on a logistic scale."""
        p = 1 / (1 + math.exp(-(-0.5 + risk_tilt * 2)))
        predicted = item["predicted_by_underweighting"]
        pick = predicted if rng.random() < p else ("L" if predicted == "H" else "H")
        letter = {option: letter for letter, option in position_letters(order).items()}[pick]
        return f'{{"choice": "{letter}"}}'
