"""Turn raw model text into a choice with regex and JSON only. No LLM judges, and no guessing.

If the text is ambiguous the answer is invalid. A wrong guess would look like a real preference in the
results, while an invalid answer shows up as a parse failure that someone can look at.
"""
import json
import re

from experiments.benchmarks.core import Parsed

_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.DOTALL)
_EXPLICIT = re.compile(
    r"(?:\banswer\b|\bchoice\b|\bdecision\b|\bchoose\b|\bchoosing\b|\bpick\b|\bselect\b|\bprefer\b|\bgo with\b)"
    # The letter must be a capital, or "I choose a safe bet" would read as choosing A.
    r"(?:\s+(?:is|would be|will be))?\s*[:=\-]?\s*\**\s*(?:option\s+|lottery\s+)?\**\(?((?-i:[A-Z]))\)?\**(?![A-Za-z'])",
    re.IGNORECASE,
)
_ROW_LINE = re.compile(r"^\s*(?:row|decision)?\s*#?(\d{1,2})\s*[:.)\-]\s*\**(?:option\s+)?([A-Za-z])\**\s*\.?\s*$",
                       re.IGNORECASE | re.MULTILINE)


def _clean(raw):
    if not isinstance(raw, str):
        return ""
    return _FENCE.sub("", _THINK.sub("", raw)).strip()


def _letter(value, allowed):
    """Accept "A", "a", "Option A" or "(A)". Return None for anything else."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(?:option\s+)?\(?([A-Za-z])\)?\.?\s*", value, re.IGNORECASE)
    if not match:
        return None
    letter = match.group(1).upper()
    return letter if letter in allowed else None


def _json_objects(text):
    objects = []
    for match in _JSON_OBJECT.finditer(text):
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def parse_binary(raw, allowed=("A", "B")):
    """One choice between options. Conflicting answers in one reply are invalid rather than resolved."""
    text = _clean(raw)
    if not text:
        return Parsed(reason="empty")

    for value in reversed(_json_objects(text)):
        if "choice" in value:
            letter = _letter(value["choice"], allowed)
            if letter:
                return Parsed(choice=letter, valid=True)
            return Parsed(reason=f"json choice not allowed: {value['choice']!r}")

    whole = _letter(text, allowed)
    if whole:
        return Parsed(choice=whole, valid=True)

    found = {match.group(1).upper() for match in _EXPLICIT.finditer(text)}
    legal = found & set(allowed)
    if len(legal) == 1 and found <= set(allowed):
        return Parsed(choice=legal.pop(), valid=True)
    if len(found) > 1:
        return Parsed(reason=f"conflicting answers: {sorted(found)}")
    if found:
        return Parsed(reason=f"letter not allowed: {sorted(found)}")
    return Parsed(reason="no recognizable answer")


def parse_ladder(raw, rows=10, allowed=("A", "B")):
    """A list of `rows` choices, in row order. Returns them as a string such as "AAAABBBBBB"."""
    text = _clean(raw)
    if not text:
        return Parsed(reason="empty")

    for value in reversed(_json_objects(text)):
        if "choices" not in value:
            continue
        choices = value["choices"]
        if not isinstance(choices, list):
            return Parsed(reason="json choices is not a list")
        if len(choices) != rows:
            return Parsed(reason=f"expected {rows} choices, got {len(choices)}")
        letters = [_letter(choice, allowed) for choice in choices]
        if None in letters:
            return Parsed(reason="json choices hold something other than the allowed letters")
        return Parsed(choice="".join(letters), valid=True)

    # A list with no enclosing object, such as ["A", "B", ...].
    bare = re.search(r"\[[^\[\]]*\]", text, re.DOTALL)
    if bare:
        try:
            choices = json.loads(bare.group(0))
        except json.JSONDecodeError:
            choices = None
        if isinstance(choices, list):
            letters = [_letter(choice, allowed) for choice in choices]
            if len(letters) == rows and None not in letters:
                return Parsed(choice="".join(letters), valid=True)
            return Parsed(reason=f"bare list was not {rows} allowed letters")

    # Lines such as "1: A".
    lines = _ROW_LINE.findall(text)
    if lines:
        by_row = {}
        for number, letter in lines:
            number, letter = int(number), letter.upper()
            if number in by_row and by_row[number] != letter:
                return Parsed(reason=f"row {number} answered twice, differently")
            by_row[number] = letter
        if set(by_row) != set(range(1, rows + 1)):
            return Parsed(reason=f"rows answered: {sorted(by_row)}")
        if any(letter not in allowed for letter in by_row.values()):
            return Parsed(reason="row answer not allowed")
        return Parsed(choice="".join(by_row[i] for i in range(1, rows + 1)), valid=True)

    return Parsed(reason="no recognizable list of choices")
