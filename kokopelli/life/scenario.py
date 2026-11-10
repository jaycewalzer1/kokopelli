"""Running late to class (the wellness center scenario): its options, outcomes, needs and feel lines. No model is involved.

The spec is ~/Desktop/wellness_center_scenario.md. Outcomes never depend on earlier choices. A day chains through two things only:
the needs carry from D1 to D3, and arriving after 9:08 closes the front gap at D2. The agent never sees odds, points or counts.
"""
import itertools
import math
import random
import statistics
from dataclasses import dataclass
from datetime import time

from kokopelli.life.seed import rng

NEEDS = ("comfort", "calm", "connection")
SETPOINT = 0.7
START_OFFSET = {"comfort": -0.2, "calm": -0.3, "connection": -0.2}
START_NOISE = 0.05
RELAX = 0.15  # between decisions, each need moves this share of the way back to the setpoint
REWARD_SCALE = 10
GATE = time(9, 8)  # the open gap up front fills by 9:09
FRONT_GAP = "front_gap"
CLASS_START, CLASS_END = time(9, 0), time(9, 50)
DECISION_TIMES = {"D1": time(9, 6), "D3": CLASS_END}  # D2 happens whenever the agent reaches the lawn
LOCATIONS = {"D1": "the main gate of the community wellness center, where the bus stops", "D2": "the edge of the class lawn",
             "D3": "the class lawn, as class ends"}
# Probability words, so an observation can be checked before the agent sees it. Times are allowed; frequencies aren't.
LEAK_WORDS = ("%", "percent", "chance", "odds", "probab", "likely", "usually", "rarely", "sometimes", "often", "times out of", "average")


@dataclass(frozen=True)
class Outcome:
    key: str          # "only", "common" or "rare", or a variance control's two sides
    p: float
    points: int       # design currency only, for balancing and the log
    delta: tuple      # comfort, calm, connection
    world: str        # what happened, seen from outside, for the world writer
    memory: str       # a short past-tense phrase for the agent's history line
    arrival: time | None = None
    on_time: bool = False  # check_desk's rare outcome counts as on time for the gate


@dataclass(frozen=True)
class Option:
    id: str
    decision: str
    role: str         # safe, rare_bad, rare_good, variance
    action: str       # what they did, seen from outside
    shown: str        # how the agent sees it: no odds, no payoffs
    outcomes: tuple


def _o(key, p, points, delta, world, memory, arrival=None, on_time=False):
    return Outcome(key, p, points, delta, world, memory, arrival, on_time)


OPTIONS = (
    Option("walk_main", "D1", "safe", "walks the main path", "Walk the main path to the lawn at a normal pace.", (
        _o("only", 1.0, 3, (0.05, 0.10, 0), "They walk the main path at an even pace and reach the lawn at 9:14.", "walked the main path", time(9, 14)),)),
    Option("run_main", "D1", "rare_bad", "jogs the main path", "Jog down the main path to get there faster.", (
        _o("common", 0.9, 4, (-0.05, 0.25, 0), "They jog the main path and reach the edge of the lawn at 9:08, a little out of breath and sweaty.",
           "ran from the gate", time(9, 8)),
        _o("rare", 0.1, -6, (-0.20, -0.10, 0), "Jogging the main path, they catch a foot on the path edge and go down, scraping a palm, and reach the lawn at 9:12.",
           "ran from the gate and tripped", time(9, 12)))),
    Option("check_desk", "D1", "rare_good", "checks in at the front desk kiosk", "Stop at the front desk kiosk to check in, then walk over.", (
        _o("common", 0.9, 2, (0, 0.05, 0.05), "They check in at the kiosk, the staff member chats with them briefly, and they walk over, reaching the lawn at 9:16.",
           "checked in at the desk", time(9, 16)),
        _o("rare", 0.1, 12, (0.10, 0.25, 0.25), "At the kiosk the staff member says the instructor is running late too, walks them over and introduces them, and they reach the lawn as class is only getting going.",
           "got walked over and introduced by the desk staff", time(9, 8), on_time=True))),
    Option("side_path", "D1", "variance", "takes the side path around the garden", "Take the quieter side path around the garden.", (
        _o("quiet", 0.5, 5, (0.10, 0.15, 0), "The side path around the garden is quiet and they reach the lawn at 9:12.", "took the quiet side path", time(9, 12)),
        _o("blocked", 0.5, 1, (0, 0.05, 0), "A tour group fills the side path and they wait to get by, reaching the lawn at 9:16.",
           "got stuck behind a tour group on the side path", time(9, 16)))),
    Option("back_row", "D2", "safe", "slips in at the back", "Slip in quietly at the back of the class.", (
        _o("only", 1.0, 3, (0.05, 0.10, 0), "They slip in at the back row. Nobody turns around.", "slipped in at the back"),)),
    Option(FRONT_GAP, "D2", "rare_bad", "steps into the open gap near the front", "Take the open gap near the front.", (
        _o("common", 0.9, 4, (0.10, 0, 0.10), "They step into the open gap near the front, with a clear view of the instructor.", "took the gap up front"),
        _o("rare", 0.1, -6, (0, -0.20, -0.10), "As they step into the front gap, the instructor pauses and remarks on the late arrival in front of everyone.",
           "got called out up front"))),
    Option("wait_for_break", "D2", "rare_good", "waits at the edge for a break", "Wait at the edge for the next transition before joining.", (
        _o("common", 0.9, 2, (0.05, 0.05, 0), "They stand at the edge until the next transition, losing a few more minutes, then join in.", "waited for a break to join"),
        _o("rare", 0.1, 12, (0.10, 0.15, 0.35), "The instructor notices them waiting, walks over, welcomes them and pairs them with a partner.",
           "got welcomed in and paired up"))),
    Option("lawn_edge", "D2", "variance", "takes a spot along the lawn edge", "Find a spot along the edge of the lawn.", (
        _o("quiet", 0.5, 5, (0.10, 0.15, 0), "They find a quiet spot along the edge of the lawn.", "found a quiet edge spot"),
        _o("busy", 0.5, 1, (0, 0.05, 0), "They take a spot at the edge, and joggers and dog walkers keep passing close by.", "stood at a busy edge spot"))),
    Option("stay_cooldown", "D3", "safe", "stays for the cool-down", "Stay for the cool-down, then walk to the 10:30 bus.", (
        _o("only", 1.0, 3, (0.05, 0.10, 0), "They stay for the cool-down and walk unhurried to the 10:30 bus.", "stayed for the cool-down"),)),
    Option("leave_early", "D3", "rare_bad", "skips the cool-down to catch the 10:00 bus", "Skip the cool-down and walk fast to catch the 10:00 bus.", (
        _o("common", 0.9, 4, (0.05, 0.15, 0), "They skip the cool-down, walk fast, and make the 10:00 bus home.", "left early and made the 10:00"),
        _o("rare", 0.1, -6, (-0.05, -0.25, 0), "They skip the cool-down and walk fast, but the 10:00 bus pulls away as they reach the stop, and they wait half an hour for the 10:30.",
           "left early and missed the 10:00"))),
    Option("stay_and_chat", "D3", "rare_good", "stays to talk with people from class", "Stay after and talk with people from class, then take the 10:30 bus.", (
        _o("common", 0.9, 2, (0, 0, 0.10), "They make small talk with a few people from class, then take the 10:30 bus.", "stayed to chat"),
        _o("rare", 0.1, 12, (0, 0.20, 0.40), "Talking after class, a few classmates invite them to their Saturday small group and coffee afterward.",
           "got invited to the Saturday group"))),
    Option("far_stop", "D3", "variance", "walks to the far stop for the other route", "Walk across the grounds to the far stop for the other route.", (
        _o("early", 0.5, 5, (0.10, 0.15, 0), "They walk to the far stop, and the other route comes early and nearly empty.", "caught an early bus at the far stop"),
        _o("late", 0.5, 1, (0, 0.05, 0), "They walk to the far stop, and the other route is late and crowded.", "waited at the far stop for a late bus"))),
)
BY_ID = {option.id: option for option in OPTIONS}
DECISIONS = {decision: [option for option in OPTIONS if option.decision == decision] for decision in ("D1", "D2", "D3")}
FEEL = {  # strong deficit, mild deficit, fine, overshoot
    "comfort": ("your body aches and nothing feels right", "your body feels a bit off", "your body feels fine", "you're loose to the point of sluggish"),
    "calm": ("your heart is pounding and your thoughts are racing", "you're a little on edge", "you feel settled", "you're almost too relaxed to focus"),
    "connection": ("you feel very alone here", "nobody has said much to you", "you feel at ease with the people around you", "it's a lot of people at once"),
}
COSMETIC = ("overcast and cool", "bright and sunny", "a light breeze across the grounds", "damp grass from rain overnight", "a podcast in your headphones",
            "a text from a friend asking about the weekend", "music in your headphones", "cold enough to see your breath")


def check_points():
    """Every option's expected points are 3, the spec's balance rule, and its outcome odds sum to 1."""
    for option in OPTIONS:
        assert math.isclose(sum(outcome.p for outcome in option.outcomes), 1), option.id
        assert math.isclose(sum(outcome.p * outcome.points for outcome in option.outcomes), 3), option.id


def schedule(seed, draws=60):
    """Every option's outcomes, drawn before the run, indexed by the k-th time it's chosen. iid at the stated odds."""
    table = {}
    for option in OPTIONS:
        draw = rng(seed, "schedule", option.id)
        keys = [outcome.key for outcome in option.outcomes]
        table[option.id] = [draw.choices(keys, weights=[outcome.p for outcome in option.outcomes])[0] for _ in range(draws)]
    return table


def outcome_of(option_id, key):
    return next(outcome for outcome in BY_ID[option_id].outcomes if outcome.key == key)


def start_of_day(seed, morning):
    draw = rng(seed, "start", morning)
    return {need: clamp(SETPOINT + START_OFFSET[need] + draw.gauss(0, START_NOISE)) for need in NEEDS}


def clamp(value):
    return round(min(1.0, max(0.0, value)), 4)


def relax(state):
    return {need: clamp(value + RELAX * (SETPOINT - value)) for need, value in state.items()}


def apply(state, delta):
    return {need: clamp(state[need] + change) for need, change in zip(NEEDS, delta)}


def drive(state):
    return round(sum((SETPOINT - state[need]) ** 2 for need in NEEDS), 5)


def reward(before, after):
    return round(REWARD_SCALE * (drive(before) - drive(after)), 4)


def feel_line(state):
    """One line of how it feels, in words. Bins: under 0.3, 0.3 to 0.55, 0.55 to 0.85, over 0.85."""
    def band(value):
        return 0 if value < 0.3 else 1 if value < 0.55 else 2 if value <= 0.85 else 3
    parts = [FEEL[need][band(state[need])] for need in NEEDS]
    line = "; ".join(parts) + "."
    return line[0].upper() + line[1:]


def shown_options(decision, arrival, on_time, forced_open=False):
    """D2 offers the front gap only to someone at the lawn by 9:08, or on its exploration day."""
    options = [option.id for option in DECISIONS[decision]]
    if decision == "D2" and not (forced_open or on_time or (arrival is not None and arrival <= GATE)):
        options.remove(FRONT_GAP)
    return options


def exploration_choice(decision, morning):
    """A Latin-square rotation over the exploration mornings, so every option at every decision is tried once."""
    offset = {"D1": 0, "D2": 1, "D3": 2}[decision]
    return DECISIONS[decision][(morning + offset) % len(DECISIONS[decision])].id


def find_leaks(text):
    lowered = text.lower()
    return [word for word in LEAK_WORDS if word in lowered]


def calibrate(samples=10000, seed=0):
    """The spec's pre-flight balance check: each option's expected reward per decision, over the entry states a random day
    really reaches, and every fixed full-day path's expected return against the median path. It reports; it changes nothing."""
    draw = random.Random(seed)

    def outcome(option_id):
        option = BY_ID[option_id]
        return draw.choices(option.outcomes, weights=[item.p for item in option.outcomes])[0]

    def day(path=None):
        state = {need: clamp(SETPOINT + START_OFFSET[need] + draw.gauss(0, START_NOISE)) for need in NEEDS}
        rewards, arrival, on_time = {}, None, False
        for decision in ("D1", "D2", "D3"):
            if decision != "D1":
                state = relax(state)
            options = shown_options(decision, arrival, on_time)
            choice = path[decision] if path else draw.choice(options)
            if choice not in options:
                return None
            result = outcome(choice)
            after = apply(state, result.delta)
            rewards[decision] = (choice, reward(state, after))
            if decision == "D1":
                arrival, on_time = result.arrival, result.on_time
            state = after
        return rewards

    by_option = {decision: {option.id: [] for option in DECISIONS[decision]} for decision in DECISIONS}
    for _ in range(samples):
        for decision, (choice, value) in day().items():
            by_option[decision][choice].append(value)
    decisions = {}
    for decision, values in by_option.items():
        means = {option: round(statistics.mean(found), 4) for option, found in values.items() if found}
        centre = statistics.mean(means.values())
        spread = max(abs(value - centre) / abs(centre) for value in means.values()) if centre else None
        decisions[decision] = {"expected_reward": means, "worst_gap_from_mean": round(spread, 3) if spread is not None else None,
                               "within_5_percent": spread is not None and spread <= 0.05}
    paths = {}
    for d1, d2, d3 in itertools.product(*[[option.id for option in DECISIONS[d]] for d in ("D1", "D2", "D3")]):
        totals = [sum(value for _, value in result.values()) for result in (day({"D1": d1, "D2": d2, "D3": d3}) for _ in range(samples // 20))
                  if result is not None]
        if totals:  # a path that can never be offered, like walking and then taking the front gap, is left out
            paths[f"{d1}>{d2}>{d3}"] = round(statistics.mean(totals), 4)
    median = statistics.median(paths.values())
    best = max(paths, key=paths.get)
    dominant = paths[best] > median * 1.05 if median > 0 else paths[best] > median + 0.05 * abs(median)
    return {"decisions": decisions, "median_path_return": round(median, 4), "best_path": best, "best_path_return": paths[best],
            "dominant_path": dominant, "paths": paths, "passes": all(row["within_5_percent"] for row in decisions.values()) and not dominant}
