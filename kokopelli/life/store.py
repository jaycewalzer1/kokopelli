"""SQLite storage. There is no update or delete anywhere: a closing is a new row, and state is a replay of the log."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from kokopelli.life.seed import PublicSeed
from kokopelli.life.windows import LEVELS, age_at, children, depth, find, life_window

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id    INTEGER PRIMARY KEY,
    seed      TEXT NOT NULL,
    rng_key   TEXT NOT NULL,
    fork_of   INTEGER,
    fork_node TEXT,
    fork_cut  INTEGER
);
-- Apart from the seed so that loading a seed cannot bring the target along.
CREATE TABLE IF NOT EXISTS hidden_targets (
    run_id INTEGER PRIMARY KEY,
    target TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS openings (
    run_id      INTEGER NOT NULL,
    node_id     TEXT NOT NULL,
    parent_id   TEXT,
    idx         INTEGER NOT NULL,
    level       TEXT NOT NULL,
    label       TEXT NOT NULL,
    start_t     TEXT NOT NULL,
    end_t       TEXT NOT NULL,
    age         REAL NOT NULL,
    salience    REAL NOT NULL,
    depth_limit TEXT NOT NULL,
    opening     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    PRIMARY KEY (run_id, node_id)
);
CREATE INDEX IF NOT EXISTS openings_by_seq ON openings (run_id, seq);
CREATE INDEX IF NOT EXISTS openings_by_parent ON openings (run_id, parent_id);
CREATE INDEX IF NOT EXISTS openings_by_level ON openings (run_id, level, start_t);
CREATE TABLE IF NOT EXISTS closings (
    run_id  INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    closing TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    PRIMARY KEY (run_id, node_id)
);
CREATE INDEX IF NOT EXISTS closings_by_seq ON closings (run_id, seq);
CREATE TABLE IF NOT EXISTS events (
    run_id  INTEGER NOT NULL,
    seq     INTEGER NOT NULL,
    node_id TEXT,
    t       TEXT NOT NULL,
    kind    TEXT NOT NULL,
    data    TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS events_by_node ON events (run_id, node_id);
CREATE INDEX IF NOT EXISTS events_by_time ON events (run_id, t);
"""
TABLES = ("runs", "hidden_targets", "openings", "closings", "events")
GUARDS = "".join(
    f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{verb} BEFORE {verb} ON {table}
        BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"""
    for table in TABLES for verb in ("UPDATE", "DELETE"))

OPENING_KEYS = {"setting", "exogenous", "pressures", "open_questions"}
CLOSING_KEYS = {"summary", "what_happened", "pressures", "choices"}
OUTCOMES = {"met", "avoided", "didnt_arise"}


class WriteOnceError(Exception):
    """A second opening or closing for the same node."""


class OrderError(Exception):
    """A node opened or closed before the tree allows it."""


class InvalidNodeError(Exception):
    """An opening or closing that breaks the rules for its contents."""


def validate_opening(opening):
    if set(opening) != OPENING_KEYS:
        raise InvalidNodeError(f"an opening has exactly {sorted(OPENING_KEYS)}, got {sorted(opening)}")
    for pressure in opening["pressures"]:
        if set(pressure) != {"id", "text", "odds"} or not 0 <= pressure["odds"] <= 1:
            raise InvalidNodeError(f"a pressure needs an id, text, and odds from 0 to 1: {pressure}")


def validate_closing(closing, opening):
    if set(closing) != CLOSING_KEYS:
        raise InvalidNodeError(f"a closing has exactly {sorted(CLOSING_KEYS)}, got {sorted(closing)}")
    resolved = {pressure["id"]: pressure["outcome"] for pressure in closing["pressures"]}
    if set(resolved) != {pressure["id"] for pressure in opening["pressures"]}:
        raise InvalidNodeError("a closing must resolve each pressure in its opening, and no others")
    if not set(resolved.values()) <= OUTCOMES:
        raise InvalidNodeError(f"a pressure outcome is one of {sorted(OUTCOMES)}")


def empty_state():
    return {"place": None, "people": {}, "money": 0, "skills": {}}


def apply_event(state, kind, data):
    """Fold one log event into the state. Other kinds, like choices, don't change state."""
    if kind == "moved":
        state["place"] = data["place"]
    elif kind == "person_met":
        state["people"][data["name"]] = {"relationship": data["relationship"], "closeness": data.get("closeness", 0.5)}
    elif kind == "relationship_changed":
        state["people"][data["name"]]["closeness"] = round(state["people"][data["name"]]["closeness"] + data["delta"], 3)
    elif kind == "money_changed":
        state["money"] += data["delta"]
    elif kind == "skill_changed":
        state["skills"][data["skill"]] = round(state["skills"].get(data["skill"], 0) + data["delta"], 3)
    return state


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Without this, INSERT OR REPLACE deletes the old row without firing the delete guard.
        self.conn.execute("PRAGMA recursive_triggers=ON")
        self.conn.executescript(SCHEMA + GUARDS)
        self._seeds = {}

    def close(self):
        self.conn.close()

    @contextmanager
    def atomic(self):
        """Everything inside is written together or not at all. Nested uses join the outer one."""
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def _next_seq(self, run_id):
        row = self.conn.execute(
            """SELECT MAX(m) FROM (SELECT MAX(seq) m FROM openings WHERE run_id = :r
               UNION ALL SELECT MAX(seq) FROM closings WHERE run_id = :r
               UNION ALL SELECT MAX(seq) FROM events WHERE run_id = :r)""", {"r": run_id}).fetchone()
        return (row[0] or 0) + 1

    def last_seq(self, run_id):
        return self._next_seq(run_id) - 1

    def create_run(self, seed):
        with self.atomic():
            run_id = self.conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM runs").fetchone()[0]
            public = seed.public()
            self.conn.execute("INSERT INTO runs (run_id, seed, rng_key) VALUES (?, ?, ?)",
                              (run_id, json.dumps(public.to_dict()), str(seed.rng_seed)))
            if seed.hidden_target is not None:
                self.conn.execute("INSERT INTO hidden_targets VALUES (?, ?)", (run_id, seed.hidden_target))
            start = life_window(seed.birth_date).start
            if seed.place:
                self.append_event(run_id, None, start, "moved", {"place": seed.place})
            for person in seed.family:
                self.append_event(run_id, None, start, "person_met", person)
        return run_id

    def runs(self):
        return [dict(row) for row in self.conn.execute("SELECT run_id, seed, fork_of, fork_node FROM runs ORDER BY run_id")]

    def public_seed(self, run_id):
        if run_id not in self._seeds:
            row = self.conn.execute("SELECT seed FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"no run {run_id}")
            self._seeds[run_id] = PublicSeed.from_dict(json.loads(row["seed"]))
        return self._seeds[run_id]

    def rng_key(self, run_id):
        return self.conn.execute("SELECT rng_key FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    def node(self, run_id, node_id):
        row = self.conn.execute(
            """SELECT o.*, c.closing, c.seq AS closed_seq FROM openings o
               LEFT JOIN closings c ON c.run_id = o.run_id AND c.node_id = o.node_id
               WHERE o.run_id = ? AND o.node_id = ?""", (run_id, node_id)).fetchone()
        return self._decode(row) if row else None

    def child_nodes(self, run_id, parent_id):
        rows = self.conn.execute(
            """SELECT o.*, c.closing, c.seq AS closed_seq FROM openings o
               LEFT JOIN closings c ON c.run_id = o.run_id AND c.node_id = o.node_id
               WHERE o.run_id = ? AND o.parent_id IS ?""", (run_id, parent_id))
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row):
        node = dict(row)
        node["opening"] = json.loads(node["opening"])
        node["closing"] = json.loads(node["closing"]) if node["closing"] else None
        return node

    def closed_before(self, run_id, level, moment, limit):
        """The latest finished nodes at this level that ended by this moment, newest first."""
        rows = self.conn.execute(
            """SELECT o.*, c.closing, c.seq AS closed_seq FROM openings o
               JOIN closings c ON c.run_id = o.run_id AND c.node_id = o.node_id
               WHERE o.run_id = ? AND o.level = ? AND o.end_t <= ? ORDER BY o.start_t DESC LIMIT ?""",
            (run_id, level, moment, limit))
        return [self._decode(row) for row in rows]

    def salient_before(self, run_id, moment, floor):
        """Every finished node that ended by this moment with at least this salience."""
        rows = self.conn.execute(
            """SELECT o.*, c.closing, c.seq AS closed_seq FROM openings o
               JOIN closings c ON c.run_id = o.run_id AND c.node_id = o.node_id
               WHERE o.run_id = ? AND o.end_t <= ? AND o.salience >= ?""", (run_id, moment, floor))
        return [self._decode(row) for row in rows]

    def cursor(self, run_id):
        """The deepest open node, which is always the most recently opened one still open."""
        row = self.conn.execute(
            """SELECT o.node_id FROM openings o
               LEFT JOIN closings c ON c.run_id = o.run_id AND c.node_id = o.node_id
               WHERE o.run_id = ? AND c.node_id IS NULL ORDER BY o.seq DESC LIMIT 1""", (run_id,)).fetchone()
        return self.node(run_id, row[0]) if row else None

    def effective_limit(self, node):
        """A node's depth limit, or finer if it escalated. Escalating adds an event, so the row never changes."""
        rows = self.conn.execute("SELECT data FROM events WHERE run_id = ? AND node_id = ? AND kind = 'escalated'",
                                 (node["run_id"], node["node_id"]))
        levels = [node["depth_limit"], *(json.loads(row[0])["to"] for row in rows)]
        return max(levels, key=depth)

    def open_node(self, run_id, window, salience, depth_limit, opening):
        validate_opening(opening)
        birth = self.public_seed(run_id).birth_date
        with self.atomic():
            if self.node(run_id, window.id):
                raise WriteOnceError(f"{window.id} already has an opening")
            if find(window.id, birth) != window:
                raise OrderError(f"{window.id} is not a window of this life")
            self._check_can_open(run_id, window, birth)
            self.conn.execute(
                "INSERT INTO openings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, window.id, window.parent_id, window.index, window.level, window.label,
                 window.start.isoformat(), window.end.isoformat(), age_at(birth, window.start), salience,
                 depth_limit, json.dumps(opening), self._next_seq(run_id)))
        return self.node(run_id, window.id)

    def _check_can_open(self, run_id, window, birth):
        if window.parent_id is None:
            return
        parent = self.node(run_id, window.parent_id)
        if parent is None or parent["closing"] is not None:
            raise OrderError(f"{window.id} needs its parent open")
        if depth(self.effective_limit(parent)) <= depth(parent["level"]):
            raise OrderError(f"{parent['node_id']} is at its depth limit, so it has no children")
        if window.index > 0:
            before = children(find(window.parent_id, birth), birth)[window.index - 1]
            sibling = self.node(run_id, before.id)
            if sibling is None or sibling["closing"] is None:
                raise OrderError(f"{window.id} needs {before.id} closed first")

    def close_node(self, run_id, node_id, closing):
        node = self.node(run_id, node_id)
        if node is None:
            raise OrderError(f"{node_id} has no opening to close")
        if node["closing"] is not None:
            raise WriteOnceError(f"{node_id} already has a closing")
        validate_closing(closing, node["opening"])
        with self.atomic():
            self._check_can_close(run_id, node)
            self.conn.execute("INSERT INTO closings VALUES (?, ?, ?, ?)",
                              (run_id, node_id, json.dumps(closing), self._next_seq(run_id)))
        return self.node(run_id, node_id)

    def _check_can_close(self, run_id, node):
        opened = self.child_nodes(run_id, node["node_id"])
        if not opened and depth(self.effective_limit(node)) <= depth(node["level"]):
            return
        window = find(node["node_id"], self.public_seed(run_id).birth_date)
        needed = children(window, self.public_seed(run_id).birth_date)
        closed = sum(child["closing"] is not None for child in opened)
        if closed < len(needed):
            raise OrderError(f"{node['node_id']} has {closed} of {len(needed)} children closed")

    def escalate(self, run_id, node_id):
        """Let a node at its depth limit open finer children mid-window."""
        node = self.node(run_id, node_id)
        if node is None or node["closing"] is not None:
            raise OrderError(f"{node_id} is not open")
        if node["level"] == LEVELS[-1]:
            raise OrderError(f"{node_id} is already the finest level")
        finer = LEVELS[depth(node["level"]) + 1]
        return self.append_event(run_id, node_id, node["start_t"], "escalated", {"to": finer})

    def append_event(self, run_id, node_id, t, kind, data):
        if node_id is not None:
            node = self.node(run_id, node_id)
            if node is None or node["closing"] is not None:
                raise OrderError(f"cannot log an event on {node_id}: it is not open")
        t = t if isinstance(t, str) else t.isoformat()
        with self.atomic():
            seq = self._next_seq(run_id)
            self.conn.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                              (run_id, seq, node_id, t, kind, json.dumps(data)))
        return seq

    def events(self, run_id, start=None, end=None, node_id=None, kind=None, after_seq=0, limit=-1):
        query = "SELECT * FROM events WHERE run_id = ? AND seq > ?"
        args = [run_id, after_seq]
        for clause, value in (("t >= ?", start), ("t < ?", end), ("node_id = ?", node_id), ("kind = ?", kind)):
            if value is not None:
                query += f" AND {clause}"
                args.append(value)
        rows = self.conn.execute(query + " ORDER BY seq LIMIT ?", (*args, limit))
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def count_events(self, run_id, start, end, kind):
        return self.conn.execute("SELECT COUNT(*) FROM events WHERE run_id = ? AND t >= ? AND t < ? AND kind = ?",
                                 (run_id, start, end, kind)).fetchone()[0]

    def state(self, run_id, upto_seq=None, base=None, after_seq=0):
        """Current state is a replay of the log, optionally continuing from an earlier replay."""
        state = base if base is not None else empty_state()
        for event in self.events(run_id, after_seq=after_seq):
            if upto_seq is not None and event["seq"] > upto_seq:
                break
            apply_event(state, event["kind"], event["data"])
        return state

    def fork(self, run_id, node_id):
        """A new run holding everything written before this node opened. The original is only read."""
        node = self.node(run_id, node_id)
        if node is None:
            raise OrderError(f"cannot fork at {node_id}: it has not opened")
        cut = node["seq"]
        with self.atomic():
            new_id = self.conn.execute("SELECT MAX(run_id) + 1 FROM runs").fetchone()[0]
            source = self.conn.execute("SELECT seed, rng_key FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            # A new random stream, or the fork would just replay the same future.
            self.conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                              (new_id, source["seed"], f"{source['rng_key']}/fork{new_id}", run_id, node_id, cut))
            self.conn.execute("INSERT INTO hidden_targets SELECT ?, target FROM hidden_targets WHERE run_id = ?",
                              (new_id, run_id))
            for table in ("openings", "closings", "events"):
                columns = [row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")]
                rest = ", ".join(column for column in columns if column != "run_id")
                self.conn.execute(f"INSERT INTO {table} (run_id, {rest}) SELECT ?, {rest} FROM {table} "
                                  "WHERE run_id = ? AND seq < ?", (new_id, run_id, cut))
        return new_id

    def writes(self, run_id, after_seq=0, limit=2000):
        """Openings, closings, and events merged in the order they were written."""
        # A run may be writing between these queries. Stopping at one sequence number keeps the three in step,
        # or a caller continuing from the newest row it got would skip rows the other queries missed.
        args = (run_id, after_seq, self.last_seq(run_id), limit)
        opened = self.conn.execute("SELECT * FROM openings WHERE run_id = ? AND seq > ? AND seq <= ? ORDER BY seq LIMIT ?",
                                   args).fetchall()
        closed = self.conn.execute(
            """SELECT c.*, o.opening FROM closings c
               JOIN openings o ON o.run_id = c.run_id AND o.node_id = c.node_id
               WHERE c.run_id = ? AND c.seq > ? AND c.seq <= ? ORDER BY c.seq LIMIT ?""", args).fetchall()
        logged = self.conn.execute("SELECT * FROM events WHERE run_id = ? AND seq > ? AND seq <= ? ORDER BY seq LIMIT ?",
                                   args).fetchall()
        writes = [{"write": "opening", **dict(row), "opening": json.loads(row["opening"])} for row in opened]
        writes += [{"write": "closing", **dict(row), "opening": json.loads(row["opening"]),
                    "closing": json.loads(row["closing"])} for row in closed]
        writes += [{"write": "event", **dict(row), "data": json.loads(row["data"])} for row in logged]
        return sorted(writes, key=lambda write: write["seq"])[:limit]

    def counts(self, run_id):
        count = lambda table: self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)).fetchone()[0]
        return {"opened": count("openings"), "closed": count("closings"), "events": count("events")}

    def depth_by_day(self, run_id):
        """The deepest level each day reached, as {date: level}."""
        rows = self.conn.execute(
            f"""SELECT substr(start_t, 1, 10) AS day, level FROM openings WHERE run_id = ?
                AND level IN ({','.join('?' * len(LEVELS[depth('day'):]))})""", (run_id, *LEVELS[depth("day"):]))
        days = {}
        for row in rows:
            if row["day"] not in days or depth(row["level"]) > depth(days[row["day"]]):
                days[row["day"]] = row["level"]
        return days
