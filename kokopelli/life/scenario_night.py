"""The wellness center night: a new life, written at months up to age 20, then weekday mornings where the agent runs late to class.

Everything goes through the life generator. The world writer writes every stretch from all the context above it, as always.
Only the scenario's decision moments zoom down to 30 seconds; every other stretch stops at its own level. At a decision
moment the agent (Qwen) gets a short, high-level picture of who it is, how it feels in words, one line per recent morning
and its options, never odds or counts. The outcome comes from a schedule drawn before the run, and the world writer is told
what happened and writes it. The scenario's rules are in kokopelli/life/scenario.py.

    python -m kokopelli.life.scenario_night stage            # write the job out for the Start button on the GPU queue page
    python -m kokopelli.life.scenario_night --queued FOLDER  # what the Start button runs: takes turns in the GPU queue until done
    python -m kokopelli.life.scenario_night --run FOLDER     # one turn, run inside the queue by --queued
    python -m kokopelli.life.scenario_night --mock           # the whole night with stand-in models, in a minute or two

Phases, each resumable after a crash: calibrate (CPU), life (Qwen), export, clips (Cosmos, after Qwen is unloaded).

It's a polite job. Other work comes first, so between model calls it checks two things. If a job with a lower priority number
is waiting in the GPU queue, it frees its model and ends its turn with exit code 75, and --queued puts it back in the line
behind that job. If memory runs short (ram_share.py), it gives the model back and waits for room. Every step it took is
saved, so the next turn picks up where this one stopped.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kokopelli.life import scenario
from kokopelli.life.engine import Budget, Engine
from kokopelli.life.llm_generator import LLMGenerator, parse_opening
from kokopelli.life.memory import FAILED, GIST_END
from kokopelli.life.panel import seed_from
from kokopelli.life.prompts import kind_of, opening_prompt
from kokopelli.life.resolver import Resolver
from kokopelli.life.seed import rng
from kokopelli.life.store import Store
from kokopelli.life.pipeline import process_table, read_tickets
from kokopelli.life.windows import children, depth, life_window
from kokopelli.settings import GPU_QUEUE_SCRIPT, LIFE_FOCUS, PIPELINE_PATHS, ROOT, SCENARIO_NIGHT, SCENARIO_OUT, STAGED_JOBS

from kokopelli.ops import ram_share

MAX_CRASHES = 5
YIELDED = 75  # gpu.py and the GPU page read this exit code as "out of time, can resume"
REQUEUE_SECONDS = 60
NO_LIMIT = 10 ** 9
ARM, RATE_MODE = "lived", "iid"
AGENT_SYSTEM = """You are living one person's life from the inside, a moment at a time. You are that person.
Choose what you do next from the options given. Go by who you are, how you feel right now and what your recent mornings were like.
Reply with one JSON object and nothing else: {"choice": "<option id>", "reason": "<one sentence>"}"""
DIARY_SYSTEM = """You are living one person's life from the inside. Write a short diary entry in the first person, 4 to 6 sentences,
about your recent mornings going to the outdoor class at the wellness center. Plain text, no heading."""
CLIP_SCENES = {"D1": "The bus stop at the entrance gate of a community wellness center's green outdoor grounds, a paved path leading in.",
               "D2": "The edge of an open lawn where an outdoor fitness class is underway, the instructor at the front, people in rows.",
               "D3": "An open lawn as an outdoor class ends, people stretching and drifting toward a path to the bus stop."}


def mornings(config=SCENARIO_NIGHT):
    """The class mornings: weekdays from the first one."""
    found, day = [], date.fromisoformat(config["first_morning"])
    while len(found) < config["mornings"]:
        if day.weekday() < 5:
            found.append(day)
        day += timedelta(days=1)
    return found


class Scenario:
    """The mornings, what has been decided so far, and what comes next. Rebuilt from the store's log on a resume."""

    def __init__(self, store, run_id, config=SCENARIO_NIGHT):
        self.store, self.run_id, self.config = store, run_id, config
        self.days = mornings(config)
        self.seed_key = f"{config['seed']['rng_seed']}"
        self.schedule = scenario.schedule(self.seed_key)
        self.records = [event["data"] for event in store.events(run_id, kind="scenario_decision")]

    def moment(self, morning, decision):
        if decision == "D2":
            d1 = self.record(morning, "D1")
            return datetime.combine(self.days[morning], scenario.outcome_of(d1["choice"], d1["outcome"]).arrival) if d1 else None
        return datetime.combine(self.days[morning], scenario.DECISION_TIMES[decision])

    def record(self, morning, decision):
        return next((row for row in self.records if row["morning"] == morning and row["decision"] == decision), None)

    def moments(self):
        """Every decision moment known so far, as (when, morning, decision)."""
        found = []
        for morning in range(len(self.days)):
            for decision in ("D1", "D2", "D3"):
                when = self.moment(morning, decision)
                if when is not None:
                    found.append((when, morning, decision))
        return found

    def holds_moment(self, window):
        return any(window.start <= when < window.end for when, _, _ in self.moments())

    def moment_at(self, window):
        if window.level != "sec30":
            return None
        return next(((morning, decision) for when, morning, decision in self.moments() if when == window.start), None)

    def anchor_texts(self, window):
        """What the world writer is told is fixed in a stretch. Above a day it's one line for all the mornings, so a year isn't a list."""
        inside = [day for day in self.days if window.start <= datetime.combine(day, scenario.CLASS_START) < window.end]
        if not inside:
            return []
        if depth(window.level) < depth("day"):
            return [f"Weekday mornings from {inside[0]:%b %d} to {inside[-1]:%b %d, %Y}: a 9:00 outdoor class on the lawn at a community "
                    "wellness center, reached by bus. The bus gets there at 9:06, after class has started."]
        if window.level == "day":
            return ["At 9:06 the bus drops them at the main gate of the community wellness center, six minutes after the 9:00 outdoor "
                    "class on the lawn has started. The lawn is an 8 minute walk down the main path. Class ends at 9:50, and buses leave "
                    "the main gate at 10:00 and 10:30."]
        texts = {"D1": "9:06: the bus drops them at the main gate. The 9:00 outdoor class on the lawn has already started.",
                 "D3": "9:50: the outdoor class is ending. Buses leave the main gate at 10:00 and 10:30, and another route stops at the far stop."}
        found = []
        for when, _morning, decision in self.moments():
            if window.start <= when < window.end:
                found.append(texts.get(decision) or f"{when:%-H:%M}: they reach the edge of the class lawn, where class is underway "
                                                         "with the instructor at the front.")
        return found

    def uses(self, option_id):
        return sum(row["choice"] == option_id for row in self.records)

    def state_entering(self, morning, decision):
        """The needs as this decision finds them: a fresh morning at D1, then carried and relaxed toward the setpoint."""
        if decision == "D1":
            return scenario.start_of_day(self.seed_key, morning)
        before = self.record(morning, "D1" if decision == "D2" else "D2")
        return scenario.relax(before["state_after"])

    def cosmetic(self, morning):
        return rng(self.seed_key, "cosmetic", morning).choice(scenario.COSMETIC)

    def history(self, morning):
        """One line per earlier morning, in words. Never counts or rates: a frequency is a description."""
        lines = []
        for earlier in range(max(0, morning - self.config["history_mornings"]), morning):
            parts = [self.record(earlier, decision) for decision in ("D1", "D2", "D3")]
            done = [scenario.outcome_of(part["choice"], part["outcome"]).memory for part in parts if part]
            if done:
                lines.append(f"{self.days[earlier]:%A}: {', '.join(done)}.")
        return lines

    def so_far(self, morning, decision):
        earlier = [self.record(morning, step) for step in ("D1", "D2", "D3")[:("D1", "D2", "D3").index(decision)]]
        return [scenario.outcome_of(row["choice"], row["outcome"]).memory for row in earlier if row]


def clock_line(when, decision):
    if decision == "D1":
        return f"{when:%-H:%M}. The bus just dropped you at the main gate of the wellness center. Your 9:00 outdoor class on the lawn has already started."
    if decision == "D2":
        return f"{when:%-H:%M}. You've reached the edge of the class lawn. Class is underway, with the instructor at the front."
    return f"{when:%-H:%M}. Class is ending. Buses leave the main gate at 10:00 and 10:30, and another route stops at the far stop across the grounds."


def gist(text):
    return GIST_END.split(text or "")[0] if text and not text.startswith(FAILED) else ""


class ScenarioGenerator(LLMGenerator):
    """The world writer, told about the mornings as fixed events, and told what happened at each decision."""

    def __init__(self, seed, rng_key, plan, **kwargs):
        super().__init__(seed, rng_key, **kwargs)
        self.plan = plan

    def write_opening(self, context):
        window = context["window"]
        anchors = self.plan.anchor_texts(window)
        focus = rng(self.rng_key, window.id, "focus").choice(LIFE_FOCUS) if kind_of(window.level) in ("period", "day") and not anchors else ""
        system, user = opening_prompt(self.seed, context, anchors, focus)
        answer = self._ask("opening", window, system, user, parse_opening)
        if answer is None:
            return 0.0, {"setting": f"{FAILED} {window.label}", "exogenous": anchors, "pressures": [], "open_questions": []}
        salience, opening = answer
        return 1.0 if anchors else salience, {**opening, "exogenous": anchors}


class NoEscalation(Resolver):
    """A stretch never turns out to need finer detail mid-way, so only the decision moments go deep and the night's cost is known."""

    def escalates(self, window):
        return False


class ScenarioEngine(Engine):
    def __init__(self, store, run_id, plan, agent_complete, log_path=None, **kwargs):
        super().__init__(store, run_id, **kwargs)
        self.plan, self.agent_complete, self.log_path = plan, agent_complete, log_path
        self.rng_key = store.rng_key(run_id)

    def _limit(self, salience, window=None):
        if window is not None and self.plan.holds_moment(window):
            return "sec30"
        return super()._limit(salience)

    def _choice_point(self, window, node):
        found = self.plan.moment_at(window)
        if found is None:
            return super()._choice_point(window, node)
        morning, decision = found
        record = self._decide(window, morning, decision)
        option, outcome = scenario.BY_ID[record["choice"]], scenario.outcome_of(record["choice"], record["outcome"])
        self.store.append_event(self.run_id, node["node_id"], window.start, "choice_point", {"options": record["options_shown"]})
        choice = {"verb": option.action, "stance": "engage", "option": option.id}
        self.store.append_event(self.run_id, node["node_id"], window.start, "choice", {**choice, "reason": record["reason"]})
        self.store.append_event(self.run_id, node["node_id"], window.start, "scenario_decision", record)
        self.plan.records.append(record)
        return self._close(window, node, stance="engage", choices=[choice], extra={"fixed_outcome": outcome.world})

    def _decide(self, window, morning, decision):
        started = time.monotonic()
        plan = self.plan
        exploring = morning < plan.config["explore_mornings"]
        d1 = plan.record(morning, "D1")
        arrival = scenario.outcome_of(d1["choice"], d1["outcome"]).arrival if d1 else None
        on_time = scenario.outcome_of(d1["choice"], d1["outcome"]).on_time if d1 else False
        assigned = scenario.exploration_choice(decision, morning) if exploring else None
        shown = scenario.shown_options(decision, arrival, on_time, forced_open=assigned == scenario.FRONT_GAP)
        gated = [option.id for option in scenario.DECISIONS[decision] if option.id not in shown]
        before = plan.state_entering(morning, decision)
        feel = scenario.feel_line(before)
        if assigned:
            choice, reason, fallback = assigned, "assigned on an exploration morning", False
        else:
            choice, reason, fallback = self._ask_agent(window, morning, decision, shown, feel)
        index = plan.uses(choice)
        key = plan.schedule[choice][index % len(plan.schedule[choice])]
        outcome = scenario.outcome_of(choice, key)
        after = scenario.apply(before, outcome.delta)
        when = window.start
        return {"seed": plan.seed_key, "arm": ARM, "rate_mode": RATE_MODE, "morning": morning, "day": morning + 1, "date": plan.days[morning].isoformat(),
                "phase": "exploration" if exploring else "consequential", "decision": decision, "clock": f"{when:%H:%M}",
                "arrival": arrival.isoformat() if arrival else None, "options_shown": shown, "options_gated": gated, "choice": choice,
                "reason": reason, "fallback": fallback, "option_draw_index": index, "outcome": key, "role": scenario.BY_ID[choice].role,
                "points": outcome.points, "state_before": before, "state_after": after, "drive_before": scenario.drive(before),
                "drive_after": scenario.drive(after), "reward": scenario.reward(before, after), "feel_line": feel, "feel_after": scenario.feel_line(after),
                "narrative": outcome.world, "cosmetic": plan.cosmetic(morning), "node_id": window.id,
                "upstream_path": [f"{row['choice']}:{row['outcome']}" for row in (plan.record(morning, step) for step in ("D1", "D2") if step < decision) if row],
                "wall_ms": round((time.monotonic() - started) * 1000)}

    def who(self, when):
        """The agent's basic picture of itself: high level, from the life's own sketch and this year's."""
        seed = self.seed
        birth = seed.birth_date
        life = self.store.node(self.run_id, life_window(birth).id)
        year = next(window for window in children(life_window(birth), birth) if window.start <= when < window.end)
        year_node = self.store.node(self.run_id, year.id)
        age = int((when.date() - birth).days // 365.25)
        lines = [f"You are {age}, in {year.label.replace('College', 'year')} of college, living in {seed.place}." if year.label.startswith("College")
                 else f"You are {age}, living in {seed.place}.", f"Temperament: {seed.temperament}." if seed.temperament else ""]
        lines += [gist(life and life["opening"]["setting"]), gist(year_node and year_node["opening"]["setting"])]
        return "\n".join(line for line in lines if line)

    def _ask_agent(self, window, morning, decision, shown, feel):
        plan = self.plan
        scene = [clock_line(window.start, decision), f"Today: {plan.cosmetic(morning)}."]
        so_far = plan.so_far(morning, decision)
        if so_far:
            scene.append(f"This morning so far, you {', then '.join(so_far)}.")
        history = plan.history(morning)
        options = "\n".join(f"- {option_id}: {scenario.BY_ID[option_id].shown}" for option_id in shown)
        checked = "\n".join([*scene, *history, feel, options])
        leaks = scenario.find_leaks(checked)
        if leaks:
            raise RuntimeError(f"probability words would reach the agent: {leaks}")
        user = "\n\n".join(f"{title}\n{body}" for title, body in (
            ("WHO YOU ARE", self.who(window.start)), ("RECENT MORNINGS", "\n".join(history) or "This is your first morning at this class."),
            ("NOW", "\n".join(scene)), ("HOW YOU FEEL", feel), ("YOUR OPTIONS", options)) if body)
        settings = plan.config["agent"]
        for attempt in range(settings["attempts"]):
            sample = rng(self.rng_key, window.id, "agent", attempt).randrange(2 ** 31)
            started = time.monotonic()
            result = self.agent_complete(AGENT_SYSTEM, user, max_tokens=settings["max_tokens"], temperature=settings["temperature"], seed=sample)
            parsed = parse_choice(result.text, shown)
            log_call(self.log_path, "agent", window, attempt, AGENT_SYSTEM, user, result, time.monotonic() - started, None if parsed else "unusable choice")
            if parsed:
                return (*parsed, False)
        # Logged as a fallback, so a run with many of them can be thrown out rather than trusted.
        return rng(self.rng_key, window.id, "fallback").choice(shown), "no usable answer, chosen at random", True


def parse_choice(raw, shown):
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    try:
        answer = json.loads(match.group()) if match else None
    except json.JSONDecodeError:
        answer = None
    if not isinstance(answer, dict) or answer.get("choice") not in shown:
        return None
    return answer["choice"], str(answer.get("reason") or "").strip()[:300]


def log_call(path, write, window, attempt, system, user, result, seconds, error):
    if not path:
        return
    print(f"{time.strftime('%H:%M:%S')} scenario {write} {window.id if window else '-'} try {attempt + 1} {seconds:.1f}s{' FAILED: ' + error if error else ''}", flush=True)
    with open(path, "a") as log:
        log.write(json.dumps({"at": time.time(), "tag": "scenario", "write": write, "node": window.id if window else None,
                              "level": window.level if window else None, "attempt": attempt, "ok": error is None, "error": error,
                              "seconds": round(seconds, 2), "system": system, "user": user, "raw": result.text,
                              "prompt_tokens": result.prompt_tokens, "generation_tokens": result.generation_tokens,
                              "generation_tps": result.generation_tps, "peak_memory_gb": result.peak_memory, "finish_reason": result.finish_reason}) + "\n")


class YieldTurn(Exception):
    """A more important job is waiting for the GPU. Raised between steps, so nothing half-written is kept."""


def more_important_waiting(priority, queue=None):
    """Names of live tickets waiting for this Mac's GPU with a lower priority number than ours. Jobs sent to PACE don't count."""
    if priority is None:
        return []
    folder = Path(queue or Path(PIPELINE_PATHS["ops"]) / "queue")
    tickets, _ = read_tickets(folder, process_table())
    names = []
    for ticket in tickets:
        try:
            where = json.loads((folder / f"{Path(ticket['id']).name}.json").read_text()).get("where", "local")
        except (OSError, ValueError):
            where = "local"
        if not ticket["running"] and where != "pace" and (ticket["priority"] if ticket["priority"] is not None else 10 ** 6) < priority:
            names.append(ticket["name"])
    return names


class Polite:
    """A model call that first gives way: to a more important job in the queue, then to anything short of memory."""

    def __init__(self, complete, guard, priority):
        self.complete, self.guard, self.priority = complete, guard, priority

    def check(self):
        waiting = more_important_waiting(self.priority)
        if waiting:
            raise YieldTurn(", ".join(waiting))
        if self.guard:
            self.guard.before()

    def __call__(self, *args, **kwargs):
        self.check()
        return self.complete(*args, **kwargs)


# Stand-in models, so the whole night can be rehearsed on the CPU in a minute or two.
def mock_complete(system, user, max_tokens=512, temperature=0.7, seed=None):
    draw = rng("mock", seed, user[-200:])
    if system.startswith("You are living one person's life from the inside, a moment"):
        shown = re.findall(r"^- (\w+):", user, re.MULTILINE)
        text = json.dumps({"choice": draw.choice(shown), "reason": "[mock] it seemed right."})
    elif system.startswith(DIARY_SYSTEM[:40]):
        text = "[mock] The mornings at the wellness center ran together."
    elif "Write the opening" in system:
        text = json.dumps({"salience": round(draw.random() ** 3, 3), "setting": "[mock] a stretch of time.", "pressures": [], "open_questions": []})
    else:
        text = json.dumps({"summary": "[mock] it passed.", "what_happened": "[mock] it passed."})
    return SimpleNamespace(text=text, prompt_tokens=len(user) // 4, generation_tokens=20, generation_tps=1000.0, peak_memory=0.0, finish_reason="stop")


def _load(folder):
    return json.loads((folder / "state.json").read_text())


def _save(folder, state):
    temporary = folder / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=1))
    temporary.replace(folder / "state.json")


def phase_calibrate(folder, state):
    scenario.check_points()
    result = scenario.calibrate(samples=2000 if state.get("mock") else 10000)
    (folder / "calibration.json").write_text(json.dumps(result, indent=1))
    print(f"Calibration {'passes' if result['passes'] else 'FAILS'}: best path {result['best_path']} {result['best_path_return']} "
          f"against a median of {result['median_path_return']}. Reported only; the run goes on.", flush=True)


def open_run(folder, state, store):
    if "run_id" not in state:
        state["run_id"] = store.create_run(seed_from(SCENARIO_NIGHT["seed"]))
        _save(folder, state)
    return state["run_id"]


def phase_life(folder, state):
    store = Store(folder / "life.db")
    try:
        run_id = open_run(folder, state, store)
        plan = Scenario(store, run_id)
        if state.get("mock"):
            complete = Polite(mock_complete, None, state.get("priority"))
        else:
            from kokopelli.wm import llm_model  # loaded only for a real run
            guard = ram_share.Guard("scenario_qwen", SCENARIO_NIGHT["qwen_gb"], unload=llm_model.unload, log=lambda line: print(line, flush=True))
            complete = Polite(llm_model.chat, guard, state.get("priority"))
        seed, key = store.public_seed(run_id), store.rng_key(run_id)
        generator = ScenarioGenerator(seed, key, plan, complete=complete, log_path=folder / "calls.jsonl", tag="scenario")
        engine = ScenarioEngine(store, run_id, plan, complete, log_path=folder / "calls.jsonl", generator=generator,
                                resolver=NoEscalation(key), budget=Budget(NO_LIMIT, NO_LIMIT), deepest=SCENARIO_NIGHT["past_depth"])
        last_day = find_day(seed.birth_date, plan.days[-1])
        reason = engine.run(until=last_day.id)
        print(f"Life written: {reason}, {len(plan.records)} decisions.", flush=True)
        write_diary(folder, store, run_id, plan, complete, engine)
    finally:
        store.close()


def find_day(birth, day):
    window = life_window(birth)
    moment = datetime.combine(day, scenario.CLASS_START)
    while window.level != "day":
        window = next(child for child in children(window, birth) if child.start <= moment < child.end)
    return window


def write_diary(folder, store, run_id, plan, complete, engine):
    path = folder / "diary.md"
    if path.exists():
        return
    lines = plan.history(len(plan.days))
    last = plan.records[-1] if plan.records else None
    user = "\n\n".join([f"WHO YOU ARE\n{engine.who(datetime.combine(plan.days[-1], scenario.CLASS_END))}", "YOUR MORNINGS\n" + "\n".join(lines),
                        f"HOW YOU FEEL NOW\n{last['feel_after']}" if last else ""])
    started = time.monotonic()
    result = complete(DIARY_SYSTEM, user, max_tokens=SCENARIO_NIGHT["diary_tokens"], temperature=SCENARIO_NIGHT["agent"]["temperature"], seed=7)
    log_call(folder / "calls.jsonl", "diary", None, 0, DIARY_SYSTEM, user, result, time.monotonic() - started, None)
    path.write_text(f"# Diary after {len(plan.days)} mornings\n\n{result.text.strip()}\n")


def phase_export(folder, state):
    """trajectory.jsonl in the spec's schema, with each decision's return to go, the schedule for audit, and a short summary."""
    store = Store(folder / "life.db")
    try:
        plan = Scenario(store, state["run_id"])
        rows = sorted(plan.records, key=lambda row: (row["morning"], row["decision"]))
        for row in rows:
            row["return_to_go"] = round(sum(other["reward"] for other in rows if other["morning"] == row["morning"] and other["decision"] >= row["decision"]), 4)
            node = store.node(state["run_id"], row["node_id"])
            row["world_wrote"] = node["closing"]["what_happened"] if node and node["closing"] else None
        (folder / "trajectory.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        (folder / "outcome_schedule.json").write_text(json.dumps({"seed": plan.seed_key, "rate_mode": RATE_MODE, "draws": plan.schedule}, indent=1))
        (folder / "summary.md").write_text(summary(rows, folder))
    finally:
        store.close()


def summary(rows, folder):
    free = [row for row in rows if row["phase"] == "consequential"]
    lines = [f"# Wellness center night: {len(rows)} decisions, {len(free)} chosen freely", ""]
    for role in ("safe", "rare_bad", "rare_good", "variance"):
        share = sum(row["role"] == role for row in free) / len(free) if free else 0
        lines.append(f"- {role}: {share:.0%} of free choices")
    rare = [row for row in rows if row["outcome"] == "rare"]
    lines += [f"- rare outcomes seen: {len(rare)} ({', '.join(f'{row['choice']} on day {row['day']}' for row in rare) or 'none'})",
              f"- fallbacks (no usable answer, chosen at random): {sum(row['fallback'] for row in rows)}"]
    try:
        calls = [json.loads(line) for line in (folder / "calls.jsonl").read_text().splitlines() if line.strip()]
        lines.append(f"- model calls: {len(calls)}, {sum(not call['ok'] for call in calls)} unusable")
    except OSError:
        pass
    return "\n".join(lines) + "\n"


def phase_clips(folder, state):
    """A short Cosmos clip of each decision moment, from what the world writer wrote there. Qwen is unloaded first."""
    if not SCENARIO_NIGHT["clips"]:
        return
    if not state.get("mock"):
        from kokopelli.wm import llm_model
        llm_model.unload()
    rows = [json.loads(line) for line in (folder / "trajectory.jsonl").read_text().splitlines() if line.strip()]
    clips = folder / "clips"
    clips.mkdir(exist_ok=True)
    # Each clip is its own Cosmos process, so there's nothing to unload between them, only room to wait for.
    guard = None if state.get("mock") else ram_share.Guard("scenario_cosmos", SCENARIO_NIGHT["cosmos_gb"], log=lambda line: print(line, flush=True))
    polite = Polite(None, guard, state.get("priority"))
    for row in rows:
        output = clips / f"m{row['day']:02d}_{row['decision']}.mp4"
        if output.exists():
            continue
        polite.check()
        if guard:
            guard.loaded = False  # the last clip's process has exited, so the next one needs room again
        prompt = f"{CLIP_SCENES[row['decision']]} {row.get('world_wrote') or row['narrative']} Morning light, {row['cosmetic']}, steady camera."
        started = time.monotonic()
        if state.get("mock"):
            output.write_bytes(b"")
        else:
            from kokopelli.wm.world_model import text_to_video
            settings = SCENARIO_NIGHT["clip"]
            text_to_video(prompt, output, size=settings["size"], frames=settings["frames"], steps=settings["steps"], seed=row["day"] * 10 + int(row["decision"][1]))
        print(f"{time.strftime('%H:%M:%S')} clip {output.name} {time.monotonic() - started:.0f}s", flush=True)


PHASES = (("calibrate", phase_calibrate), ("life", phase_life), ("export", phase_export), ("clips", phase_clips))


def work(folder):
    state = _load(folder)
    for name, phase in PHASES:
        if name in state["done"]:
            continue
        print(f"Starting {name}", flush=True)
        phase(folder, state)
        state["done"][name] = time.time()
        _save(folder, state)
        print(f"Finished {name}", flush=True)


def supervise(folder):
    """Run the work in a child process and restart it after a crash. The model can die in ways a try/except never sees."""
    crashes = 0
    with open(folder / "run.log", "a") as log:
        while True:
            child = subprocess.Popen([sys.executable, "-u", "-m", "kokopelli.life.scenario_night", "--worker", str(folder)],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
            for line in child.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            if child.wait() in (0, YIELDED):
                return child.returncode
            crashes += 1
            print(f"Worker exited with {child.returncode}. Crash {crashes} of {MAX_CRASHES}.", flush=True)
            if crashes >= MAX_CRASHES:
                return 1
            time.sleep(30)


def new_folder(mock=False, priority=None):
    folder = SCENARIO_OUT / f"{'mock-' if mock else ''}{datetime.now():%Y-%m-%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    _save(folder, {"mock": mock, "created": time.time(), "done": {}, "priority": priority})
    return folder


def about_text():
    guess = estimate()
    return (f"A new life written at {SCENARIO_NIGHT['past_depth']}s up to age 20, then {SCENARIO_NIGHT['mornings']} weekday mornings at the "
            f"wellness center where the agent runs late to class and decides 3 times each (lived arm). About {guess['qwen_calls']} Qwen calls "
            f"and {guess['clips']} Cosmos clips, roughly {guess['hours']} h. Gives its turn to any job with a lower priority number.")


def take_turns(folder, script=GPU_QUEUE_SCRIPT):
    """Queue one turn after another until the night is done. A turn ending with 75 gave way to another job, so queue again."""
    queue = SCENARIO_NIGHT["queue"]
    turn = 0
    while True:
        turn += 1
        print(f"{time.strftime('%H:%M:%S')} queuing turn {turn}", flush=True)
        code = subprocess.call([sys.executable, str(script), "run", "--name", queue["name"], "--priority", str(queue["priority"]),
                                "--max-hours", str(queue["max_hours"]), "--cwd", str(ROOT), "--about", about_text(),
                                "--output", str(Path(folder).resolve().relative_to(ROOT)), "--",
                                str(ROOT / ".venv" / "bin" / "python"), "-u", "-m", "kokopelli.life.scenario_night", "--run", str(folder)], cwd=ROOT)
        if code != YIELDED:
            print(f"{time.strftime('%H:%M:%S')} turn {turn} ended with {code}. {'Done.' if code == 0 else 'Stopping.'}", flush=True)
            return code
        print(f"{time.strftime('%H:%M:%S')} turn {turn} gave way. Queuing again in {REQUEUE_SECONDS} s.", flush=True)
        time.sleep(REQUEUE_SECONDS)


def estimate(config=SCENARIO_NIGHT):
    """Hours on the Mac, from the 12 s per Qwen call measured on 2026-11-03 and about 110 s per Cosmos clip."""
    birth = date.fromisoformat(config["seed"]["birth_date"])
    life = life_window(birth)
    past = 1
    for year in children(life, birth):
        if year.start.date() > date.fromisoformat(config["first_morning"]):
            break
        seasons = children(year, birth)
        past += 1 + (len(seasons) if config["past_depth"] != "year" else 0) + \
            (sum(len(children(season, birth)) for season in seasons) if config["past_depth"] == "month" else 0)
    per_morning = 115  # 24 hours, the path down to each decision and each decision's own moments, opened and closed
    calls = 2 * past + config["mornings"] * per_morning
    clips = 3 * config["mornings"] if config["clips"] else 0
    return {"qwen_calls": calls, "clips": clips, "hours": round((calls * 12 + clips * 110) / 3600, 1)}


def stage():
    """Write the job for the GPU queue page's Start button. Nothing runs until it's pressed."""
    queue = SCENARIO_NIGHT["queue"]
    folder = new_folder(priority=queue["priority"])
    job = {"name": queue["name"], "priority": queue["priority"], "max_hours": queue["max_hours"], "cwd": str(ROOT), "about": about_text(),
           "outputs": [str(folder.relative_to(ROOT))], "command": [str(ROOT / ".venv" / "bin" / "python"), "-u", "-m", "kokopelli.life.scenario_night", "--queued", str(folder)],
           # It queues its own turns, so Start runs the command as it is rather than wrapping it in one gpu.py ticket.
           "self_queued": True, "estimate": estimate(), "created_at": time.time()}
    STAGED_JOBS.mkdir(parents=True, exist_ok=True)
    path = STAGED_JOBS / f"{queue['name']}.json"
    if path.exists():
        raise SystemExit(f"{path} is already staged. Start it from the GPU queue page or delete it first.")
    path.write_text(json.dumps(job, indent=1))
    print(f"Staged {path}\nIt writes to {folder}\nEstimate: {job['estimate']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=["stage"])
    parser.add_argument("--run", help="run the night in this folder, resuming wherever it stopped")
    parser.add_argument("--queued", help="take turns in the GPU queue for the night in this folder until it's done")
    parser.add_argument("--mock", action="store_true", help="with --run and no folder given, rehearse with stand-in models in a new folder")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == "stage":
        return stage()
    if args.worker:
        try:
            work(Path(args.worker))
        except YieldTurn as waiting:
            print(f"Giving the GPU to {waiting}. Everything so far is saved; the next turn picks up here.", flush=True)
            raise SystemExit(YIELDED)
        except Exception:
            traceback.print_exc()
            raise SystemExit(1)
        return
    if args.queued:
        raise SystemExit(take_turns(Path(args.queued)))
    folder = Path(args.run) if args.run else new_folder(mock=True) if args.mock else None
    if folder is None:
        parser.error("give stage, --queued FOLDER, --run FOLDER, or --mock")
    print(f"Writing to {folder}", flush=True)
    raise SystemExit(supervise(folder))


if __name__ == "__main__":
    main()
