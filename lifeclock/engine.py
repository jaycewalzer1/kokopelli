"""Tick the clock across a life, one minute at a time.

Sim output is a pure function of the canon. Wall time decides only when a day
gets processed and is recorded separately, so a paced run, an unpaced run, and
a killed-and-resumed run must all finish with identical digests.
"""
import hashlib
import json
import random
import time
import zlib

from .clock import MINUTES_PER_DAY, format_t, level_bounds, level_key
from .store import connect, dumps, load_canon, read_strip
from .world import MASK64, MICRO_HOLD_MINUTES, MIX_A, MIX_B

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
COMMIT_EVERY_DAYS = 7
GENESIS = "0" * 64
AUDIT_MIN_SECONDS = 0.0005


def tick_day(world, day_index, strip):
    """Advance through each lived minute of one day.

    Inlined because it runs about 43 million times per life. The micro-action
    formula must stay identical to World.micro_index, which a test enforces.
    """
    base = day_index * MINUTES_PER_DAY
    lo = max(world.birth_t - base, 0)
    hi = min(world.death_t - base, MINUTES_PER_DAY)
    seed, lens = world.seed, world.micro_lens
    counts = {}
    h = FNV_OFFSET
    for m in range(lo, hi):
        code = strip[m]
        x = (seed ^ (((base + m) // MICRO_HOLD_MINUTES) * MIX_A)) & MASK64
        x = ((x ^ (x >> 30)) * MIX_B) & MASK64
        micro = (x >> 40) % lens[code]
        h = ((h ^ ((code << 8) | micro)) * FNV_PRIME) & MASK64
        counts[code] = counts.get(code, 0) + 1
    return counts, h, hi - lo


def named_counts(world, counts):
    return {world.activities[code]["id"]: n for code, n in sorted(counts.items())}


def merge(into, counts):
    for key, n in counts.items():
        into[key] = into.get(key, 0) + n


class LifeRun:
    def __init__(self, world, db_path):
        self.world = world
        self.conn = connect(db_path)
        self.open = {}
        self.chain = GENESIS
        self.next_day = world.first_day()
        self.complete = False
        # Audits only read, so their picks need not match between runs.
        self.auditor = random.Random()
        self.audits = 0
        self.audit_failures = 0
        self._restore()
        self.audits = int(self._info("audits") or 0)
        self.audit_failures = int(self._info("audit_failures") or 0)

    def _restore(self):
        w = self.world
        row = self.conn.execute("SELECT value FROM meta WHERE key='canon_sha256'").fetchone()
        if row and row[0] != w.canon_sha256:
            raise SystemExit("This database was built from a different canon; refusing to resume.")
        ck = self.conn.execute(
            "SELECT next_day, chain, open, complete FROM checkpoint WHERE id=1"
        ).fetchone()
        if ck:
            self.next_day, self.chain = ck[0], ck[1]
            self.open = json.loads(ck[2])
            self.complete = bool(ck[3])
        else:
            with self.conn:
                load_canon(self.conn, w)

    def _parent_of(self, level, lo):
        w = self.world
        d = w.date_of(lo // MINUTES_PER_DAY)
        if level == "segment":
            return w.life_id
        if level == "year":
            return w.segment_at(lo)["id"]
        if level == "season":
            return level_key("year", d)
        if level == "month":
            return level_key("season", d)
        return None  # A week crosses months and years, so it has no single parent.

    def _spans_for(self, day_index):
        """The (key, lo, hi) of the span at each rollup level for one day."""
        w = self.world
        t = max(day_index * MINUTES_PER_DAY, w.birth_t)
        d = w.date_of(day_index)
        seg = w.segment_at(t)
        out = {
            "life": (w.life_id, w.birth_t, w.death_t),
            "segment": (seg["id"], *w.segment_bounds(seg)),
        }
        for level in ("year", "season", "month", "week"):
            out[level] = (level_key(level, d), *w.clip(*level_bounds(level, d)))
        return out

    def _payload(self, level, key, lo, hi):
        w = self.world
        if level == "life":
            return {"story": w.life["story"], "person": w.life["person"]}
        if level == "segment":
            return w.segment_payload(next(s for s in w.segments if s["id"] == key))
        return {
            "year": w.year_payload, "season": w.season_payload,
            "month": w.month_payload, "week": w.week_payload,
        }[level](key, lo, hi)

    def _write_span(self, level, key, lo, hi, parent, payload, rollup):
        self.conn.execute(
            "INSERT INTO spans VALUES (?,?,?,?,?,?,?,?)",
            (self.world.life_id, level, key, lo, hi, parent, dumps(payload), dumps(rollup)),
        )

    def _close(self, level):
        s = self.open.pop(level)
        payload = self._payload(level, s["key"], s["lo"], s["hi"])
        self._write_span(level, s["key"], s["lo"], s["hi"],
                         self._parent_of(level, s["lo"]), payload, s["rollup"])

    def _save_checkpoint(self):
        self.conn.execute(
            "INSERT OR REPLACE INTO checkpoint VALUES (1, ?, ?, ?, ?)",
            (self.next_day, self.chain, dumps(self.open), int(self.complete)),
        )

    def step_day(self, day_index):
        w = self.world
        for level, (key, lo, hi) in self._spans_for(day_index).items():
            cur = self.open.get(level)
            if cur and cur["key"] != key:
                self._close(level)
                cur = None
            if not cur:
                self.open[level] = {"key": key, "lo": lo, "hi": hi, "rollup": {}}

        payload, strip = w.day(day_index)
        counts, minute_hash, lived = tick_day(w, day_index, strip)
        rollup = named_counts(w, counts)
        for level_state in self.open.values():
            merge(level_state["rollup"], rollup)

        d = w.date_of(day_index)
        day_key = d.isoformat()
        base = day_index * MINUTES_PER_DAY
        lo, hi = w.clip(base, base + MINUTES_PER_DAY)
        life = w.life_id
        self._write_span("day", day_key, lo, hi, level_key("month", d), payload, rollup)
        self.conn.execute(
            "INSERT INTO day_strips VALUES (?,?,?)",
            (life, day_key, zlib.compress(bytes(strip), 6)),
        )
        for event_start, _, event_id in w.events_by_day.get(day_index, ()):
            if event_start // MINUTES_PER_DAY == day_index:
                e = w.event_by_id[event_id]
                self.conn.execute(
                    "INSERT INTO moments VALUES (?,?,?,?,?)",
                    (life, event_start, "event", "canon",
                     dumps({"event": event_id, "title": e["title"], "text": e["text"]})),
                )

        step = hashlib.sha256()
        step.update(self.chain.encode())
        step.update(minute_hash.to_bytes(8, "big"))
        step.update(bytes(strip))
        step.update(dumps(payload).encode())
        self.chain = step.hexdigest()
        self.next_day = day_index + 1
        return lived

    def finish(self):
        for level in ("week", "month", "season", "year", "segment", "life"):
            if level in self.open:
                self._close(level)
        self.complete = True

    def run(self, wall_seconds=None, stop_before_day=None, heartbeat_seconds=30.0, log=None):
        """Run to completion, or to stop_before_day. Returns (chain, complete)."""
        w = self.world
        log = log or (lambda text: print(text, flush=True))
        if self.complete:
            log("Life already complete.")
            return self.chain, True
        total = w.total_minutes
        started = self._wall_start()
        last = w.last_day()
        last_beat = time.time()
        pending = 0
        peak_lag = float(self._info("peak_lag_seconds") or 0.0)
        for day_index in range(self.next_day, last + 1):
            if stop_before_day is not None and day_index >= stop_before_day:
                break
            self.step_day(day_index)
            pending += 1
            done_t = min((day_index + 1) * MINUTES_PER_DAY, w.death_t)
            lag = 0.0
            if wall_seconds:
                target = started + wall_seconds * (done_t - w.birth_t) / total
                now = time.time()
                if now < target:
                    self._audit_until(target, done_t)
                else:
                    lag = now - target
                    peak_lag = max(peak_lag, lag)
            now = time.time()
            beat = now - last_beat >= heartbeat_seconds
            if pending >= COMMIT_EVERY_DAYS or beat:
                self._save_checkpoint()
                if beat:
                    self.conn.execute(
                        "INSERT INTO telemetry VALUES (?,?,?)", (now - started, done_t, lag))
                    self._set_info("peak_lag_seconds", peak_lag)
                    self._set_info("audits", self.audits)
                    self._set_info("audit_failures", self.audit_failures)
                    self._beat(now - started, done_t, lag, log)
                    last_beat = now
                self.conn.commit()
                pending = 0
        if self.next_day > last:
            self.finish()
            log(f"Life complete after {time.time() - started:.1f}s of wall time.")
        self._save_checkpoint()
        self._set_info("peak_lag_seconds", peak_lag)
        self._set_info("audits", self.audits)
        self._set_info("audit_failures", self.audit_failures)
        self._set_info("wall_finished", time.time())
        self.conn.commit()
        return self.chain, self.complete

    def _audit_until(self, deadline, upto_t):
        """Fill idle time by checking lived minutes against random access."""
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            if remaining < AUDIT_MIN_SECONDS:
                time.sleep(remaining)
                return
            self._audit_once(upto_t)

    def _audit_once(self, upto_t):
        w = self.world
        t = self.auditor.randrange(w.birth_t, upto_t)
        stack = w.at(t)
        row = self.conn.execute(
            "SELECT strip FROM day_strips WHERE life_id=? AND day_key=?",
            (w.life_id, stack["day"]["key"]),
        ).fetchone()
        span = self.conn.execute(
            "SELECT payload FROM spans WHERE life_id=? AND level='day' AND key=?",
            (w.life_id, stack["day"]["key"]),
        ).fetchone()
        self.audits += 1
        if row is None or span is None:
            self.audit_failures += 1
            return
        code = read_strip(row[0])[t % MINUTES_PER_DAY]
        day = {k: v for k, v in stack["day"].items() if k != "key"}
        if w.activities[code]["id"] != stack["minute"]["activity"] or json.loads(span[0]) != day:
            self.audit_failures += 1

    def _beat(self, elapsed, t, lag, log):
        w = self.world
        seg = w.segment_at(t - 1)["name"]
        pct = 100 * (t - w.birth_t) / w.total_minutes
        log(f"[wall {elapsed:7.1f}s] {format_t(t - 1)} age {w.age_years(t - 1):5.1f} "
            f"{pct:5.1f}% {seg:<18} lag {lag:5.2f}s audits {self.audits:,} failed {self.audit_failures}")

    def _info(self, key):
        row = self.conn.execute("SELECT value FROM run_info WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_info(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO run_info VALUES (?, ?)", (key, str(value)))

    def _wall_start(self):
        # Kept across a resume, so downtime from a kill is caught up, not added.
        value = self._info("wall_started")
        if value is None:
            value = time.time()
            self._set_info("wall_started", value)
            self.conn.commit()
        return float(value)


def replay_chain(world):
    """Rebuild the chain from the canon alone, touching no database."""
    chain = GENESIS
    for day_index in range(world.first_day(), world.last_day() + 1):
        payload, strip = world.day(day_index)
        _, minute_hash, _ = tick_day(world, day_index, strip)
        step = hashlib.sha256()
        step.update(chain.encode())
        step.update(minute_hash.to_bytes(8, "big"))
        step.update(bytes(strip))
        step.update(dumps(payload).encode())
        chain = step.hexdigest()
    return chain

