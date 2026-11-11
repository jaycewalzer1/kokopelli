"""Psych-101 (trial-by-trial human choices from 160 experiments) as rows a LoRA can train on, minus what our sweeps test.

    .venv/bin/python -m experiments.sensation.psych101.prepare download   # 859 MB into out/sensation/psych101/data/raw
    .venv/bin/python -m experiments.sensation.psych101.prepare survey     # every experiment: size, screen words, first lines
    .venv/bin/python -m experiments.sensation.psych101.prepare convert    # the LoRA rows, the split and the held-out list

Read SOURCE.md first: it holds the licence and what was and wasn't downloaded. Nothing here loads a model.

What a row is. A Psych-101 session is one participant's whole experiment written out in English, each choice they made
wrapped in << and >>. mlx-vlm's trainer learns from chat rows and can restrict the loss to the last assistant message
(`train_on_completions`). So one row is one choice: the user message is the session up to that choice (the instructions,
then as much of the most recent history as fits), and the assistant message is what the person chose. The loss then
falls on the human's choice only, never on the experimenter's text.

What is left out, and why. Our sweeps ask whether hunger changes sharing. If the adapter had seen people play dictator or
public-goods games, a change on the sweep could be memory of those games and not transfer from how people decide in
general. So every experiment about food, hunger, generosity or social giving is held out (held_out.yaml, one reason
each). The list is checked, not trusted: every experiment whose text matches a screen word must be either held out or
listed under `kept_after_review` with the reason it is unrelated, or `convert` refuses to write anything.

The split is fixed by hashing (experiment, participant): the same person is never in both train and validation, and
rerunning gives the same files byte for byte.
"""
import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from experiments.benchmarks.core import REPO, stable_int

REPO_ID = "marcelbinz/Psych-101"
REVISION = "611565c66395e2787cd7e3305149bb75dc138024"
FILENAME = "prompts_training.jsonl"
SHA256 = "7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01"

HERE = Path(__file__).resolve().parent
HELD_OUT = HERE / "held_out.yaml"
DATA = REPO / "out" / "sensation" / "psych101" / "data"   # never in git

CHOICE = re.compile(r"<<(.*?)>>", re.DOTALL)
CUT = "[...]"

# Words that mark an experiment as possibly about what the sweeps test. Deliberately broad: a match only means "a person
# must look", and held_out.yaml records what they decided. Matched on whole words, case ignored.
SCREEN = {
    "food": ("food", "foods", "hungry", "hunger", "starving", "starve", "eat", "eats", "eating", "ate", "feed", "feeds",
             "feeding", "fed", "meal", "meals", "snack", "snacks", "breakfast", "lunch", "dinner", "cook", "cooking", "egg",
             "eggs", "fruit", "fruits", "bread", "calorie", "calories", "appetite", "thirst", "thirsty"),
    "giving": ("donate", "donated", "donation", "donations", "charity", "charities", "generous", "generosity", "altruism",
               "altruistic", "dictator", "ultimatum", "proposer", "responder", "recipient", "trustee", "investor",
               "public good", "public goods", "group account", "common pool", "contribute", "contributed", "contribution",
               "contributions", "cooperate", "cooperation", "defect", "share", "shares", "sharing", "split the", "send to",
               "transfer to", "give", "gives", "giving", "gave", "gift", "gifts", "trade", "lend", "other player",
               "other players", "other participant", "other participants", "other person", "your partner", "your opponent",
               "fair", "unfair", "offer", "offers", "offered"),
}
_WORD = re.compile(r"[a-z]+")
_SINGLE = {topic: frozenset(word for word in words if " " not in word) for topic, words in SCREEN.items()}
_PHRASE = {topic: {word: re.compile(rf"\b{re.escape(word)}\b") for word in words if " " in word} for topic, words in SCREEN.items()}


# ---------------------------------------------------------------- reading

def sessions(path):
    """One dict per session, read a line at a time: the file is 859 MB and never needs to be in memory at once."""
    with Path(path).open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(2 ** 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(data=DATA):
    """Fetch the one training file at the pinned revision, with no token, and check it is the file SOURCE.md describes."""
    from huggingface_hub import hf_hub_download
    raw = Path(data) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = Path(hf_hub_download(REPO_ID, FILENAME, repo_type="dataset", revision=REVISION, local_dir=raw, token=False))
    found = sha256_file(path)
    if found != SHA256:
        raise SystemExit(f"{path} has SHA-256 {found}, not the {SHA256} recorded in SOURCE.md. Not using it.")
    record = {"repo": REPO_ID, "revision": REVISION, "file": FILENAME, "bytes": path.stat().st_size, "sha256": found,
              "licence": "apache-2.0 (see experiments/sensation/psych101/SOURCE.md)", "downloaded": date.today().isoformat(),
              "token_sent": False}
    (raw / "download.json").write_text(json.dumps(record, indent=1) + "\n")
    return path


# ---------------------------------------------------------------- the hold-out

def study(experiment):
    """`hilbig2014generalized/exp1.csv` -> `hilbig2014generalized`: one paper's experiments share a study name."""
    return experiment.split("/", 1)[0]


def load_held_out(path=HELD_OUT):
    """{"held_out": {name: reason}, "kept_after_review": {name: reason}, "tiers": {held-out name: tier}}.

    A name is a study or a full experiment id.
    """
    config = yaml.safe_load(Path(path).read_text()) or {}
    lists = {}
    for key in ("held_out", "kept_after_review"):
        entries = config.get(key) or []
        missing = [entry for entry in entries if not str(entry.get("reason", "")).strip() or not entry.get("experiment")]
        if missing:
            raise ValueError(f"{path}: every {key} entry needs an experiment and a reason. Bad: {missing}")
        lists[key] = {entry["experiment"]: " ".join(str(entry["reason"]).split()) for entry in entries}
    both = set(lists["held_out"]) & set(lists["kept_after_review"])
    if both:
        raise ValueError(f"{path}: listed as both held out and kept: {sorted(both)}")
    # "rule": the plan's rule plainly covers it. "cautious": held out to be safe, and the owner may decide otherwise.
    lists["tiers"] = {entry["experiment"]: entry.get("tier", "rule") for entry in config.get("held_out") or []}
    return lists


def listed(experiment, names):
    """The entry covering this experiment (its full id first, then its study), or None."""
    return experiment if experiment in names else study(experiment) if study(experiment) in names else None


def screen(text):
    """Which screen words a text contains, by topic: {"giving": ["dictator", ...]}. Empty when nothing matches."""
    # One pass that splits the text into words and intersects, then the few two-word phrases: a hundred-way regex
    # alternation over 839 MB took over five minutes; this takes about one.
    lowered = text.lower()
    words = set(_WORD.findall(lowered))
    hits = {}
    for topic in SCREEN:
        found = set(_SINGLE[topic] & words)
        found |= {phrase for phrase, pattern in _PHRASE[topic].items() if phrase in lowered and pattern.search(lowered)}
        if found:
            hits[topic] = sorted(found)
    return hits


def unreviewed(screen_hits, lists):
    """Experiments that matched a screen word and that nobody has ruled on. `convert` refuses while this isn't empty."""
    return {experiment: hits for experiment, hits in sorted(screen_hits.items())
            if hits and not listed(experiment, lists["held_out"]) and not listed(experiment, lists["kept_after_review"])}


# ---------------------------------------------------------------- one session into rows

def split_of(experiment, participant, validation_percent=5):
    """Train or validation, by person: all of one participant's choices land on the same side."""
    return "validation" if stable_int("psych101-split", experiment, participant) % 100 < validation_percent else "train"


def strip_marks(text):
    """The transcript as a person would read it: earlier choices stay, their << >> wrapping goes."""
    return CHOICE.sub(lambda match: match.group(1), text)


def context(text, start, max_chars=2400, head_chars=1000):
    """What the model reads before the choice that begins at `start`: the instructions, then the latest history that fits.

    The instructions are everything before the line holding the first choice. When the session so far is longer than
    max_chars, the oldest history is dropped (whole lines where there are lines) and a [...] line marks the gap, so a
    row's length is bounded however long the session ran.
    """
    first = CHOICE.search(text)
    head_end = text.rfind("\n", 0, first.start()) + 1 if first else 0
    head_end = min(head_end, start)
    head, body = text[:head_end], strip_marks(text[head_end:start])
    if len(head) > head_chars:
        head = head[:head_chars].rsplit(None, 1)[0] + f" {CUT}\n"
    room = max(max_chars - len(head), max_chars // 4)
    if len(body) > room:
        tail = body[-room:]
        line = tail.find("\n")
        space = tail.find(" ")
        tail = tail[line + 1:] if 0 <= line < len(tail) - 1 else tail[space + 1:] if space >= 0 else tail
        body = f"{CUT}\n{tail}"
    return (head + body).rstrip()


def picked(count, per_session, experiment, participant, seed=0):
    """Which of a session's `count` choices become rows: a fixed random handful, in order."""
    if count <= per_session:
        return list(range(count))
    return sorted(random.Random(stable_int("psych101-pick", experiment, participant, seed)).sample(range(count), per_session))


def rows_from(session, per_session=2, max_chars=2400, head_chars=1000, seed=0):
    """Chat rows for one session, in mlx-vlm's format, with where each came from.

    The extra keys are for the hold-out check and the sidecar; the trainer reads only `messages`.
    """
    text, experiment, participant = session["text"], session["experiment"], session["participant"]
    choices = list(CHOICE.finditer(text))
    rows = []
    for index in picked(len(choices), per_session, experiment, participant, seed):
        match = choices[index]
        answer = match.group(1).strip()
        prompt = context(text, match.start(), max_chars, head_chars)
        if not answer or not prompt:
            continue
        rows.append({"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}],
                     "experiment": experiment, "participant": participant, "choice": index, "choices_in_session": len(choices)})
    return rows


def interleave(by_experiment):
    """Round-robin over experiments (sorted by name), so the first n rows cover as many experiments as n allows.

    The pilot trains on a prefix of this order: however short the night makes it, it isn't one experiment's worth.
    """
    names = sorted(by_experiment)
    longest = max((len(by_experiment[name]) for name in names), default=0)
    return [by_experiment[name][turn] for turn in range(longest) for name in names if turn < len(by_experiment[name])]


# ---------------------------------------------------------------- the whole file

def survey(source, screen_sessions=None):
    """Per experiment: sessions, choices, characters, screen words and how its text opens.

    The screen reads every session unless screen_sessions caps it: a word list that names a food in session 900 is
    exactly what a look at the first few would miss.
    """
    found = {}
    for session in sessions(source):
        entry = found.setdefault(session["experiment"], {"sessions": 0, "choices": 0, "chars": 0, "screen": {}, "opens": ""})
        if screen_sessions is None or entry["sessions"] < screen_sessions:
            for topic, words in screen(session["text"]).items():
                entry["screen"][topic] = sorted(set(entry["screen"].get(topic, [])) | set(words))
        if not entry["opens"]:
            entry["opens"] = strip_marks(session["text"])[:700]
        entry["sessions"] += 1
        entry["choices"] += len(CHOICE.findall(session["text"]))
        entry["chars"] += len(session["text"])
    return dict(sorted(found.items()))


def convert(source, out, held_out_path=HELD_OUT, per_session=2, max_chars=2400, head_chars=1000, validation_percent=5,
            pilot_per_experiment=40, seed=0, screen_sessions=None):
    """Write the LoRA folder. Two passes: the first only checks that the hold-out list has ruled on every screen match."""
    source, out = Path(source), Path(out)
    lists = load_held_out(held_out_path)
    inventory = survey(source, screen_sessions)
    open_questions = unreviewed({name: entry["screen"] for name, entry in inventory.items()}, lists)
    if open_questions:
        lines = "\n".join(f"  {name}: {hits}" for name, hits in open_questions.items())
        raise SystemExit(f"These experiments match a screen word and aren't ruled on in {held_out_path}:\n{lines}\n"
                         "Add each to held_out or kept_after_review, with a reason. Nothing was written.")
    unknown = sorted(name for key in ("held_out", "kept_after_review") for name in lists[key]
                     if not any(name in (experiment, study(experiment)) for experiment in inventory))
    if unknown:
        raise SystemExit(f"{held_out_path} names experiments that aren't in the data: {unknown}. Nothing was written.")

    lora = out / "lora"
    (lora / "pilot").mkdir(parents=True, exist_ok=True)
    counts = {"train": Counter(), "validation": Counter(), "transfer_held_out": Counter()}
    pilot = {"train": {}, "validation": {}}
    files = {name: (lora / f"{name}.jsonl").open("w", encoding="utf-8") for name in counts}
    try:
        for session in sessions(source):
            experiment = session["experiment"]
            held = listed(experiment, lists["held_out"])
            name = "transfer_held_out" if held else split_of(experiment, session["participant"], validation_percent)
            for row in rows_from(session, per_session, max_chars, head_chars, seed):
                files[name].write(json.dumps(row, ensure_ascii=False) + "\n")
                counts[name][experiment] += 1
                if not held:
                    # A fixed sample per experiment for the pilot: keep the rows with the smallest hash, whatever order they arrive in.
                    rank = stable_int("psych101-pilot", experiment, row["participant"], row["choice"], seed)
                    keep = pilot[name].setdefault(experiment, [])
                    keep.append((rank, row))
                    if len(keep) > 4 * pilot_per_experiment:
                        keep.sort(key=lambda pair: pair[0])
                        del keep[pilot_per_experiment:]
    finally:
        for file in files.values():
            file.close()

    pilot_counts = {}
    for name, by_experiment in pilot.items():
        limit = pilot_per_experiment if name == "train" else max(1, pilot_per_experiment // 10)
        chosen = {experiment: [row for _, row in sorted(pairs, key=lambda pair: pair[0])[:limit]]
                  for experiment, pairs in by_experiment.items()}
        ordered = interleave(chosen)
        with (lora / "pilot" / f"{name}.jsonl").open("w", encoding="utf-8") as file:
            for row in ordered:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
        pilot_counts[name] = len(ordered)

    held_report = []
    for name, reason in lists["held_out"].items():
        covered = [experiment for experiment in inventory if name in (experiment, study(experiment))]
        held_report.append({"experiment": name, "tier": lists["tiers"][name], "reason": reason, "covers": covered,
                            "sessions": sum(inventory[e]["sessions"] for e in covered),
                            "choices": sum(inventory[e]["choices"] for e in covered),
                            "screen": {e: inventory[e]["screen"] for e in covered}})
    kept_report = [{"experiment": name, "reason": reason,
                    "screen": {e: inventory[e]["screen"] for e in inventory if name in (e, study(e))}}
                   for name, reason in lists["kept_after_review"].items()]
    total = {key: sum(entry[key] for entry in inventory.values()) for key in ("sessions", "choices", "chars")}
    held_total = {key: sum(entry[key] for entry in held_report) for key in ("sessions", "choices")}
    (out / "held_out.json").write_text(json.dumps({
        "why": "Experiments about food, hunger, generosity or social giving never reach train or validation, so the "
               "sensation sweeps measure transfer and not memory.",
        "held_out": held_report, "kept_after_review": kept_report,
        "cost": {"experiments": sum(len(entry["covers"]) for entry in held_report), "of_experiments": len(inventory),
                 **held_total, **{f"of_{key}": total[key] for key in held_total},
                 "by_tier": {tier: {key: sum(entry[key] for entry in held_report if entry["tier"] == tier) for key in held_total}
                             for tier in sorted(set(lists["tiers"].values()))}},
    }, indent=1) + "\n")
    manifest = {
        "source": {"repo": REPO_ID, "revision": REVISION, "file": FILENAME, "sha256": SHA256,
                   "licence": "apache-2.0 (experiments/sensation/psych101/SOURCE.md)"},
        "settings": {"per_session": per_session, "max_chars": max_chars, "head_chars": head_chars,
                     "validation_percent": validation_percent, "pilot_per_experiment": pilot_per_experiment, "seed": seed,
                     "screen_sessions": screen_sessions},
        "held_out_list_sha256": sha256_file(held_out_path),
        "in_the_file": {"experiments": len(inventory), **total},
        "rows": {name: {"rows": sum(counter.values()), "experiments": len(counter)} for name, counter in counts.items()},
        "pilot_rows": pilot_counts,
        "files": {str(path.relative_to(out)): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
                  for path in sorted(lora.rglob("*.jsonl"))},
        "format": "mlx-vlm 0.7.11 SFT rows: {'messages': [user, assistant]}; train with train_on_completions so the loss "
                  "is on the human's choice only. transfer_held_out.jsonl is for testing, never for training.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download")
    look = commands.add_parser("survey")
    look.add_argument("--json", action="store_true", help="the whole inventory as JSON, for reading every experiment's opening")
    make = commands.add_parser("convert")
    make.add_argument("--per-session", type=int, default=2, help="choices turned into rows per session")
    make.add_argument("--max-chars", type=int, default=2400, help="longest user message, about 600 tokens")
    make.add_argument("--pilot-per-experiment", type=int, default=40)
    for sub in (look, make):
        sub.add_argument("--source", default=str(DATA / "raw" / FILENAME))
    make.add_argument("--out", default=str(DATA))
    args = parser.parse_args()
    if args.command == "download":
        print(download())
    elif args.command == "survey":
        inventory = survey(args.source)
        if args.json:
            print(json.dumps(inventory, indent=1))
            return
        lists = load_held_out() if HELD_OUT.exists() else {"held_out": {}, "kept_after_review": {}}
        for name, entry in inventory.items():
            ruling = "HELD OUT" if listed(name, lists["held_out"]) else "kept" if listed(name, lists["kept_after_review"]) else \
                "UNREVIEWED" if entry["screen"] else ""
            print(f"{name}\t{entry['sessions']}\t{entry['choices']}\t{ruling}\t{entry['screen'] or ''}")
    else:
        manifest = convert(args.source, args.out, per_session=args.per_session, max_chars=args.max_chars,
                           pilot_per_experiment=args.pilot_per_experiment)
        print(json.dumps({key: manifest[key] for key in ("in_the_file", "rows", "pilot_rows")}, indent=1))


if __name__ == "__main__":
    main()
