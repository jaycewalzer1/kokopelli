"""Why does the agent repeat itself? Re-ask real Qwen the same logged moments, changing one thing at a time.

Each variant removes one possible cause: its own earlier notes, what it saw, the example in the prompt, or the order of
the things it can see. Replies are read and tallied. Nothing here touches the run or its log.
"""
import argparse
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from runtime import replay
from runtime.actions import InvalidDecision, parse_decision
from runtime.frames import load_rgb, save_rgb

NOTES = re.compile(r"Your notes:\n.*?\n\nThe (\d+) images", re.DOTALL)
SEEN = re.compile(r"You can see: (.*)\.\n")
EXAMPLE_TARGET = '"target": "door"}, "diary"'
SAMPLES_AT_TEMPERATURE = 3
SAMPLE_TEMPERATURE = 0.7


def without_notes(prompt):
    return NOTES.sub(r"Your notes:\n(none yet)\n\nThe \1 images", prompt)


def other_example(prompt, visible):
    """The example names door, which might be why it picks door. Use the last thing it can see that isn't door."""
    other = next(name for name in reversed(visible) if name != "door")
    return prompt.replace(EXAMPLE_TARGET, f'"target": "{other}"}}, "diary"')


def reversed_list(prompt, visible):
    return SEEN.sub(f"You can see: {', '.join(reversed(visible))}.\n", prompt, count=1)


def blank_frames(images, folder):
    """Plain gray pictures the same size as what it really saw, so any change comes from the content."""
    return [save_rgb(np.full(load_rgb(path).shape, 128, np.uint8), Path(folder) / f"blank_{i}.png") for i, path in enumerate(images)]


def variants(prompt, visible, images, folder):
    blank = blank_frames(images, folder)
    return {"as_logged": (prompt, images), "no_notes": (without_notes(prompt), images), "blank_frames": (prompt, blank),
            "no_notes_blank_frames": (without_notes(prompt), blank), "other_example": (other_example(prompt, visible), images),
            "reversed_list": (reversed_list(prompt, visible), images)}


def read_reply(raw, visible):
    """The action as a short string, or why the reply wasn't valid."""
    try:
        decision = parse_decision(raw, visible)
    except InvalidDecision as error:
        return {"action": None, "diary": None, "error": str(error)}
    action = decision.action.model_dump()
    return {"action": " ".join(str(value) for value in action.values()), "diary": decision.diary, "error": None}


def probe(run_dir, ask):
    """ask(prompt, images, temperature) returns the model's raw reply."""
    run_dir = Path(run_dir)
    rows = []
    with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
        for tick in replay.summarize(run_dir)["ticks"]:
            images = [str(run_dir / path) for path in tick["agent_input"]["images"]]
            visible = tick["sim"]["visible"]
            for name, (prompt, pictures) in variants(tick["agent_input"]["prompt"], visible, images, folder).items():
                rows.append({"tick": tick["tick"], "variant": name, "temperature": 0.0, **read_reply(ask(prompt, pictures, 0.0), visible)})
            for _ in range(SAMPLES_AT_TEMPERATURE):
                raw = ask(tick["agent_input"]["prompt"], images, SAMPLE_TEMPERATURE)
                rows.append({"tick": tick["tick"], "variant": "as_logged", "temperature": SAMPLE_TEMPERATURE, **read_reply(raw, visible)})
    return rows


def tally(rows):
    result = {}
    for row in rows:
        key = f"{row['variant']} t={row['temperature']}"
        result.setdefault(key, Counter())[row["action"] or "invalid"] += 1
    return {key: dict(counts) for key, counts in result.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from llm_model import ask

    rows = probe(args.run, lambda prompt, images, temperature: ask(prompt, images, max_tokens=300, temperature=temperature))
    summary = {"tally": tally(rows), "rows": rows}
    args.out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["tally"], indent=2))


if __name__ == "__main__":
    main()
