"""Gives an agent an inner life: it says what changed, updates how it feels from that, then decides only at a decision point.

FeelingAgent wraps any runtime agent, so the loop in kokopelli/loop/loop.py runs unchanged. See kokopelli/mind/OPEN_DECISIONS.md.
What the model says it feels shapes only its own later prompts, and is never used as a score.

Real Qwen returned whatever feeling its history named, whatever the frames showed (kokopelli/mind/MEASUREMENTS.md). So the change is
judged from images alone, a tick where nothing changed asks no feeling at all, and settle() keeps the mood continuous.

feelings.jsonl has two kinds of row, written as they happen, so a viewer can read it during a run. timeline() joins them.
    appraisal: tick, t, feeling, intensity, why, raw (only if unparseable), visible, point, reason, seconds, usage,
               change, change_raw (only if unparseable), change_seconds, change_usage, reported (what the model said, before
               settle), carried (true when nothing changed, so no feeling was asked for), last_frame
    choice:    tick, t, action, decided (false when a quiet tick carried on with no decision call), seconds, usage
"""
import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path

RECENT_SHOWN = 5
MAX_FEELING_CHARS = 30
MAX_WHY_CHARS = 200  # With RECENT_SHOWN, this caps what feelings add to a prompt however long the run gets.
MAX_CHANGE_CHARS = 200
MAX_STEP = 0.15  # The most intensity can move in one tick. A full swing takes minutes, not one 30 second tick.
SWITCH_BELOW = 0.3  # A feeling has to fade to here before a different one can take over, so happy can't flip straight to sad.
MAX_GAP = 4  # Ticks without a decision before the agent gets one anyway, so it can't sleep through a quiet stretch.
BIG_INTENSITY = 0.7
DECIDE_MARK = "Decide what to do"
CHANGE = ("The first image is from a moment ago. The others are what you see now. Did anything actually change: someone arrived or "
          "left, something moved somewhere new, something happened? Small movements, camera drift and blur don't count. "
          'Reply with one JSON object and nothing else:\n{"changed": true or false, "what": "<one sentence about what changed, or empty>"}')
APPRAISE = ("Before doing anything, how do you feel about what just happened, and why? Reply with one JSON object and nothing else:\n"
            '{"feeling": "<one word>", "intensity": <0 to 1>, "why": "<one sentence about what you saw>"}')
BIG_NOTE = "This moment matters. Think about what your choice could lead to.\n"
FAILED_MARK = "It didn't work."  # kokopelli/loop/prompt_builder.outcome_text writes this after a failed action
FEEL_EVENTS_ENV = "KOKO_FEEL_EVENTS"  # "1" turns on known_event() below; off by default (P5, docs/log/fable/2026-11-10-P5.md)
CARRY_ON = "move_to"  # In the sim, wait cancels a walk in progress, so a tick with no decision has to keep walking.


def parse_appraisal(raw):
    """The appraisal in a reply, or None. A bad reply costs a feeling, not the tick."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group()) if match else None
        feeling, intensity, why = str(data["feeling"]).strip().lower(), float(data["intensity"]), str(data.get("why", "")).strip()  # pyright: ignore[reportOptionalSubscript, reportOptionalMemberAccess]  # None -> TypeError, caught below
    except (ValueError, TypeError, KeyError):
        return None
    if not feeling or intensity != intensity:
        return None
    return {"feeling": feeling[:MAX_FEELING_CHARS], "intensity": min(1.0, max(0.0, intensity)), "why": why[:MAX_WHY_CHARS]}


def parse_change(raw):
    """(what changed or None, whether the reply could be read). An unreadable reply counts as nothing changing."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group()) if match else None
        changed, what = data["changed"], str(data.get("what") or "").strip()  # pyright: ignore[reportOptionalSubscript, reportOptionalMemberAccess]  # None -> TypeError, caught below
    except (ValueError, TypeError, KeyError, AttributeError):
        return None, False
    if changed is not True:
        return None, True
    return (what or "Something changed.")[:MAX_CHANGE_CHARS], True


def known_event(agent_input, last_visible):
    """What the loop already knows happened this tick, without asking the model: someone or something came into or went
    out of view, or the last action failed. Real Qwen's frame-only check said "nothing changed" on 19 of 19 ticks of
    qwen_change_20, so with this off such a tick carries the old feeling unasked."""
    gained = [name for name in agent_input.visible if name not in last_visible]
    lost = [name for name in last_visible if name not in agent_input.visible]
    parts = [f"Now in view: {', '.join(gained)}." if gained else "", f"No longer in view: {', '.join(lost)}." if lost else "",
             "What you just tried didn't work." if FAILED_MARK in agent_input.prompt else ""]
    return " ".join(p for p in parts if p)[:MAX_CHANGE_CHARS] or None


def settle(current, reported):
    """The feeling after this tick. The model says where it's heading, and this limits how far the mood gets in one tick."""
    if not current:
        return reported
    if reported["feeling"] != current["feeling"]:
        if current["intensity"] > SWITCH_BELOW:
            return {**reported, "feeling": current["feeling"], "intensity": round(max(SWITCH_BELOW, current["intensity"] - MAX_STEP), 3)}
        return {**reported, "intensity": min(reported["intensity"], SWITCH_BELOW)}
    step = max(-MAX_STEP, min(MAX_STEP, reported["intensity"] - current["intensity"]))
    return {**reported, "intensity": round(current["intensity"] + step, 3)}


def decision_point(previous, appraisal, visible, last_visible, gap, change=None):
    """Return (size, reason) if this tick is a decision point, or None. A rule rather than a model, so a run can be checked."""
    intensity, feeling = (appraisal["intensity"], appraisal["feeling"]) if appraisal else (0.0, None)
    if previous is None:
        return "small", "first look"
    if intensity >= BIG_INTENSITY:
        return "big", "strong feeling"
    if set(visible) != set(last_visible):
        return "small", "what's in view changed"
    if change:
        return "small", "something changed"
    if feeling and feeling != previous:
        return "small", "feeling changed"
    if gap >= MAX_GAP:
        return "small", "been a while"
    return None


def inner_context(rows):
    """What the agent knows about itself: its recent feelings and its last choice."""
    feelings = [row for row in rows if row["kind"] == "appraisal" and row["feeling"] and not row.get("carried")][-RECENT_SHOWN:]
    lines = [f"[{row['t']}] {row['feeling']} ({row['intensity']:.1f}): {row['why']}" for row in feelings]
    last = next((row["action"] for row in reversed(rows) if row["kind"] == "choice"), None)
    return (f"How you've been feeling:\n{chr(10).join(lines) or '(nothing yet)'}\n\n"
            f"What you last chose to do: {json.dumps(last) if last else 'nothing yet'}\n\n")


def _change_line(change):
    return f"What just changed: {change}\n\n" if change else ""


def appraisal_prompt(base, rows, change=None):
    before, _, _ = base.partition(DECIDE_MARK)
    return f"{before}{inner_context(rows)}{_change_line(change)}{APPRAISE}"


def decision_prompt(base, rows, size="small"):
    before, mark, after = base.partition(DECIDE_MARK)
    change = next((row.get("change") for row in reversed(rows) if row["kind"] == "appraisal"), None)
    return f"{before}{inner_context(rows)}{_change_line(change)}{BIG_NOTE if size == 'big' else ''}{mark}{after}"


def parse_action(raw, visible):
    """The action the loop would carry out for this reply, or None. Uses the loop's parser so the record can't disagree with the sim."""
    from kokopelli.mind.actions import InvalidDecision, parse_decision
    try:
        return parse_decision(raw, visible).action.model_dump()
    except InvalidDecision:
        return None


def read_rows(path):
    """Every complete row. A process killed mid-write leaves a torn last line, which is dropped."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return rows


def timeline(path):
    """One entry per tick, joining what the agent felt with what it did. No action means both replies were invalid."""
    rows = read_rows(path)
    choices = {row["tick"]: row for row in rows if row["kind"] == "choice"}
    return [{"tick": row["tick"], "t": row["t"], "feeling": row["feeling"], "intensity": row["intensity"], "why": row["why"], "change": row.get("change"),
             "point": row["point"], "reason": row["reason"], "action": choices.get(row["tick"], {}).get("action"),
             "decided": choices.get(row["tick"], {}).get("decided", False)}
            for row in rows if row["kind"] == "appraisal"]


class FeelingAgent:
    """Runs appraise, gate, decide inside the loop's one agent turn. Rows go to a file, so a resumed run keeps its past."""

    def __init__(self, inner, path, events=None):
        self.inner, self.path = inner, Path(path)
        # Known events count as a change (known_event); off unless asked for, or KOKO_FEEL_EVENTS=1.
        self.events = os.environ.get(FEEL_EVENTS_ENV) == "1" if events is None else events
        self.rows = read_rows(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rewrite()
        self.tick_prompt = None

    def release(self):
        self.inner.release()

    def _rewrite(self):
        # Write then rename, so being killed here leaves the old file or the new one.
        temp = self.path.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        os.replace(temp, self.path)

    def _write(self, row):
        self.rows.append(row)
        with open(self.path, "a") as file:
            file.write(json.dumps(row) + "\n")
            file.flush()

    def _rewind(self, tick):
        """A resume repeats any tick after the last checkpoint, so whatever that tick felt before never happened."""
        if any(row["tick"] >= tick for row in self.rows):
            self.rows = [row for row in self.rows if row["tick"] < tick]
            self._rewrite()

    def _ask(self, agent_input, prompt):
        clock = time.perf_counter()
        raw = self.inner.decide(replace(agent_input, prompt=prompt))
        return raw, {"seconds": round(time.perf_counter() - clock, 3), "usage": getattr(self.inner, "last_usage", None)}

    def _appraisal_rows(self):
        return [row for row in self.rows if row["kind"] == "appraisal"]

    def _notice(self, agent_input, past):
        """What changed since last tick, judged from the frames alone, so it can't echo the notes or feelings in the prompt."""
        previous = past[-1].get("last_frame")
        images = [previous, *agent_input.images] if previous else agent_input.images
        raw, cost = self._ask(replace(agent_input, retry_error=None, images=images), CHANGE)
        change, readable = parse_change(raw)
        return {"change": change, "change_raw": None if readable else raw, "change_seconds": cost["seconds"], "change_usage": cost["usage"]}

    def _appraise(self, agent_input):
        past = self._appraisal_rows()
        noticed = self._notice(agent_input, past) if past else {"change": None, "change_raw": None, "change_seconds": 0.0, "change_usage": None}
        change = noticed["change"]
        if past and not change and self.events:
            change = known_event(agent_input, past[-1]["visible"])
            if change:
                noticed = {**noticed, "change": change, "change_from": "event"}
        current = next((row for row in reversed(past) if row["feeling"]), None)
        previous = current["feeling"] if current else ("" if past else None)
        last_visible = past[-1]["visible"] if past else []
        decided = [row["tick"] for row in past if row["point"]]
        gap = agent_input.tick - decided[-1] if decided else 0
        fields = {"raw": None, "reported": None, "carried": False}
        if past and not change:
            felt = current and {key: current[key] for key in ("feeling", "intensity", "why")}
            gate, fields["carried"] = None, True
        else:
            raw, cost = self._ask(replace(agent_input, retry_error=None), appraisal_prompt(agent_input.prompt, self.rows, change))
            reported = parse_appraisal(raw)
            felt = reported and settle(current, reported)
            # The mood moves slowly, but how big this moment is comes from what the model just said about it.
            gate = reported and {**felt, "intensity": reported["intensity"]}  # pyright: ignore[reportGeneralTypeIssues]  # felt is a dict whenever reported is
            fields.update(raw=raw if not reported else None, reported=reported, **cost)
        point = decision_point(previous, gate, agent_input.visible, last_visible, gap, change)
        self._write({"kind": "appraisal", "tick": agent_input.tick, "t": agent_input.now, "seconds": 0.0, "usage": None, **fields, **noticed,
                     "feeling": felt and felt["feeling"], "intensity": felt and felt["intensity"], "why": felt and felt["why"],
                     "visible": list(agent_input.visible), "last_frame": str(agent_input.images[-1]) if agent_input.images else None,
                     "point": point[0] if point else None, "reason": point[1] if point else None})
        return point

    def _carry_on(self, agent_input):
        last = next((row["action"] for row in reversed(self.rows) if row["kind"] == "choice"), None)
        action = last if last and last.get("type") == CARRY_ON and last.get("target") in agent_input.visible else {"type": "wait"}
        self._write({"kind": "choice", "tick": agent_input.tick, "t": agent_input.now, "action": action, "decided": False,
                     "seconds": 0.0, "usage": None})
        return json.dumps({"action": action})

    def decide(self, agent_input):
        if not agent_input.retry_error or self.tick_prompt is None:  # A retry is the same moment, so it isn't felt a second time.
            self._rewind(agent_input.tick)
            point = self._appraise(agent_input)
            if not point:
                return self._carry_on(agent_input)
            self.tick_prompt = decision_prompt(agent_input.prompt, self.rows, point[0])
        raw, cost = self._ask(agent_input, self.tick_prompt)
        action = parse_action(raw, agent_input.visible)
        if action:
            self._write({"kind": "choice", "tick": agent_input.tick, "t": agent_input.now, "action": action, "decided": True, **cost})
        return raw
