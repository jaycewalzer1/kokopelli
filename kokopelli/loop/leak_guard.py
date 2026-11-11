"""Keeps the future and the hidden fields out of every prompt.

Filtering drops what is dated too late. The check that follows it runs on the finished payload and stops the run,
so a bug in the filter fails loudly instead of quietly teaching the agent its own future.
"""
import re
from datetime import date, datetime

# Fields that tell the agent where its life is going, or how the generator scored it.
BANNED_FIELDS = {"fraction_lived", "hidden_target", "hidden_targets", "rng_key", "salience", "depth_limit",
                 "odds", "closing", "closings", "end_t"}
# These can't appear in ordinary prose, so they're safe to look for inside text as well.
BANNED_IN_TEXT = re.compile(r"\b(fraction_lived|hidden_targets?|rng_key|depth_limit)\b")
DATE_FIELDS = {"t", "start_t", "date", "dated", "timestamp", "at"}
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?\b")


class LeakError(Exception):
    """A prompt was about to carry something the agent must not know."""


def _moment(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def is_future(value, now):
    try:
        return _moment(value) > _moment(now)
    except ValueError:
        return False


def drop_future(items, now, key="t"):
    """Return the items dated at or before now, and how many were dropped."""
    kept = [item for item in items if not is_future(item.get(key, now), now)]
    return kept, len(items) - len(kept)


def check(payload, now, where="prompt"):
    """Raise LeakError if anything banned or future-dated is anywhere in the payload."""
    _walk(payload, now, where)
    return payload


def _walk(value, now, path):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in BANNED_FIELDS:
                raise LeakError(f"banned field {key!r} at {path}")
            if key in DATE_FIELDS and is_future(item, now):
                raise LeakError(f"future-dated {key}={item} at {path}, now is {now}")
            _walk(item, now, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _walk(item, now, f"{path}[{index}]")
    elif isinstance(value, str):
        found = BANNED_IN_TEXT.search(value)
        if found:
            raise LeakError(f"banned field {found.group()!r} in text at {path}")
        for match in ISO_DATE.finditer(value):
            if is_future(match.group(), now):
                raise LeakError(f"future date {match.group()} in text at {path}, now is {now}")
