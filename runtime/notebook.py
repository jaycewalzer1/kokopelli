"""The agent's notes as a folder of markdown files, following Google's Open Knowledge Format v0.2.

One file per distinct note, index.md listing them and log.md recording changes. Writing nearly the same note again
updates its file instead of adding another, so the prompt shows a repeated thought once rather than feeding it back
five times. The checkpoint holds the same list, because a resume repeats any tick after it and the folder must forget that tick.
"""
import difflib
import json
from pathlib import Path

SAME_NOTE = 0.9
DESCRIPTION_CHARS = 100
ACTOR = "agent/kokopelli"


def remember(notes, now, text):
    """Add a note, or mark an existing one as written again. Returns the list."""
    for note in notes:
        if difflib.SequenceMatcher(None, note["text"], text).ratio() >= SAME_NOTE:
            note["last"], note["times"] = now, note.get("times", 1) + 1
            return notes
    notes.append({"t": now, "text": text, "last": now, "times": 1})
    return notes


def latest(notes, count):
    """The notes touched most recently, oldest first, so a repeated thought stays in view without crowding the others."""
    return sorted(notes, key=lambda note: note.get("last", note["t"]))[-count:]


def _name(index):
    return f"note-{index + 1:04d}"


def _describe(note):
    return " ".join(note["text"].split())[:DESCRIPTION_CHARS]


def _document(note):
    # A JSON string is also a valid YAML string, so no quoting rules of our own are needed.
    last = note.get("last", note["t"])
    return (f"---\ntype: Diary Note\ndescription: {json.dumps(_describe(note))}\n"
            f"generated: {{ by: {ACTOR}, at: {json.dumps(last)} }}\nfirst_written: {json.dumps(note['t'])}\n"
            f"times_written: {note.get('times', 1)}\n---\n\n{note['text']}\n")


def _index(notes):
    lines = [f"* [{_name(i)}](notes/{_name(i)}.md) - {_describe(note)}" for i, note in enumerate(notes)]
    return "---\nokf_version: \"0.2\"\n---\n\n# Notes\n\n" + "".join(line + "\n" for line in lines)


def _log(notes):
    events = [(note["t"][:10], f"* **Creation**: [{_name(i)}](notes/{_name(i)}.md)") for i, note in enumerate(notes)]
    events += [(note.get("last", note["t"])[:10], f"* **Update**: [{_name(i)}](notes/{_name(i)}.md), written {note.get('times', 1)} times")
               for i, note in enumerate(notes) if note.get("times", 1) > 1]
    text = "# Update log\n"
    for day in sorted({day for day, _ in events}, reverse=True):
        text += f"\n## {day}\n" + "".join(entry + "\n" for when, entry in events if when == day)
    return text


def write_bundle(folder, notes):
    """Make the folder match the list exactly, including removing files a repeated tick no longer has."""
    folder = Path(folder)
    (folder / "notes").mkdir(parents=True, exist_ok=True)
    wanted = {f"{_name(i)}.md" for i in range(len(notes))}
    for path in (folder / "notes").glob("note-*.md"):
        if path.name not in wanted:
            path.unlink()
    for index, note in enumerate(notes):
        (folder / "notes" / f"{_name(index)}.md").write_text(_document(note))
    (folder / "index.md").write_text(_index(notes))
    (folder / "log.md").write_text(_log(notes))
    return folder
