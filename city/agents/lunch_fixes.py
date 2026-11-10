"""Behavior fixes for the lunch (city/agents/lunch_wm.py), each behind a switch that is off by default (P5, see
docs/fable_log/P5.md for the measured effect of each):

  --fixes memory    the prompt keeps the conversation so far (both voices), and a diary note that only restates one of
                    the last three is dropped. Before, "What you heard" was emptied after every decision, so Mara forgot
                    Iris's answer one step later and asked about the bees again.
  --fixes repeats   a line nearly the same as one of the speaker's own last four, or the other's last two, is sent back
                    to Qwen as a bad reply (out/bodies/demo/runs/wm: Mara said the same sentence three times).
  --fixes loops     walking up to someone already within arm's length is refused with a note instead of re-run, and a
                    pick-up of a bowl someone holds or that is out of reach is refused (both picked up lunch_bowl_1).
  --decide-on-change  an idle mind with nothing pending decides only when its painted frame changed, or after
                    QUIET_STEPS quiet steps; before, every idle mind asked Qwen every step.
"""
import difflib
import re

FIXES = ("memory", "repeats", "loops")
SAME_LINE = 0.75     # difflib ratio at or above which two lines count as the same line
TALK_SHOWN = 10      # conversation lines kept in the prompt
FRAME_CHANGE = 6.0   # mean absolute difference (0-255, 64x36 grey) above which a frame counts as changed
QUIET_STEPS = 3      # an idle mind with nothing new still decides after this many quiet steps


def parse_fixes(text):
    names = {f.strip() for f in (text or "").split(",") if f.strip()}
    if "all" in names:
        return set(FIXES)
    bad = names - set(FIXES)
    if bad:
        raise ValueError(f"unknown fix {sorted(bad)}; choose from {FIXES} or all")
    return names


def norm(text):
    return re.sub(r"[^a-z0-9 ]+", "", str(text).lower().replace("’", "'")).split()


def similarity(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def repeated(text, mine, theirs):
    """The earlier line `text` repeats (one of mine[-4:] or theirs[-2:]) and whose it was, or None."""
    for whose, lines in (("you", mine[-4:]), ("other", theirs[-2:])):
        for line in reversed(lines):
            if similarity(text, line) >= SAME_LINE:
                return whose, line
    return None


def restates(note, diary):
    """True when a diary note only restates one of the last three notes (they carry a "[clock] " prefix)."""
    return any(similarity(note, d.split("] ", 1)[-1]) >= SAME_LINE for d in diary[-3:])


def frame_diff(a, b):
    """Mean absolute grey difference between two frame files, at 64x36. Missing frames count as changed."""
    if not a or not b:
        return 255.0
    if a == b:
        return 0.0
    import numpy as np
    from PIL import Image
    x, y = (np.asarray(Image.open(p).convert("L").resize((64, 36)), np.float32) for p in (a, b))
    return float(np.abs(x - y).mean())
