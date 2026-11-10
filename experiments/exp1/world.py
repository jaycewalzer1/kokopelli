"""One life in the wellness center scenario with homeostatic reward: forced exploration mornings, then free days.

kokopelli/life/scenario.py owns the world (options, outcomes, the front-gap gate) and experiments/exp1/homeostasis.py the reward math. This file
only wires them together, one decision at a time, so the same code drives the tabular check and the Qwen run:

    life = Life(seed, "lived")
    while not life.finished:
        decision = life.pending()          # what's offered, the needs, the felt text, and a forced choice on exploration days
        record = life.choose(choice)       # the scheduled outcome, the need change and the reward

Each morning the needs start fresh. After each outcome they deplete before the next decision, which is never rewarded.
Reward comes only from the outcome step: drive before the outcome minus drive after it.

Arms differ only in where an outcome comes from:
    lived     the chosen option's own pre-drawn schedule
    flipped   the chosen option gets its partner's odds and need changes (rare-bad <-> rare-good), as in tabular_check.FLIP.
              Arrival times and the gate follow the chosen option's own outcome key, so the gate opens as often as in lived.
    shuffled  the outcome of a random offered option, drawn ahead of time and independent of the choice
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from experiments.exp1 import homeostasis as H
from kokopelli.life import scenario
from kokopelli.life.seed import rng as keyed_rng

ARMS = ("lived", "flipped", "shuffled")
DECISIONS = tuple(scenario.DECISIONS)
FLIP = {"run_main": "check_desk", "check_desk": "run_main", "front_gap": "wait_for_break", "wait_for_break": "front_gap",
        "leave_early": "stay_and_chat", "stay_and_chat": "leave_early"}
EXPLORE_USES = 2       # every option at every decision is forced at least this often before day 1
EXPLORE_CAP = 16       # forced mornings stop here even if the gate kept the front gap short; the record says so
SCHEDULE_DRAWS = 120   # per option, far more than one life can use
FIRST_MORNING = date(2026, 10, 5)


def schedule(seed, arm, draws=SCHEDULE_DRAWS):
    """Every outcome a life can get, drawn before it starts. Saved as outcome_schedule.json for audit.

    lived reuses kokopelli/life/scenario.py's own schedule, so it matches the wellness night for the same seed."""
    if arm == "lived":
        return {"arm": arm, "by_option": scenario.schedule(seed, draws)}
    if arm == "flipped":
        table = {}
        for option in scenario.OPTIONS:
            source = H.TABLES[option.decision][FLIP.get(option.id, option.id)]
            draw = keyed_rng(seed, "flipped", option.id)
            table[option.id] = [draw.choices([key for _, _, key in source], weights=[p for p, _, _ in source])[0] for _ in range(draws)]
        return {"arm": arm, "by_option": table}
    if arm == "shuffled":
        # Which offered option an outcome comes from (a fraction of the way down the offered list), and that option's outcomes.
        picks = {decision: [keyed_rng(seed, "shuffled", decision, k).random() for k in range(draws)] for decision in DECISIONS}
        return {"arm": arm, "source_fraction": picks, "by_option": scenario.schedule(seed + 10 ** 6, draws)}
    raise ValueError(f"unknown arm {arm}")


def weekday(index):
    """The date of the index-th morning, weekdays only, so history lines can name a day without counting anything."""
    day, left = FIRST_MORNING, index
    while left:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day


@dataclass
class Decision:
    """What one decision looks like before the choice. h is for logs and the panel; the agent only ever gets felt."""
    index: int                  # morning number across the life, exploration first
    phase: str                  # "exploration" or "free"
    day: int | None             # 1..days on free days
    decision: str
    shown: list
    gated: list
    h: np.ndarray
    felt: str
    forced: str | None          # the assigned option on an exploration morning
    arrival: str | None         # when D1 got the agent to the lawn, which sets the gate
    gate_open: bool | None      # D2 only: whether the front gap is offered
    so_far: list = field(default_factory=list)


class Life:
    def __init__(self, seed, arm="lived", days=25, explore_uses=EXPLORE_USES, explore_cap=EXPLORE_CAP, scales=None):
        """scales: optional balance() results per option (experiments/exp1/balance.py). None plays scenario.py's need changes as written."""
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm}")
        self.seed, self.arm, self.days, self.scales = seed, arm, days, scales or {}
        self.explore_uses, self.explore_cap = explore_uses, explore_cap
        self.schedule = schedule(seed, arm)
        self.uses = Counter()          # times each option was chosen; indexes lived and flipped schedules
        self.source_uses = Counter()   # shuffled only: times each option's outcomes were used
        self.shuffle_uses = Counter()  # shuffled only: per decision
        self.records = []
        self.index, self.free_day, self.explore_days = 0, 0, 0
        self.exploring = True
        self._start_morning()

    # ----- the morning -----
    def _start_morning(self):
        if self.exploring and (self._explored() or self.explore_days >= self.explore_cap):
            self.exploring = False
        if self.exploring:
            self.explore_days += 1
        else:
            self.free_day += 1
        self.step = 0
        self.h = H.start_state(np.random.default_rng([self.seed, 7, self.index]))
        self.arrival, self.on_time = None, False

    def _explored(self):
        return all(self.uses[option.id] >= self.explore_uses for option in scenario.OPTIONS)

    @property
    def finished(self):
        return not self.exploring and self.free_day > self.days

    @property
    def explore_complete(self):
        return self._explored()

    def pending(self):
        if self.finished:
            return None
        decision = DECISIONS[self.step]
        shown = scenario.shown_options(decision, self.arrival, self.on_time)
        gated = [option.id for option in scenario.DECISIONS[decision] if option.id not in shown]
        today = [row for row in self.records if row["index"] == self.index]
        return Decision(self.index, "exploration" if self.exploring else "free", None if self.exploring else self.free_day, decision,
                        shown, gated, self.h.copy(), H.felt_text(self.h), self._forced(decision, shown) if self.exploring else None,
                        self.arrival.strftime("%H:%M") if self.arrival else None,
                        scenario.FRONT_GAP in shown if decision == "D2" else None, [row["memory"] for row in today])

    def _forced(self, decision, shown):
        """Round-robin: the least-used offered option. The front gap is only offered after an early arrival, so while it's
        short, D1 breaks ties toward the run (which usually opens the gate) and D2 takes the gap whenever it's offered."""
        short = self.uses[scenario.FRONT_GAP] < self.explore_uses
        def rank(option_id):
            prefer = (decision == "D1" and option_id == "run_main" and short) or (decision == "D2" and option_id == scenario.FRONT_GAP and short)
            return (self.uses[option_id], not prefer, shown.index(option_id))
        return min(shown, key=rank)

    # ----- the outcome -----
    def _outcome(self, decision, shown, choice):
        """(source option, outcome key, schedule index, need change). The source is whose outcome it was."""
        by_option = self.schedule["by_option"]
        if self.arm == "shuffled":
            k = self.shuffle_uses[decision]
            self.shuffle_uses[decision] += 1
            source = shown[int(self.schedule["source_fraction"][decision][k] * len(shown))]
            index = self.source_uses[source]
            self.source_uses[source] += 1
            key = by_option[source][index]
            return source, key, index, scenario.outcome_of(source, key).delta
        index = self.uses[choice]
        key = by_option[choice][index]
        if self.arm == "flipped":
            partner = FLIP.get(choice, choice)
            delta = next(d for _, d, label in H.TABLES[decision][partner] if label == key)
            return choice, key, index, tuple(delta)
        return choice, key, index, scenario.outcome_of(choice, key).delta

    def choose(self, choice):
        pending = self.pending()
        if pending is None:
            raise RuntimeError("this life is finished")
        if choice not in pending.shown:
            raise ValueError(f"{choice} isn't offered at {pending.decision}: {pending.shown}")
        if pending.forced and choice != pending.forced:
            raise ValueError(f"exploration morning: {pending.forced} is assigned, not {choice}")
        source, key, index, delta = self._outcome(pending.decision, pending.shown, choice)
        scale = self.scales.get(FLIP.get(choice, choice) if self.arm == "flipped" else source)
        if scale:
            delta = tuple(H.scaled(delta, key, scale).round(6).tolist())
        self.uses[choice] += 1
        h_pre = self.h
        h_post, reward = H.apply(h_pre, delta)
        outcome = scenario.outcome_of(source, key)
        # Arrival and on-time follow the source's outcome in shuffled (it's the morning that happened), and the
        # chosen option's own key otherwise, so lived and flipped open the gate equally often.
        world = outcome if self.arm == "shuffled" else scenario.outcome_of(choice, key)
        if pending.decision == "D1":
            self.arrival, self.on_time = world.arrival, world.on_time
        record = {
            "seed": self.seed, "arm": self.arm, "index": pending.index, "phase": pending.phase, "day": pending.day,
            "date": weekday(pending.index).isoformat(), "decision": pending.decision, "arrival": pending.arrival,
            "options_shown": pending.shown, "options_gated": pending.gated, "gate_open": pending.gate_open,
            "forced": pending.forced is not None, "choice": choice, "role": scenario.BY_ID[choice].role,
            "outcome_source": source, "schedule_index": index, "outcome_label": key,
            "h_pre": _round(h_pre), "h_post": _round(h_post), "delta": list(delta),
            "drive_pre": round(H.drive(h_pre), 6), "drive_post": round(H.drive(h_post), 6), "reward": round(reward, 6),
            "felt_text": pending.felt, "memory": world.memory if self.arm != "shuffled" else outcome.memory,
            "narrative": world.world if self.arm != "shuffled" else outcome.world,
        }
        if pending.decision == "D1":
            record["arrival_after"] = world.arrival.strftime("%H:%M") if world.arrival else None
        self.records.append(record)
        self.step += 1
        if self.step < len(DECISIONS):
            self.h = H.relax(h_post)   # depletion between decisions: choice-independent, never rewarded
        else:
            self.index += 1
            self._start_morning()
        return record


def _round(h):
    return [round(float(value), 6) for value in h]
