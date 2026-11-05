"""Rebuilds a run from its log alone, which is what the viewer shows and what the replay tests check."""
from pathlib import Path

from runtime.event_log import event_hash, read_lines


class BrokenChain(Exception):
    """A line in the log was changed or removed."""


def verify_chain(events):
    prev = ""
    for event in events:
        if event["prev"] != prev or event_hash(event, prev) != event["hash"]:
            raise BrokenChain(f"the log breaks at seq {event['seq']}")
        prev = event["hash"]


def effective(events):
    """Drop what a crash left behind: a resume restarts from a tick, so earlier tries at that tick don't count."""
    kept = []
    for event in events:
        if event["kind"] == "resume":
            kept = [item for item in kept if item["tick"] is None or item["tick"] < event["data"]["from_tick"]]
        kept.append(event)
    return kept


def load(run_dir, verify=True):
    events = read_lines(Path(run_dir) / "events.jsonl")
    if verify:
        verify_chain(events)
    return events


def _tick_view(tick):
    return {"tick": tick, "chunks": [], "drift": [], "reanchors": [], "outputs": []}


def summarize(run_dir):
    """Everything the viewer draws, from nothing but the log."""
    events = load(run_dir)
    ticks, run = {}, {"alarms": [], "resumes": 0}
    single = {"sim_step": "sim", "wm_prompt": "wm_prompt", "agent_input": "agent_input", "decision": "decision", "autonomy": "autonomy",
              "tick_end": "timing", "agent_fallback": "fallback"}
    many = {"wm_chunk": "chunks", "drift_check": "drift", "reanchor": "reanchors", "agent_output": "outputs"}
    for event in effective(events):
        kind, tick, data = event["kind"], event["tick"], event["data"]
        if kind in single:
            ticks.setdefault(tick, _tick_view(tick))[single[kind]] = data
        elif kind in many:
            ticks.setdefault(tick, _tick_view(tick))[many[kind]].append(data)
        elif kind == "leak_alarm":
            run["alarms"].append({"tick": tick, **data})
        elif kind == "resume":
            run["resumes"] += 1
        elif kind in ("run_start", "sim_reset", "run_end", "counterfactual", "stitched"):
            run[kind] = data
    done = [ticks[key] for key in sorted(ticks) if "timing" in ticks[key]]
    seconds = {}
    for tick in done:
        for stage, value in tick["timing"]["seconds"].items():
            seconds[stage] = round(seconds.get(stage, 0) + value, 3)
    differs = [tick["autonomy"]["differs"] for tick in done if "autonomy" in tick]
    run["totals"] = {"ticks": len(done), "seconds": seconds, "cost_usd": round(sum(t["timing"]["cost_usd"] for t in done), 4),
                     "reanchors": sum(len(t["reanchors"]) for t in done), "fallbacks": sum("fallback" in t for t in done),
                     "invalid_replies": sum(not o["valid"] for t in done for o in t["outputs"]),
                     "autonomy": round(sum(differs) / len(differs), 3) if differs else None, "events": len(events)}
    return {"run": run, "ticks": done}


def trajectory(run_dir):
    """Agent position and action per tick, for comparing two runs."""
    return [{"tick": t["tick"], "pos": t["sim"]["state"]["agent"]["pos"], "action": t["decision"]["action"],
             "objects": {name: item["state"] for name, item in t["sim"]["state"]["objects"].items()}} for t in summarize(run_dir)["ticks"]]
