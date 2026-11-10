"""What is in mind when a stretch of time is written, shaped like a person's memory rather than a transcript."""
import re

from life.windows import LEVELS, depth, stage_at
from core.settings import LIFE_MEMORY

FAILED = "[failed]"
GIST_END = re.compile(r"(?<=[.!?])\s")


def _closed(node, detail):
    remembered = {"level": node["level"], "label": node["label"], "start_t": node["start_t"],
                  "summary": node["closing"]["summary"]}
    return {**remembered, "what_happened": node["closing"]["what_happened"]} if detail else remembered


def _outline(store, run_id, window):
    """The period you're in, from the whole life down to the parent. You always know where you are in your life."""
    outline, node_id = [], window.parent_id
    while node_id:
        node = store.node(run_id, node_id)
        # A gist only. You remember what a year was like, not how it was worded, and a small model copies what it can see.
        outline.insert(0, {"level": node["level"], "label": node["label"], "setting": GIST_END.split(node["opening"]["setting"])[0]})
        node_id = node["parent_id"]
    return outline


def _recent(store, run_id, window):
    """Yesterday in detail, last week as a gist, last month as less: each step back in time is a coarser level."""
    recent = []
    for level in reversed(LEVELS[1:depth(window.level) + 1]):
        same = level == window.level
        limit = LIFE_MEMORY["recent_same_level"] if same else LIFE_MEMORY["recent_coarser"]
        rows = store.closed_before(run_id, level, window.start.isoformat(), limit)
        recent += [_closed(row, detail=same) for row in rows if not row["closing"]["summary"].startswith(FAILED)]
    return sorted(recent, key=lambda item: item["start_t"])


def _vivid(store, run_id, window, recent):
    """Older moments that stuck. What sticks depends on how much it mattered and how well you could form memories then."""
    newest_allowed = recent[0]["start_t"] if recent else window.start.isoformat()
    rows = store.salient_before(run_id, newest_allowed, LIFE_MEMORY["vivid_floor"])
    scored = [(row["salience"] * stage_at(row["age"])["memory_strength"], row) for row in rows
              if depth(row["level"]) >= depth("month") and not row["closing"]["summary"].startswith(FAILED)]
    scored = [item for item in scored if item[0] >= LIFE_MEMORY["vivid_floor"]]
    # A big day's hours and minutes all carry its salience, but they are one memory, so each day counts once.
    seen, vivid = set(), []
    for _, row in sorted(scored, key=lambda item: (-item[0], depth(item[1]["level"]))):
        day = row["start_t"][:10]
        if day not in seen and len(vivid) < LIFE_MEMORY["vivid"]:
            seen.add(day)
            vivid.append(_closed(row, detail=False))
    return sorted(vivid, key=lambda item: item["start_t"])


def recall(store, run_id, window):
    recent = _recent(store, run_id, window)
    return {"outline": _outline(store, run_id, window), "recent": recent, "vivid": _vivid(store, run_id, window, recent)}


def consolidate(store, run_id, node_id):
    """A closing period's parts, in order. Writing a month from its weeks is how a gist gets formed."""
    kids = sorted(store.child_nodes(run_id, node_id), key=lambda kid: kid["idx"])
    return [{"label": kid["label"], "summary": kid["closing"]["summary"]} for kid in kids
            if kid["closing"] and not kid["closing"]["summary"].startswith(FAILED)]
