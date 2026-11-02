"""Top-down expansion from the canon to any minute.

Every function here is pure in (canon, path). Randomness comes from hashing a
span's path instead of advancing a stream, which gives random access: day N can
be computed without days 0..N-1, and editing one event leaves other days alone.
"""
import bisect
import hashlib
import json
from pathlib import Path

from .clock import (
    MINUTES_PER_DAY, SEASON_BY_MONTH, date_to_t, format_t, from_t, level_bounds,
    level_key, to_t, week_key,
)

CANON_PATH = Path(__file__).resolve().parent.parent / "canon" / "world.json"
MASK64 = (1 << 64) - 1
MIX_A = 0x9E3779B97F4A7C15
MIX_B = 0xBF58476D1CE4E5B9
MICRO_HOLD_MINUTES = 3


def hhmm(text):
    return int(text[:2]) * 60 + int(text[3:])


class Lane:
    """A step function over time: the value in force at any minute."""

    def __init__(self, entries):
        self.starts = [to_t(e["from"]) for e in entries]
        self.values = [e["value"] for e in entries]

    def at(self, t):
        return self.values[max(bisect.bisect_right(self.starts, t) - 1, 0)]


class World:
    def __init__(self, path=CANON_PATH):
        raw = Path(path).read_bytes()
        self.canon = json.loads(raw)
        self.canon_sha256 = hashlib.sha256(raw).hexdigest()
        w = self.canon["world"]
        self.seed = w["seed"]
        self.life = self.canon["life"]
        self.life_id = self.life["id"]
        self.birth_t = to_t(self.life["birth"])
        self.death_t = to_t(self.life["death"])
        self.total_minutes = self.death_t - self.birth_t

        self.activities = self.canon["activities"]
        self.code = {a["id"]: i for i, a in enumerate(self.activities)}
        self.micro_lists = [a["micro"] for a in self.activities]
        self.micro_lens = [len(m) for m in self.micro_lists]

        self.roles = self.canon["roles"]
        self.role_lane = Lane(self.canon["lanes"]["role"])
        self.residence_lane = Lane(self.canon["lanes"]["residence"])
        self.household_lane = Lane(self.canon["lanes"]["household"])

        self.segments = self.canon["segments"]
        self.segment_starts = [to_t(s["start"]) for s in self.segments]
        self.segment_starts[0] = self.birth_t
        self.statements = {
            st["id"]: {**st, "segment": seg["id"]}
            for seg in self.segments for st in seg["statements"]
        }

        self.events = sorted(self.canon["events"], key=lambda e: to_t(e["at"]))
        self.event_by_id = {e["id"]: e for e in self.events}
        self.events_by_day = {}
        for e in self.events:
            start = to_t(e["at"])
            end = min(start + e["minutes"], self.death_t)
            day = start // MINUTES_PER_DAY
            while day * MINUTES_PER_DAY < end:
                self.events_by_day.setdefault(day, []).append((start, end, e["id"]))
                day += 1

        self.plans = self.canon["plans"]
        rhythms = w["week_rhythms"]
        self.rhythm_by_id = {r["id"]: r for r in rhythms}
        self.rhythm_ladder = [r["id"] for r in rhythms for _ in range(r["weight"])]
        self.holidays = set(w["holidays"])
        self.schedules = {}

    # Addressing ----------------------------------------------------------

    def rng(self, path):
        digest = hashlib.blake2b(f"{self.seed}/{path}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big")

    def choice(self, path, items):
        return items[self.rng(path) % len(items)]

    def clip(self, lo, hi):
        return max(lo, self.birth_t), min(hi, self.death_t)

    def first_day(self):
        return self.birth_t // MINUTES_PER_DAY

    def last_day(self):
        return (self.death_t - 1) // MINUTES_PER_DAY

    def date_of(self, day_index):
        return from_t(day_index * MINUTES_PER_DAY).date()

    def age_years(self, t):
        return (t - self.birth_t) / (MINUTES_PER_DAY * 365.2425)

    # Narrative levels ----------------------------------------------------

    def segment_at(self, t):
        return self.segments[max(bisect.bisect_right(self.segment_starts, t) - 1, 0)]

    def segment_bounds(self, seg):
        idx = self.segments.index(seg)
        hi = self.segment_starts[idx + 1] if idx + 1 < len(self.segments) else self.death_t
        return self.segment_starts[idx], hi

    def segment_payload(self, seg):
        return {
            "name": seg["name"],
            "voice": seg["voice"],
            "developmental_task": seg["developmental_task"],
            "planning_horizon_years": seg["planning_horizon_years"],
            "summary": seg["summary"],
            "statements": [s["id"] for s in seg["statements"]],
        }

    def statements_held_at(self, t):
        """What she holds to be true at minute t. Never includes her future."""
        return [
            s for s in self.statements.values()
            if to_t(s["from"]) <= t and (s["until"] is None or t < to_t(s["until"]))
        ]

    def plans_believed_at(self, t):
        """What she was planning at minute t, as she understood it then."""
        return [p for p in self.plans if to_t(p["formed"]) <= t < to_t(p["ended"])]

    def events_between(self, lo, hi):
        return [e for e in self.events if lo <= to_t(e["at"]) < hi]

    # Calendar levels -----------------------------------------------------

    def year_payload(self, key, lo, hi):
        events = sorted(self.events_between(lo, hi), key=lambda e: -e["significance"])
        plans = self.plans_believed_at(lo)
        seg = self.segment_at(lo)
        if events:
            theme = events[0]["title"]
        elif plans:
            theme = "Working on: " + plans[0]["text"]
        else:
            theme = seg["developmental_task"]
        return {
            "theme": theme,
            "age_at_start": int(self.age_years(lo)),
            "segment": seg["id"],
            "active_plans": [f'{p["id"]}#v{p["version"]}' for p in plans],
            "events": [e["id"] for e in events],
        }

    def season_payload(self, key, lo, hi):
        name = key.split("-")[1]
        role = self.role_lane.at(lo)
        return {
            "season": name,
            "role": role,
            "focus": self.roles[role]["season_focus"][name],
            "events": [e["id"] for e in self.events_between(lo, hi)],
        }

    def month_payload(self, key, lo, hi):
        mm = key[5:7]
        due = [
            {"plan": f'{p["id"]}#v{p["version"]}', "milestone": m["text"]}
            for p in self.plans for m in p["milestones"]
            if m["due"][:7] == key
        ]
        return {
            "motif": self.canon["world"]["month_motif"][mm],
            "residence": self.residence_lane.at(lo),
            "milestones_due": due,
            "events": [e["id"] for e in self.events_between(lo, hi)],
        }

    def week_rhythm(self, key):
        return self.choice(f"week/{key}/rhythm", self.rhythm_ladder)

    def week_payload(self, key, lo, hi):
        rhythm = self.week_rhythm(key)
        return {
            "rhythm": rhythm,
            "events": [e["id"] for e in self.events_between(lo, hi)],
        }

    def weather(self, d):
        c = self.canon["world"]["climate"][f"{d.month:02d}"]
        key = d.isoformat()
        delta = self.rng(f"day/{key}/temp") % (2 * c["spread"] + 1) - c["spread"]
        return {"temp_c": c["mean_c"] + delta, "sky": self.choice(f"day/{key}/sky", c["skies"])}

    def compile_schedule(self, entries):
        key = id(entries)
        compiled = self.schedules.get(key)
        if compiled is None:
            compiled = [(hhmm(s), self.code[a]) for s, a in entries]
            self.schedules[key] = compiled
        return compiled

    def day_plan(self, d):
        """Classify a day and choose its schedule."""
        t = date_to_t(d)
        key = d.isoformat()
        role_id = self.role_lane.at(t)
        role = self.roles[role_id]
        rhythm_id = self.week_rhythm(week_key(d))
        rhythm = self.rhythm_by_id[rhythm_id]
        working = (
            d.weekday() in role["workdays"]
            and d.strftime("%m-%d") not in self.holidays
            and d.month not in role.get("off_months", ())
        )
        sick = self.rng(f"day/{key}/sick") % 1000 < rhythm["sick_p"] * 1000
        if sick:
            kind, schedule = "sick", self.canon["sick_day"]
        elif working and d.month in role.get("field_months", ()):
            kind, schedule = "field", role["field_workday"]
        elif working:
            kind, schedule = "workday", role["workday"]
        else:
            kind, schedule = "restday", role["restday"]
        return role_id, role, rhythm_id, rhythm, kind, schedule

    def day(self, day_index):
        """Return (payload, strip): a day's description and 1440 activity codes."""
        d = self.date_of(day_index)
        key = d.isoformat()
        role_id, role, rhythm_id, rhythm, kind, schedule = self.day_plan(d)
        strip = bytearray(MINUTES_PER_DAY)

        compiled = self.compile_schedule(schedule)
        boundaries = []
        for i, (minute, code) in enumerate(compiled):
            jitter = 0 if i == 0 else self.rng(f"day/{key}/sched/{i}") % 21 - 10
            boundaries.append((max(minute + jitter, 0), code))
        for i, (minute, code) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else MINUTES_PER_DAY
            if end > minute:
                strip[minute:end] = bytes([code]) * (end - minute)

        overlay = rhythm["overlay"]
        applies = overlay and role["overlay_ok"] and (
            overlay["day"] == kind or (overlay["day"] == "workday" and kind == "field")
        )
        if applies:
            lo, hi = hhmm(overlay["from"]), hhmm(overlay["to"])
            strip[lo:hi] = bytes([self.code[overlay["activity"]]]) * (hi - lo)

        day_t = day_index * MINUTES_PER_DAY
        event_ids = []
        event_code = self.code["event"]
        for start, end, event_id in self.events_by_day.get(day_index, ()):
            lo, hi = max(start - day_t, 0), min(end - day_t, MINUTES_PER_DAY)
            strip[lo:hi] = bytes([event_code]) * (hi - lo)
            event_ids.append(event_id)

        # Minutes outside the life stay code 0, "unlived".
        if day_t < self.birth_t:
            strip[:self.birth_t - day_t] = bytes(self.birth_t - day_t)
        if day_t + MINUTES_PER_DAY > self.death_t:
            cut = self.death_t - day_t
            strip[cut:] = bytes(MINUTES_PER_DAY - cut)

        payload = {
            "kind": kind,
            "weekday": d.strftime("%A"),
            "role": role_id,
            "rhythm": rhythm_id,
            "week": week_key(d),
            "residence": self.residence_lane.at(day_t),
            "household": self.household_lane.at(day_t),
            "weather": self.weather(d),
            "events": event_ids,
        }
        return payload, strip

    # Minute level --------------------------------------------------------

    def micro_index(self, t, code):
        x = (self.seed ^ ((t // MICRO_HOLD_MINUTES) * MIX_A)) & MASK64
        x = ((x ^ (x >> 30)) * MIX_B) & MASK64
        return (x >> 40) % self.micro_lens[code]

    def at(self, t):
        """Read the whole stack at one minute, from life down to micro-action."""
        if not self.birth_t <= t < self.death_t:
            raise ValueError(f"{format_t(t)} is outside the life")
        d = from_t(t).date()
        day_index = t // MINUTES_PER_DAY
        payload, strip = self.day(day_index)
        minute = t - day_index * MINUTES_PER_DAY
        hour = minute // 60
        hour_codes = strip[hour * 60:(hour + 1) * 60]
        tally = {}
        for code in hour_codes:
            if code:
                tally[code] = tally.get(code, 0) + 1
        dominant = max(sorted(tally), key=tally.get)
        code = strip[minute]
        seg = self.segment_at(t)
        levels = {}
        for level, make in (
            ("year", self.year_payload), ("season", self.season_payload),
            ("month", self.month_payload), ("week", self.week_payload),
        ):
            key = level_key(level, d)
            lo, hi = self.clip(*level_bounds(level, d))
            levels[level] = {"key": key, **make(key, lo, hi)}
        event = next(
            (self.event_by_id[eid] for lo, hi, eid in self.events_by_day.get(day_index, ())
             if lo <= t < hi), None,
        )
        return {
            "t": t,
            "when": format_t(t),
            "life": {
                "id": self.life_id,
                "age_years": round(self.age_years(t), 3),
                "fraction_lived": round((t - self.birth_t) / self.total_minutes, 6),
            },
            "segment": {"id": seg["id"], "name": seg["name"], "task": seg["developmental_task"]},
            "statements_held": [
                {"id": s["id"], "kind": s["kind"], "text": s["text"]}
                for s in self.statements_held_at(t)
            ],
            "plans_believed": [
                {"id": p["id"], "version": p["version"], "text": p["text"], "target": p["target"]}
                for p in self.plans_believed_at(t)
            ],
            **levels,
            "day": {"key": d.isoformat(), **payload},
            "hour": {
                "key": f"{d.isoformat()}T{hour:02d}",
                "dominant": self.activities[dominant]["id"],
                "minutes": {self.activities[c]["id"]: n for c, n in sorted(tally.items())},
            },
            "minute": {
                "activity": self.activities[code]["id"],
                "label": self.activities[code]["label"],
                "micro": self.micro_lists[code][self.micro_index(t, code)],
                "event": event["title"] if event else None,
            },
        }

    # Canon validation ----------------------------------------------------

    def validate(self):
        """Return a list of problems in the canon. Empty means it holds together."""
        problems = []
        ids = {a["id"] for a in self.activities}
        if self.activities[0]["id"] != "unlived":
            problems.append("activity code 0 must be 'unlived'")

        segs = self.segments
        if segs[0]["start"] != self.life["birth"][:10]:
            problems.append("first segment must start on the birth date")
        if segs[-1]["end"] != self.life["death"][:10]:
            problems.append("last segment must end on the death date")
        for a, b in zip(segs, segs[1:]):
            if a["end"] != b["start"]:
                problems.append(f"gap between segments {a['id']} and {b['id']}")

        for name, entries in self.canon["lanes"].items():
            starts = [e["from"] for e in entries]
            if starts != sorted(starts):
                problems.append(f"lane {name} is out of order")
            if starts[0] != self.life["birth"][:10]:
                problems.append(f"lane {name} must start at birth")

        for role_id, role in self.roles.items():
            if set(role["season_focus"]) != set(SEASON_BY_MONTH.values()):
                problems.append(f"role {role_id} must describe all four seasons")
            for field, value in role.items():
                if field in ("restday", "workday", "field_workday"):
                    for _, activity in value:
                        if activity not in ids:
                            problems.append(f"role {role_id}: unknown activity {activity}")
                    minutes = [hhmm(s) for s, _ in value]
                    if minutes[0] != 0 or minutes != sorted(minutes):
                        problems.append(f"role {role_id}.{field}: schedule must start at 00:00 and ascend")
            if role["workdays"] and "workday" not in role:
                problems.append(f"role {role_id} has workdays but no workday schedule")
            if role.get("field_months") and "field_workday" not in role:
                problems.append(f"role {role_id} has field months but no field schedule")
        for value in self.canon["lanes"]["role"]:
            if value["value"] not in self.roles:
                problems.append(f"unknown role {value['value']}")

        for e in self.events:
            t = to_t(e["at"])
            if not self.birth_t <= t < self.death_t:
                problems.append(f"event {e['id']} falls outside the life")

        for s in self.statements.values():
            lo = to_t(s["from"])
            hi = self.death_t if s["until"] is None else to_t(s["until"])
            if not self.birth_t <= lo < hi <= self.death_t:
                problems.append(f"statement {s['id']}: held interval is outside the life or empty")

        seen = {}
        for p in self.plans:
            label = f'{p["id"]}#v{p["version"]}'
            if p["statement"] not in self.statements:
                problems.append(f"{label}: unknown statement {p['statement']}")
            formed, ended = to_t(p["formed"]), to_t(p["ended"])
            statement = self.statements.get(p["statement"])
            if statement:
                lo = to_t(statement["from"])
                hi = self.death_t if statement["until"] is None else to_t(statement["until"])
                if not lo <= formed < hi:
                    problems.append(f"{label}: formed while its statement was not held")
            if not self.birth_t <= formed < ended <= self.death_t:
                problems.append(f"{label}: belief interval is outside the life or empty")
            seg = self.segment_at(formed)
            horizon_days = (to_t(p["target"]) - formed) / MINUTES_PER_DAY
            if horizon_days > seg["planning_horizon_years"] * 366:
                problems.append(f"{label}: target is beyond the {seg['id']} planning horizon")
            if p["outcome"] not in ("achieved", "revised", "blocked", "abandoned"):
                problems.append(f"{label}: unknown outcome {p['outcome']}")
            for m in p["milestones"]:
                if m["event"] is None:
                    continue
                if m["event"] not in self.event_by_id:
                    problems.append(f"{label}: unknown event {m['event']}")
                elif not formed <= to_t(self.event_by_id[m["event"]]["at"]) <= ended:
                    problems.append(f"{label}: milestone event {m['event']} is outside the plan's life")
            prior = seen.get(p["id"])
            if prior is not None:
                if p["version"] != prior["version"] + 1:
                    problems.append(f"{label}: versions must be consecutive")
                if p["formed"] != prior["ended"]:
                    problems.append(f"{label}: must start when v{prior['version']} ended")
                if prior["outcome"] != "revised":
                    problems.append(f"{label}: prior version must end as revised")
            seen[p["id"]] = p
        return problems

