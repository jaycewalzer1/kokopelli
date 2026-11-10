"""The run's append-only record. Each line carries the hash of the one before, so an edit breaks the chain."""
import hashlib
import json
import os
import time
from pathlib import Path

from kokopelli.loop.interfaces import EventLog


def event_hash(event, prev):
    body = json.dumps({key: event[key] for key in ("seq", "kind", "tick", "data")}, sort_keys=True)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def read_lines(path):
    """Return the complete events. A crash can tear a line, and resuming leaves it in place. Skipping one is safe:
    a real event that got garbled would break the hash chain at the next line."""
    events = []
    for line in Path(path).read_text().split("\n"):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


class JsonlLog(EventLog):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        events = read_lines(self.path) if self.path.exists() else []
        self.seq = events[-1]["seq"] if events else 0
        self.prev = events[-1]["hash"] if events else ""
        self.file = self.path.open("a")
        # A torn line is left in place, because this log is never rewritten. It just needs ending.
        if self.path.stat().st_size and not self.path.read_bytes().endswith(b"\n"):
            self.file.write("\n")
            self.file.flush()

    def append(self, kind, tick, data):
        self.seq += 1
        event = {"seq": self.seq, "at": time.time(), "kind": kind, "tick": tick, "data": data}
        event["prev"] = self.prev
        event["hash"] = self.prev = event_hash(event, event["prev"])
        self.file.write(json.dumps(event) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        return event

    def offset(self):
        return self.path.stat().st_size

    def close(self):
        self.file.close()
