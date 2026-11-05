"""Compare two runs of the same seed: drift with and without control, or an agent against the null agent on a real sim."""
import argparse
import json
import math
import statistics
from pathlib import Path

from runtime import replay


def drift_summary(ticks):
    scores = [check["score"] for tick in ticks for check in tick["drift"]]
    return {"checks": len(scores), "mean": round(statistics.mean(scores), 4) if scores else None, "max": max(scores, default=None),
            "last_quarter_mean": round(statistics.mean(scores[-max(1, len(scores) // 4):]), 4) if scores else None,
            "reanchors": sum(len(tick["reanchors"]) for tick in ticks)}


def compare(first, second):
    a, b = replay.summarize(first)["ticks"], replay.summarize(second)["ticks"]
    shared = min(len(a), len(b))
    gaps = [math.dist(a[i]["sim"]["state"]["agent"]["pos"], b[i]["sim"]["state"]["agent"]["pos"]) for i in range(shared)]
    differing = sum(a[i]["decision"]["action"] != b[i]["decision"]["action"] for i in range(shared))
    return {"drift": {str(first): drift_summary(a), str(second): drift_summary(b)}, "ticks_compared": shared, "actions_differ": differing,
            "agent_distance": {"final": round(gaps[-1], 3) if gaps else 0, "max": round(max(gaps, default=0), 3)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.first, args.second), indent=2))


if __name__ == "__main__":
    main()
