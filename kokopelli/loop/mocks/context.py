"""A made-up half hour of a life, shaped like what the real life tree returns. Includes things the guard must keep out."""
from datetime import datetime, timedelta

from kokopelli.loop.interfaces import ContextDB
from kokopelli.loop.leak_guard import drop_future

START = "2004-06-12T16:00:00"
DEFAULTS = ["move_to", "wait", "speak", "look_at", "wait", "interact"]
# Dated events, including one after the half hour that a working filter must drop.
EVENTS = [
    {"t": "2004-06-12T15:30:00", "text": "Ana said to be home before dark."},
    {"t": "2004-06-12T16:10:00", "text": "A ball comes over the fence."},
    {"t": "2004-06-12T16:20:00", "text": "Ben calls from across the street."},
    {"t": "2031-01-01T00:00:00", "text": "Something decades away that must never be seen."},
]


class MockContext(ContextDB):
    def start_time(self):
        return START

    def context_at(self, now):
        moment = datetime.fromisoformat(now)
        events, dropped = drop_future(EVENTS, now)
        slot = int((moment - datetime.fromisoformat(START)).total_seconds() // 300)
        nodes = [
            {"level": "year", "label": "Age 14", "start_t": "2004-03-14T00:00:00", "setting": "The summer before high school.", "pressures": []},
            {"level": "day", "label": "Sat Jun 12", "start_t": "2004-06-12T00:00:00", "setting": "A warm Saturday on the street where you grew up.", "pressures": []},
            {"level": "min5", "label": f"{moment:%H:%M}", "start_t": now, "setting": f"Out front, part {slot + 1} of the afternoon.",
             "pressures": [event["text"] for event in events[-1:]]},
        ]
        figures = [{"name": "ana", "relationship": "mother", "doing": None}, {"name": "ben", "relationship": "father", "doing": None},
                   {"name": "neighbor", "relationship": "neighbor", "doing": None}]
        recent = [{"level": "hour", "label": "Earlier today", "start_t": "2004-06-12T15:00:00", "summary": event["text"]} for event in events[:1]]
        return {"nodes": nodes, "recent": recent, "state": {"place": "Atlanta, Georgia"}, "figures": figures, "dropped": dropped}

    def default_action(self, now):
        minutes = (datetime.fromisoformat(now) - datetime.fromisoformat(START)) // timedelta(seconds=30)
        return {"type": DEFAULTS[minutes % len(DEFAULTS)], "source": "script"}
