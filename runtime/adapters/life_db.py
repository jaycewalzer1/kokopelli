"""The real life tree as run context. A run works from its own copy, so the shared database is never opened for writing."""
import json
import re
import sqlite3
from pathlib import Path

from life.store import Store, apply_event, empty_state
from life.windows import depth
from runtime.interfaces import ContextDB
from runtime.leak_guard import drop_future, is_future

# The tree's verbs, grouped by the sim action they most resemble. Only used to score autonomy.
VERB_TO_ACTION = {
    "play": "interact", "practice": "interact", "work": "interact", "study": "interact", "save": "interact", "risk": "interact",
    "explore": "move_to", "follow": "move_to", "join": "move_to", "leave": "move_to", "rebel": "move_to",
    "ask": "speak", "share": "speak", "confide": "speak", "cry": "speak", "commit": "speak",
    "copy": "look_at",
    "refuse": "wait", "hide": "wait", "withdraw": "wait",
}
RECENT_LEVELS = ("day", "hour", "min15")


def copy_database(source, destination):
    """Copy through SQLite's backup, which also picks up writes still sitting in the WAL file."""
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True)
    writer = sqlite3.connect(destination)
    with writer:
        reader.backup(writer)
    reader.close()
    writer.close()
    return destination


class LifeContext(ContextDB):
    def __init__(self, db_copy, run_id, start_time=None):
        self.store, self.run_id, self._start = Store(db_copy), run_id, start_time
        self.seed = self.store.public_seed(run_id)

    def start_time(self):
        return self._start or self.deepest_day_start()

    def deepest_day_start(self):
        """The last day this life has written, starting at the morning, so a demo has real text to read."""
        row = self.store.conn.execute("SELECT start_t FROM openings WHERE run_id = ? AND level = 'day' ORDER BY start_t DESC LIMIT 1",
                                      (self.run_id,)).fetchone()
        if not row:
            raise ValueError(f"life run {self.run_id} has no written days")
        return row[0].split("T")[0] + "T09:00:00"

    def _active(self, now):
        rows = self.store.conn.execute(
            "SELECT node_id FROM openings WHERE run_id = ? AND start_t <= ? AND end_t > ?", (self.run_id, now, now)).fetchall()
        nodes = [self.store.node(self.run_id, row[0]) for row in rows]
        return sorted(nodes, key=lambda node: depth(node["level"]))

    def context_at(self, now):
        nodes = [{"level": node["level"], "label": node["label"], "start_t": node["start_t"], "setting": node["opening"]["setting"],
                  "pressures": [pressure["text"] for pressure in node["opening"]["pressures"]]} for node in self._active(now)]
        recent = []
        for level in RECENT_LEVELS:
            for row in self.store.closed_before(self.run_id, level, now, 1):
                recent.append({"level": row["level"], "label": row["label"], "start_t": row["start_t"], "summary": row["closing"]["summary"]})
        events, dropped = drop_future([{"t": row["t"], "kind": row["kind"], "data": row["data"]}
                                       for row in self.store.events(self.run_id)], now)
        state = empty_state()
        for event in events:
            apply_event(state, event["kind"], event["data"])
        # The tree doesn't record what people are doing moment to moment, so "doing" stays empty for now.
        figures = [{"name": name, "relationship": person["relationship"], "doing": None} for name, person in state["people"].items()]
        return {"nodes": nodes, "recent": recent, "state": {"place": state["place"] or self.seed.place, "money": state["money"]},
                "figures": figures, "dropped": dropped}

    def default_action(self, now):
        """The tree's own choice in this slot if it made one. Reading a closing is fine here: this never reaches a prompt."""
        for node in reversed(self._active(now)):
            choices = node["closing"]["choices"] if node["closing"] else []
            if choices:
                verb = choices[0]["verb"]
                return {"type": VERB_TO_ACTION.get(verb, "wait"), "source": f"tree:{node['level']}:{verb}"}
        return {"type": "wait", "source": "no_choice_in_tree"}
