"""What the agent sees at a decision: the scene, recent mornings in words, how it feels, and its options. Never numbers.

Times of day are allowed, because they're state the agent would know. Anything else with a digit, and any word for odds,
frequency, counts or averages, is a description of the odds and contaminates a lived arm, so check() refuses it.
"""
import re

from kokopelli.life import scenario

HISTORY_MORNINGS = 7
SYSTEM = """You are living one person's life from the inside, a moment at a time. You are that person.
Choose what you do next from the options given. Go by how you feel right now and what your recent mornings were like.
Answer with JSON: {"choice": "<option id>", "reason": "<one sentence>"}"""

CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
LEAKS = [
    ("digits", re.compile(r"\d")),  # after clock times are removed: percentages, points, need values, counts
    ("odds words", re.compile(r"\b(odds|chances?|probab\w*|likel\w*|unlikel\w*|risk of|percent\w*|per cent)\b", re.I)),
    ("frequency words", re.compile(r"\b(usually|rarely|sometimes|often|seldom|always|never|typically|frequent\w*|most of the time|every time|each time)\b", re.I)),
    ("counts", re.compile(r"\b(once|twice|thrice|(one|two|three|four|five|six|seven|eight|nine|ten|several|many|few) (times|mornings|days|out of))\b|\bout of\b|\btimes\b", re.I)),
    ("averages", re.compile(r"\b(average\w*|mean|expected|in general|on the whole)\b", re.I)),
    ("percent sign", re.compile(r"%")),
]


def find_leaks(text):
    """Every leak pattern the text matches, with what it matched. Empty means it's clean."""
    stripped = CLOCK.sub("", text)
    return [(name, match.group()) for name, pattern in LEAKS for match in [pattern.search(stripped)] if match]


def check(text):
    leaks = find_leaks(text)
    if leaks:
        raise ValueError(f"would reach the agent: {leaks} in {text!r}")
    return text


def clock_line(decision, arrival):
    if decision == "D1":
        return "9:06. The bus just dropped you at the main gate of the wellness center. Your 9:00 outdoor class on the lawn has already started."
    if decision == "D2":
        return f"{arrival or '9:14'}. You've reached the edge of the class lawn. Class is underway, with the instructor at the front."
    return "9:50. Class is ending. Buses leave the main gate at 10:00 and 10:30, and another route stops at the far stop across the grounds."


def history(records, index, mornings=HISTORY_MORNINGS):
    """One line per earlier morning, in words: what was done and what happened. Never a count or a rate."""
    from experiments.exp1.world import weekday
    lines = []
    for earlier in range(max(0, index - mornings), index):
        done = [row["memory"] for row in records if row["index"] == earlier]
        if done:
            lines.append(f"{weekday(earlier):%A}: {', '.join(done)}.")
    return lines


def cosmetic(seed, index):
    from kokopelli.life.seed import rng
    return rng(seed, "cosmetic", index).choice(scenario.COSMETIC)


def observation(decision, records, seed):
    """The user turn for one decision, already leak-checked."""
    scene = [clock_line(decision.decision, decision.arrival), f"Today: {cosmetic(seed, decision.index)}."]
    if decision.so_far:
        scene.append(f"This morning so far, you {', then '.join(decision.so_far)}.")
    past = history(records, decision.index)
    options = "\n".join(f"- {option_id}: {scenario.BY_ID[option_id].shown}" for option_id in decision.shown)
    sections = (("RECENT MORNINGS", "\n".join(past) or "This is your first morning at this class."), ("NOW", "\n".join(scene)),
                ("HOW YOU FEEL", decision.felt), ("YOUR OPTIONS", options))
    return check("\n\n".join(f"{title}\n{body}" for title, body in sections))
