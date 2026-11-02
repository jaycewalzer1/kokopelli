"""Render the world story as Markdown, from authored canon plus stored rollups."""
import json

from .clock import to_t


def age_at(world, iso):
    return int(world.age_years(to_t(iso)))


def top_activities(world, rollup, n=3):
    labels = {a["id"]: a["label"] for a in world.activities}
    total = sum(rollup.values()) or 1
    ordered = sorted(rollup.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return ", ".join(f"{labels[k]} {100 * v / total:.0f}%" for k, v in ordered)


def render_story(world, conn=None):
    c = world.canon
    w = c["world"]
    lines = [
        f"# {w['name']}: the life of {world.life['id'].replace('-', ' ').title()}",
        "",
        w["premise"],
        "",
        f"**Life clock:** {world.life['birth']} to {world.life['death']}, "
        f"{world.total_minutes:,} minutes.",
        "",
        world.life["story"],
        "",
    ]
    years = {}
    if conn is not None:
        for key, payload, rollup in conn.execute(
            "SELECT key, payload, rollup FROM spans WHERE level='year' ORDER BY start_t"
        ):
            years[key] = (json.loads(payload), json.loads(rollup))

    plans_by_segment = {}
    for p in world.plans:
        plans_by_segment.setdefault(world.segment_at(to_t(p["formed"]))["id"], []).append(p)

    for seg in world.segments:
        lines += [
            f"## {seg['name']} ({seg['start'][:4]}-{seg['end'][:4]})",
            "",
            f"*{seg['developmental_task']}*",
            "",
            seg["summary"],
            "",
            f"**Statements** (voice: {seg['voice']})",
            "",
        ]
        lines += [f"- *{s['kind']}, from {s['from'][:10]}:* {s['text']}" for s in seg["statements"]]
        lines += [""]

        plans = plans_by_segment.get(seg["id"], [])
        lines += [f"**Plans formed** (horizon: {seg['planning_horizon_years']} years)", ""]
        if not plans:
            lines += ["- None. She cannot plan yet.", ""] if seg["planning_horizon_years"] == 0 \
                else ["- None formed in this segment.", ""]
        for p in plans:
            lines.append(
                f"- `{p['id']} v{p['version']}` formed {p['formed'][:10]} at age "
                f"{age_at(world, p['formed'])}, aimed at {p['target']}: {p['text']} "
                f"**Outcome: {p['outcome']}.**"
            )
            for m in p["milestones"]:
                if m["event"]:
                    hit = world.event_by_id[m["event"]]
                    lines.append(f"  - {m['text']}: due {m['due']}, done {hit['at'][:10]}")
                else:
                    lines.append(f"  - {m['text']}: due {m['due']}, never happened")
        if plans:
            lines.append("")

        events = world.events_between(*world.segment_bounds(seg))
        lines += ["**What happened**", ""]
        lines += [f"- **{e['at'][:10]}, {e['title'].rstrip('?')}{'?' if e['title'].endswith('?') else '.'}** {e['text']}"
                  for e in events]
        lines += [""]

        rows = [(k, v) for k, v in years.items() if v[0]["segment"] == seg["id"]]
        if rows:
            lines += ["| Year | Age | Theme | Time use |", "|---|---|---|---|"]
            for key, (payload, rollup) in rows:
                theme = payload["theme"].replace("|", "/")
                lines.append(
                    f"| {key} | {payload['age_at_start']} | {theme} | {top_activities(world, rollup)} |"
                )
            lines += [""]
    return "\n".join(lines)


def render_stack(stack):
    """Print one minute's full context, from life down to micro-action."""
    lines = [
        f"{stack['when']}  age {stack['life']['age_years']:.2f}  "
        f"({100 * stack['life']['fraction_lived']:.2f}% of the life)",
        f"  segment   {stack['segment']['name']}: {stack['segment']['task']}",
    ]
    for s in stack["statements_held"]:
        lines.append(f"  holds     ({s['kind']}) {s['text']}")
    if stack["plans_believed"]:
        for p in stack["plans_believed"]:
            lines.append(f"  plan      {p['id']} v{p['version']} (aimed at {p['target']}): {p['text']}")
    else:
        lines.append("  plan      (none held at this moment)")
    lines += [
        f"  year      {stack['year']['key']}: {stack['year']['theme']}",
        f"  season    {stack['season']['key']}: {stack['season']['focus']}",
        f"  month     {stack['month']['key']}: {stack['month']['motif']}",
        f"  week      {stack['week']['key']}: {stack['week']['rhythm']}",
    ]
    d = stack["day"]
    lines += [
        f"  day       {d['key']} {d['weekday']}, {d['kind']}, {d['role']}, at {d['residence']}; "
        f"{d['weather']['temp_c']}C, {d['weather']['sky']}",
        f"  hour      {stack['hour']['key']}: mostly {stack['hour']['dominant']} {stack['hour']['minutes']}",
    ]
    m = stack["minute"]
    suffix = f" [{m['event']}]" if m["event"] else ""
    lines.append(f"  minute    {stack['when'][-5:]}: {m['label']}, {m['micro']}{suffix}")
    return "\n".join(lines)
