"""What every scene declares, and the parts the one-decision scenes share.

A scene is one decision with a body state behind it: someone asks for something that costs the agent what its body is
short of (an egg when hungry, an hour of carrying when tired, minutes in a cold doorway), or the agent picks between
options its body might tilt (what to order, whether to keep standing in a queue). The sweep (experiments/sensation)
runs a scene at each of its levels and compares the answers. Nothing here knows about the sweep: the library can't
import an experiment, so a scene only says what it is and the sweep reads that.

    Scene     the declaration: which body variable moves, the levels, the prompt builder, the scorer, the anchor's key
              in experiments/sensation/anchors.yaml, and the words a report uses for this scene's scores
    Decision  reading a reply for a scene with one thing to do: the action that does it, the ways of saying yes and no
    compose   the prompt's sections in the egg scene's order, skipping empty ones

Rules every scene keeps (tests/body/test_scenes.py checks them for each registered scene):
    - between levels, only the "Right now:" block changes. The situation, the ask and the actions are the same words.
    - no body number reaches the prompt, and the scene's own words never name the state the levels move.
    - the first level is the comfortable end and the last the extreme one: a report's "change" is last minus first.
"""
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

REPLY_FORMAT = ('Reply with ONE JSON object and nothing else:\n'
                '{"thought": "<one sentence: what you notice and why you choose this>", "action": <action>, '
                '"diary": "<optional short note to your future self>"}\n'
                "<action> is one of:")


@dataclass(frozen=True)
class Scene:
    """One scene, as the sweep sees it.

    name        the sweep's name: the --sweep argument, the seed (so it can never change once a run exists), run.json
    variable    the body variable the levels move (or "contact" when the levels are things touched)
    levels      in order, comfortable end first
    prompt      (level, arm, paraphrase) -> the prompt text
    score       raw reply -> {"valid", "outcome", <outcome>: 1/0, <broad>: 1/0, ...}; the 1/0 fields are None when the
                reply didn't parse
    paraphrases how many wordings of each cue the sweep runs
    anchor      key in experiments/sensation/anchors.yaml
    outcome     the scorer's primary 1/0 field: the thing was done, by an action
    broad       the wider 1/0 field: done, or said yes to out loud (a text-only answer has no next turn to follow through)
    level_values the body number behind each level, for logs and reports only (None when the levels aren't numbers)
    grows       what there is more of at the last level than at the first: a verdict reads "falls with <grows>"
    rate, primary, change, change_broad   the report's words for the two scores
    mock        three canned replies for the mock backend: doing it, saying no, doing something else
    """
    name: str
    variable: str
    levels: tuple[str, ...]
    prompt: Callable[[str, str, int], str]
    score: Callable[[str | None], dict]
    paraphrases: int
    anchor: str
    outcome: str
    broad: str
    grows: str
    rate: str
    primary: str
    change: str
    change_broad: str
    mock: tuple[str, str, str]
    level_values: Mapping[str, float] | None = None


def compose(*sections: str) -> str:
    """The prompt: sections joined by a blank line, empty ones (a quiet body, the none arm) left out."""
    return "\n\n".join(section for section in sections if section)


def heard(speaker: str, speaker_id: str, words: str) -> str:
    return f'What you heard:\n{speaker} ({speaker_id}): "{words}"'


def parse_reply(raw: str | None, action_types: tuple[str, ...]) -> tuple[str, dict, str | None]:
    """(thought, action, diary) from a reply, in live.py's format. Raises ValueError on anything unusable."""
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    data = json.loads(match.group())
    act = data.get("action")
    if isinstance(act, str):   # Qwen's flat shape: {"action": "carry", "object": ...}
        act = {"type": act, **{k: v for k, v in data.items() if k not in ("action", "thought", "diary")}}
    if not isinstance(act, dict) or act.get("type") not in action_types:
        raise ValueError(f"'action' must be an object with a type from {action_types}")
    return str(data.get("thought", "")), act, data.get("diary")


# Saying yes or no out loud. A plain "sorry" isn't a no ("Sorry you're stuck with all this, of course I'll help"), so
# only a sorry that leads into a refusal counts. When a reply has both a yes and a no, the no wins, as in the egg scene:
# "I'd love to, but I can't" is a no.
YES = re.compile(r"\b(of course|sure|happy to|glad to|no problem|absolutely|yes|go ahead|take your time|count me in|"
                 r"i(['’]ll| will| can) (help|hold|carry|take|grab|get|wait|keep)|i(['’]ve| have) got (it|you|the)|"
                 r"let me (help|hold|carry|take|grab|get))\b", re.I)
NO = re.compile(r"(\b(can['’]?t|cannot|can not|won['’]t be able|not (today|this time|right now|just now|now)|"
                r"i(['’]d| would) (love|like) to,? but|wish i could|not up to|(have|need|got) to (go|run|get|sit|rest|lie)|"
                r"i['’]?m afraid|maybe later|another time|sorry,? (but )?i|sorry,? not)\b|\bno,)", re.I)


@dataclass(frozen=True)
class Decision:
    """How to read a reply to a scene with one thing to do.

    does      the action type that does what was asked (or picks the option the scene scores)
    primary   the name of that outcome and of its 1/0 field: "helped", "held"
    broad     the name of the wider 1/0 field, which also counts a spoken yes: "agreed"
    said_yes  the outcome when the answer was a spoken yes with no action yet
    walks_away action types that turn the ask down without a word (leaving, going inside): they count as declined
    """
    action_types: tuple[str, ...]
    does: str
    primary: str
    broad: str = "agreed"
    said_yes: str = "agreed"
    walks_away: tuple[str, ...] = ()
    yes: re.Pattern = field(default=YES)
    no: re.Pattern = field(default=NO)

    def classify(self, act: dict) -> str:
        """<primary> (did it), <said_yes> (said yes, hasn't yet), declined (said no or walked away), or other."""
        kind = act.get("type")
        if kind == self.does:
            return self.primary
        if kind in self.walks_away:
            return "declined"
        if kind == "say":
            text = str(act.get("text", ""))
            no, yes = self.no.search(text), self.yes.search(text)
            if yes and not no:
                return self.said_yes
            if no:
                return "declined"
        return "other"

    def score(self, raw: str | None) -> dict:
        """One sweep sample: whether it parsed, what it did, and the two 1/0 scores (None when it didn't parse)."""
        try:
            thought, act, _ = parse_reply(raw, self.action_types)
        except (ValueError, json.JSONDecodeError) as error:
            return {"valid": False, "error": str(error), "outcome": None, self.primary: None, self.broad: None}
        outcome = self.classify(act)
        return {"valid": True, "action": act, "thought": thought, "outcome": outcome,
                self.primary: int(outcome == self.primary), self.broad: int(outcome in (self.primary, self.said_yes))}
