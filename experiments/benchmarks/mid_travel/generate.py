"""Generate draft travel items. Nothing here freezes anything: that is a separate step the owner approves.

The numbers come from a fixed grid here in code. The LLM only writes the words around them. That way the odds,
stakes and framing are balanced by design and can't drift with whatever the writer finds natural. Every generated
item is then checked: the stated numbers must appear, and the text mustn't mention the training world.

Try it on throwaway items:
    python -m experiments.benchmarks.mid_travel.generate --backend mock --out /tmp/evals_items.jsonl
Real generation is `--backend api`, after the owner picks the writer model (see HANDOFF.md):
    python -m experiments.benchmarks.mid_travel.generate --backend api --model <id> --out experiments/benchmarks/mid_travel/items/draft.jsonl
    python -m experiments.benchmarks.freeze freeze mid_travel experiments/benchmarks/mid_travel/items/draft.jsonl
"""
import argparse
import itertools
import json
import random
import re
from pathlib import Path

from experiments.benchmarks.core import BANNED_IN_PROMPTS, stable_int

SPEC_VERSION = 1
DOMAINS = ("commute", "flight", "delivery", "hiking")
FRAMES = ("gain", "loss")
RARE_PERCENT = (1, 2, 5, 10, 20)
STAKES = ("low", "medium", "high")
# (minutes saved most of the time, minutes lost in the rare case), by stakes
TIME_STAKES = {"low": (5, 40), "medium": (15, 120), "high": (30, 360)}
N_RARE, N_SANITY = 50, 10


def build_specs(seed=0):
    """A balanced list of 60 specs: 50 with a rare large cost and 10 sanity checks with no rare event."""
    grid = list(itertools.product(DOMAINS, FRAMES, RARE_PERCENT, STAKES))
    rng = random.Random(stable_int("mid_travel_specs", SPEC_VERSION, seed))
    rng.shuffle(grid)
    # Sort by how often each level has been used, so a short list still covers every level evenly.
    used, picked = {}, []
    for _ in range(N_RARE):
        best = min(grid, key=lambda c: sum(used.get(value, 0) for value in c))
        grid.remove(best)
        picked.append(best)
        for value in best:
            used[value] = used.get(value, 0) + 1

    specs = []
    for index, (domain, frame, percent, stakes) in enumerate(picked, 1):
        saved, lost = TIME_STAKES[stakes]
        specs.append({"id": f"travel_{index:03d}", "sanity": False, "domain": domain, "frame": frame,
                      "rare_percent": percent, "stakes": stakes, "minutes_saved": saved, "minutes_lost": lost})
    for index in range(N_SANITY):
        domain = DOMAINS[index % len(DOMAINS)]
        saved = (10, 20, 30)[index % 3]
        specs.append({"id": f"travel_sanity_{index + 1:02d}", "sanity": True, "domain": domain, "frame": FRAMES[index % 2],
                      "rare_percent": 0, "stakes": "none", "minutes_saved": saved, "minutes_lost": 0,
                      "sanity_correct": "risky"})
    return specs


def writer_prompt(spec):
    if spec["sanity"]:
        odds = f"The faster option never has any delay. It is {spec['minutes_saved']} minutes faster than the other option every time, at no extra cost."
    else:
        odds = (f"The faster option usually saves {spec['minutes_saved']} minutes. "
                f"But {spec['rare_percent']}% of the time it costs {spec['minutes_lost']} extra minutes instead.")
    framing = ("Describe the outcomes as time gained or kept." if spec["frame"] == "gain"
               else "Describe the outcomes as time lost or wasted.")
    return (
        f"Write one short travel-planning decision about {spec['domain']}. Someone is choosing between two options.\n"
        f"The reliable option always takes the same time with no surprises. {odds}\n{framing}\n"
        "State the exact numbers above. Do not say which option is better. Do not mention any specific town or "
        "person, or use the words shortcut, errand or city.\n"
        'Reply with only a JSON object with the keys "scenario" (one or two sentences of setting, with no numbers), '
        '"reliable" (the reliable option, one sentence) and "risky" (the faster option, one sentence, with its numbers).'
    )


def check_generated(spec, generated):
    """Problems with one generated item. An empty list means it's acceptable."""
    problems = []
    for key in ("scenario", "reliable", "risky"):
        if not isinstance(generated.get(key), str) or not generated[key].strip():
            problems.append(f"missing {key}")
    if problems:
        return problems
    text = " ".join(generated[key] for key in ("scenario", "reliable", "risky"))
    banned = BANNED_IN_PROMPTS.search(text)
    if banned:
        problems.append(f"banned word: {banned.group(0)}")
    numbers = set(re.findall(r"\d+", generated["risky"]))
    needed = [spec["minutes_saved"]]
    if not spec["sanity"]:
        needed += [spec["rare_percent"], spec["minutes_lost"]]
    for number in needed:
        if str(number) not in numbers:
            problems.append(f"risky option doesn't state {number}")
    return problems


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _mock_write(prompt_spec):
    """A pretend writer so the pipeline can be tested. Its items are throwaway and say so in the meta line."""
    saved, lost, percent = prompt_spec["minutes_saved"], prompt_spec["minutes_lost"], prompt_spec["rare_percent"]
    risky = (f"Take the faster {prompt_spec['domain']} option, {saved} minutes quicker with no delay ever." if prompt_spec["sanity"]
             else f"Take the faster {prompt_spec['domain']} option, which saves {saved} minutes but {percent}% of the time costs {lost} minutes.")
    return json.dumps({"scenario": f"You are planning a {prompt_spec['domain']} trip.",
                       "reliable": f"Take the standard {prompt_spec['domain']} option at its usual time.", "risky": risky})


def generate(write, seed=0, retries=2):
    """Run `write(prompt) -> text` over every spec. Returns (items, failures). Failures are reported, never dropped quietly."""
    items, failures = [], []
    for spec in build_specs(seed):
        problems = []
        for _ in range(retries + 1):
            generated = _extract_json(write(spec))
            problems = check_generated(spec, generated)
            if not problems:
                items.append({**spec, "scenario": generated["scenario"], "reliable": generated["reliable"], "risky": generated["risky"]})
                break
        if problems:
            failures.append({"id": spec["id"], "problems": problems})
    return items, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", required=True, choices=["mock", "api"])
    parser.add_argument("--model", help="Writer model id, for --backend api")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.out.name == "mid_travel_v1.jsonl":
        parser.error("Refusing to write the frozen name. Generate a draft, review it, then use benchmarks.freeze.")
    if args.out.exists():
        parser.error(f"{args.out} exists. Pick a new name so nothing is overwritten.")

    if args.backend == "mock":
        write = _mock_write
        writer = "mock (THROWAWAY: pipeline test only)"
    else:
        from experiments.benchmarks.backends.api import chat_once
        write = lambda spec: chat_once(writer_prompt(spec), args.model, args.base_url, temperature=0.7, max_tokens=300)
        writer = args.model

    items, failures = generate(write, args.seed)
    meta = {"instrument": "mid_travel", "spec_version": SPEC_VERSION, "seed": args.seed, "writer_model": writer,
            "verified": False, "frozen": False, "failures": failures}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as file:
        file.write(json.dumps({"_meta": meta}) + "\n")
        for item in items:
            file.write(json.dumps(item) + "\n")
    print(f"Wrote {len(items)} items to {args.out}; {len(failures)} specs failed checks.")


if __name__ == "__main__":
    main()
