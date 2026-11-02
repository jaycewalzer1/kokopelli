"""Check a finished life database against the canon and the clock's invariants."""
import json

from .clock import MINUTES_PER_DAY, ROLLUP_LEVELS, format_t, from_t, to_t
from .engine import replay_chain
from .store import digests, read_strip
from .world import World


def verify_life(conn, world=None, deep=True):
    """Return (problems, facts). No problems means the life passed."""
    world = world or World()
    problems = []
    facts = {}
    life = world.life_id
    total = world.total_minutes

    row = conn.execute("SELECT complete, chain FROM checkpoint WHERE id=1").fetchone()
    if not row or not row[0]:
        return ["life is not complete"], facts

    problems += [f"canon: {p}" for p in world.validate()]

    by_level = {}
    for level in ROLLUP_LEVELS:
        rows = conn.execute(
            "SELECT key, start_t, end_t, parent_key, rollup FROM spans "
            "WHERE life_id=? AND level=? ORDER BY start_t", (life, level),
        ).fetchall()
        by_level[level] = rows
        facts[f"{level}_spans"] = len(rows)
        if not rows:
            problems.append(f"{level}: no spans")
            continue
        # Each level must cover the life exactly, with no gap or overlap.
        if rows[0][1] != world.birth_t:
            problems.append(f"{level}: starts at {format_t(rows[0][1])}, not at birth")
        if rows[-1][2] != world.death_t:
            problems.append(f"{level}: ends at {format_t(rows[-1][2])}, not at death")
        for a, b in zip(rows, rows[1:]):
            if a[2] != b[1]:
                problems.append(f"{level}: gap or overlap between {a[0]} and {b[0]}")
        # Each span's minutes must add up to its length.
        tally = {}
        for key, lo, hi, _, rollup in rows:
            counts = json.loads(rollup)
            if sum(counts.values()) != hi - lo:
                problems.append(f"{level} {key}: rollup {sum(counts.values())} != length {hi - lo}")
            for name, n in counts.items():
                tally[name] = tally.get(name, 0) + n
        by_level[level + "_tally"] = tally

    # Every level must report the same time use, activity by activity.
    reference = by_level.get("life_tally", {})
    facts["lived_minutes"] = sum(reference.values())
    if facts["lived_minutes"] != total:
        problems.append(f"life rollup is {facts['lived_minutes']} minutes, expected {total}")
    for level in ROLLUP_LEVELS:
        if by_level.get(level + "_tally") != reference:
            problems.append(f"{level}: rollup totals disagree with the life total")

    # These nest strictly. Week-in-month, winter-in-year, and year-in-segment don't.
    for inner, outer in (("day", "month"), ("month", "season")):
        spans = {r[0]: r for r in by_level[outer]}
        for key, lo, hi, parent, _ in by_level[inner]:
            p = spans.get(parent)
            if not p or lo < p[1] or hi > p[2]:
                problems.append(f"{inner} {key} is not inside {outer} {parent}")
    weeks = by_level["week"]
    w_idx = 0
    for key, lo, hi, _, _ in by_level["day"]:
        while weeks[w_idx][2] <= lo:
            w_idx += 1
        if lo < weeks[w_idx][1] or hi > weeks[w_idx][2]:
            problems.append(f"day {key} is not inside week {weeks[w_idx][0]}")

    # Strips: one per day, 1440 long, agreeing with the day's own rollup.
    activities = [a["id"] for a in world.activities]
    day_rollups = {r[0]: json.loads(r[4]) for r in by_level["day"]}
    strips = 0
    event_code = world.code["event"]
    stored = {}
    for key, blob in conn.execute(
        "SELECT day_key, strip FROM day_strips WHERE life_id=?", (life,)
    ):
        strip = read_strip(blob)
        stored[key] = strip
        strips += 1
        if len(strip) != MINUTES_PER_DAY:
            problems.append(f"strip {key} has length {len(strip)}")
        counts = {}
        for code in strip:
            if code:
                counts[activities[code]] = counts.get(activities[code], 0) + 1
        if counts != day_rollups.get(key):
            problems.append(f"strip {key} disagrees with its day rollup")
    facts["day_strips"] = strips
    if strips != len(by_level["day"]):
        problems.append(f"{strips} strips for {len(by_level['day'])} days")

    # Every canon event must be live at its exact minute, in the stored strip.
    for e in world.events:
        t = to_t(e["at"])
        strip = stored.get(from_t(t).date().isoformat())
        if strip is None or strip[t % MINUTES_PER_DAY] != event_code:
            problems.append(f"event {e['id']} is not at its minute {e['at']}")
    moment_events = conn.execute("SELECT COUNT(*) FROM moments WHERE life_id=?", (life,)).fetchone()[0]
    facts["moments"] = moment_events
    if moment_events != len(world.events):
        problems.append(f"{moment_events} moments for {len(world.events)} events")

    if deep:
        replayed = replay_chain(world)
        facts["replayed_chain"] = replayed
        if replayed != row[1]:
            problems.append("replaying the canon gave a different chain than the run")

    facts["digests"] = digests(conn)
    return problems, facts
