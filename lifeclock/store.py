"""SQLite storage. See docs/DATA_MODEL.md for why each table exists."""
import hashlib
import json
import sqlite3
import zlib

from .clock import to_t

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

-- Life, segment, year, season, month, week, and day: intervals on the clock.
CREATE TABLE IF NOT EXISTS spans (
    life_id    TEXT NOT NULL,
    level      TEXT NOT NULL,
    key        TEXT NOT NULL,
    start_t    INTEGER NOT NULL,
    end_t      INTEGER NOT NULL,
    parent_key TEXT,
    payload    TEXT NOT NULL,
    rollup     TEXT NOT NULL,
    PRIMARY KEY (life_id, level, key)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS spans_by_time ON spans (life_id, level, start_t);

-- Hours and minutes: one compressed array of 1440 activity codes per day.
CREATE TABLE IF NOT EXISTS day_strips (
    life_id TEXT NOT NULL,
    day_key TEXT NOT NULL,
    strip   BLOB NOT NULL,
    PRIMARY KEY (life_id, day_key)
) WITHOUT ROWID;

-- Sparse minutes that carry authored detail. Everything else is derived.
CREATE TABLE IF NOT EXISTS moments (
    life_id  TEXT NOT NULL,
    t        INTEGER NOT NULL,
    activity TEXT NOT NULL,
    source   TEXT NOT NULL,
    detail   TEXT NOT NULL,
    PRIMARY KEY (life_id, t)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS statements (
    life_id    TEXT NOT NULL,
    id         TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    held_from  INTEGER NOT NULL,
    held_until INTEGER,
    PRIMARY KEY (life_id, id)
) WITHOUT ROWID;

-- Bitemporal: [believed_from, believed_until) is when she held this plan;
-- target_t is the time the plan is about.
CREATE TABLE IF NOT EXISTS plan_versions (
    life_id        TEXT NOT NULL,
    plan_id        TEXT NOT NULL,
    version        INTEGER NOT NULL,
    statement_id   TEXT NOT NULL,
    believed_from  INTEGER NOT NULL,
    believed_until INTEGER NOT NULL,
    target_t       INTEGER NOT NULL,
    text           TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    PRIMARY KEY (life_id, plan_id, version)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS milestones (
    life_id  TEXT NOT NULL,
    plan_id  TEXT NOT NULL,
    version  INTEGER NOT NULL,
    ordinal  INTEGER NOT NULL,
    due_t    INTEGER NOT NULL,
    text     TEXT NOT NULL,
    event_id TEXT,
    PRIMARY KEY (life_id, plan_id, version, ordinal)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS events (
    life_id      TEXT NOT NULL,
    id           TEXT NOT NULL,
    t            INTEGER NOT NULL,
    minutes      INTEGER NOT NULL,
    significance INTEGER NOT NULL,
    title        TEXT NOT NULL,
    text         TEXT NOT NULL,
    PRIMARY KEY (life_id, id)
) WITHOUT ROWID;

-- Written in the same transaction as the data it describes.
CREATE TABLE IF NOT EXISTS checkpoint (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    next_day INTEGER NOT NULL,
    chain    TEXT NOT NULL,
    open     TEXT NOT NULL,
    complete INTEGER NOT NULL
);

-- Wall-clock facts about a run. Excluded from every digest.
CREATE TABLE IF NOT EXISTS run_info (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS telemetry (
    wall_elapsed REAL NOT NULL,
    t            INTEGER NOT NULL,
    lag_seconds  REAL NOT NULL
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_canon(conn, world):
    """Copy the authored records into the database on first run."""
    life = world.life_id
    conn.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)",
        [("canon_sha256", world.canon_sha256), ("life_id", life),
         ("activities", dumps([a["id"] for a in world.activities]))],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO statements VALUES (?,?,?,?,?,?,?)",
        [(life, s["id"], s["segment"], s["kind"], s["text"], to_t(s["from"]),
          None if s["until"] is None else to_t(s["until"])) for s in world.statements.values()],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO plan_versions VALUES (?,?,?,?,?,?,?,?,?)",
        [(life, p["id"], p["version"], p["statement"], to_t(p["formed"]), to_t(p["ended"]),
          to_t(p["target"]), p["text"], p["outcome"]) for p in world.plans],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO milestones VALUES (?,?,?,?,?,?,?)",
        [(life, p["id"], p["version"], i, to_t(m["due"]), m["text"], m["event"])
         for p in world.plans for i, m in enumerate(p["milestones"])],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)",
        [(life, e["id"], to_t(e["at"]), e["minutes"], e["significance"], e["title"], e["text"])
         for e in world.events],
    )


def read_strip(blob):
    return zlib.decompress(blob)


def digests(conn):
    """Hash every record of the simulated life, leaving out wall-clock data."""
    tables = {
        "spans": "SELECT * FROM spans ORDER BY life_id, level, key",
        "moments": "SELECT * FROM moments ORDER BY life_id, t",
        "statements": "SELECT * FROM statements ORDER BY life_id, id",
        "plan_versions": "SELECT * FROM plan_versions ORDER BY life_id, plan_id, version",
        "events": "SELECT * FROM events ORDER BY life_id, id",
    }
    out = {}
    for name, sql in tables.items():
        h = hashlib.sha256()
        for row in conn.execute(sql):
            h.update(repr(row).encode())
        out[name] = h.hexdigest()
    h = hashlib.sha256()
    for key, blob in conn.execute("SELECT day_key, strip FROM day_strips ORDER BY day_key"):
        h.update(key.encode())
        h.update(read_strip(blob))
    out["day_strips"] = h.hexdigest()
    row = conn.execute("SELECT chain, complete FROM checkpoint WHERE id = 1").fetchone()
    out["chain"] = row[0] if row else None
    out["complete"] = bool(row[1]) if row else False
    return out
