"""The morning report: the numbers a run produced, and one line through its tree to read."""
import argparse
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean, median

from life.memory import FAILED
from life.store import Store
from life.windows import LEVELS, depth

# The generator may not write the agent's decisions or inner life. This only finds candidates to read.
INNER_LIFE = re.compile(r"\b(decid\w*|chooses?|chose|feels?|felt|wants?|wanted|thinks?|thought|realiz\w*|hopes?|hoped|plans? to|planned to)\b", re.I)
COMMON_WORDS = {"their", "there", "while", "which", "about", "after", "again", "still", "where", "other", "through", "around", "before", "person"}
FULL_LIFE_WRITES = 24930
BANDS = [(0.3, "under 0.3"), (0.7, "0.3 to 0.7"), (0.85, "0.7 to 0.85"), (1.01, "0.85 and up")]


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    return lines + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]


def _calls(calls):
    if not calls:
        return ["No model calls were logged."]
    successes = [call for call in calls if call["ok"]]
    each = mean(call["seconds"] for call in calls)
    lines = [f"- {len(calls)} calls, {len(calls) - len(successes)} unparsable, {sum(call['finish_reason'] == 'length' for call in calls)} cut off by the token limit",
             f"- {each:.1f}s mean, {median(call['seconds'] for call in calls):.1f}s median, {max(call['seconds'] for call in calls):.1f}s slowest",
             f"- Longest prompt {max(call['prompt_tokens'] for call in calls)} tokens, peak memory {max(call['peak_memory_gb'] for call in calls):.1f} GB",
             f"- At this speed a full life down to days ({FULL_LIFE_WRITES:,} writes) takes about {FULL_LIFE_WRITES * each / 3600:.0f} hours", ""]
    by_level = defaultdict(list)
    for call in calls:
        by_level[call["level"]].append(call)
    rows = [(level, len(by_level[level]), f"{mean(call['seconds'] for call in by_level[level]):.1f}s",
             round(mean(call["prompt_tokens"] for call in by_level[level])), sum(not call["ok"] for call in by_level[level]))
            for level in LEVELS if level in by_level]
    return lines + _table(("Level", "Calls", "Mean time", "Mean prompt tokens", "Unparsable"), rows)


def _salience(nodes):
    counts = defaultdict(Counter)
    for node in nodes:
        counts[node["level"]][next(name for limit, name in BANDS if node["salience"] < limit)] += 1
    return _table(("Level", *(name for _, name in BANDS)),
                  [(level, *(counts[level][name] for _, name in BANDS)) for level in LEVELS if level in counts])


def _motifs(nodes):
    """Words that keep coming back across a run. Comparing neighbors misses a story reworded around the same few things."""
    seen = Counter()
    for node in nodes:
        seen.update(set(re.findall(r"[a-z]{5,}", node["opening"]["setting"].lower())) - COMMON_WORDS)
    return [(word, count / len(nodes)) for word, count in seen.most_common(8) if len(nodes) >= 5 and count / len(nodes) >= 0.25]


def _checks(nodes):
    closed = [node for node in nodes if node["closing"]]
    failed = sum(FAILED in node["opening"]["setting"] for node in nodes) + sum(FAILED in node["closing"]["summary"] for node in closed)
    flagged = []
    for node in nodes:
        for text in (node["opening"]["setting"], *((node["closing"]["summary"], node["closing"]["what_happened"]) if node["closing"] else ())):
            if INNER_LIFE.search(text):
                flagged.append(f"  - {node['label']}: {text}")
    siblings = defaultdict(list)
    for node in closed:
        siblings[node["parent_id"]].append(node)
    repeats = []
    for family in siblings.values():
        family.sort(key=lambda node: node["idx"])
        repeats += [(first, second) for first, second in zip(family, family[1:])
                    if SequenceMatcher(None, first["closing"]["summary"], second["closing"]["summary"]).ratio() > 0.8]
    motifs = ", ".join(f"{word} {share:.0%}" for word, share in _motifs(nodes)) or "none"
    return [f"- {failed} writes fell back to a failure placeholder",
            f"- Words in at least a quarter of all openings: {motifs}",
            f"- {len(repeats)} of {max(0, len(closed) - len(siblings))} neighboring closings are near-repeats",
            *(f"  - {first['label']} / {second['label']}: {second['closing']['summary']}" for first, second in repeats[:8]),
            f"- {len(flagged)} passages may describe inner life or decisions. Read these, since many will be other people:", *flagged[:12]]


def _line(store, run_id):
    """One line from the life down to its deepest closed day or finer, opening then closing at each level."""
    nodes = _nodes(store, run_id)
    closed = [node for node in nodes if node["closing"]]
    if not closed:
        return ["Nothing closed yet."]
    node = max(closed, key=lambda item: (depth(item["level"]), item["start_t"]))
    by_id, chain = {item["node_id"]: item for item in nodes}, []
    while node:
        chain.insert(0, node)
        node = by_id.get(node["parent_id"])
    lines = []
    for item in chain:
        lines += [f"**{item['level']}: {item['label']}** (salience {item['salience']})", "", f"Opening: {item['opening']['setting']}", ""]
        lines += [f"- {pressure['text']} (odds {pressure['odds']})" for pressure in item["opening"]["pressures"]]
        if item["closing"]:
            lines += ["", f"Closing: {item['closing']['what_happened']}"]
        lines.append("")
    return lines


def _nodes(store, run_id):
    rows = store.conn.execute("SELECT node_id FROM openings WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()
    return [store.node(run_id, row[0]) for row in rows]


def write_report(folder):
    folder = Path(folder)
    state = json.loads((folder / "state.json").read_text())
    log = folder / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    store = Store(folder / "life.db")
    lines = [f"# Run report: {folder.name}", "", "## Phases", ""]
    lines += _table(("Phase", "Run", "Stopped because", "Opened", "Closed"),
                    [(name, run_id, state["done"].get(name, "not finished"), *(store.counts(run_id)[key] for key in ("opened", "closed")))
                     for name, run_id in state["runs"].items()])
    lines += ["", "## Calls", "", *_calls(calls)]
    for name, run_id in state["runs"].items():
        nodes = _nodes(store, run_id)
        lines += ["", f"## {name}", "", "### Salience", "", *_salience(nodes), "", "### Checks", "", *_checks(nodes), "", "### One line to read", "", *_line(store, run_id)]
    store.close()
    path = folder / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default=str(Path(__file__).parent.parent / "out" / "overnight" / "latest"))
    print(write_report(parser.parse_args().folder))


if __name__ == "__main__":
    main()
