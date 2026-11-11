"""The components a prompt's body section is built from. A component answers one question and nothing else:

    Situation       who are you, and where? The scene's fixed words.
    Interoception   what does your body feel like from inside? Body numbers in, cue lines out (kokopelli/body/cues.py).
    Contact         what have you touched since you last decided? Each touch reported once.
    Senses          several feeling components under one "Right now:" header, in the order given.

Every component has the same two methods, borrowed from Concordia's components (vendor/concordia_patterns/SOURCE.md):

    pre_act(state)  the text it adds to the prompt before the agent acts, or "" when it has nothing to say
    update(event)   what the loop tells it before a decision: which decision this is, and what the body touched

Why components: the text sweep (kokopelli/body/egg.py) and the closed loop (kokopelli/agents/egg_wm.py) used to assemble
the same words in two places. A new scene picks the components it needs and gets the same words and the same rules (no
numbers, mild cues that come and go) without copying either.

A sweep never sends an event: the tick stays None, so every sample sees the cue. A live loop sends a Moment before each
decision. A component holds only the latest Moment; the body (kokopelli/body/state.py) is what collects touches between
decisions, so there is one place where they pile up and one call (state.touched) that empties it.
"""
from dataclasses import dataclass

from kokopelli.body import cues
from kokopelli.body.state import Body

HEADER = "Right now:"


@dataclass(frozen=True)
class Moment:
    """What a live loop knows just before a decision.

    tick     the decision number, from 0. Mild cues are shown on some ticks and not others. None means "not a live
             run": always show them (a sweep).
    touched  what the body touched since the last decision, in order (keys of the Contact component's words).
    """
    tick: int | None = None
    touched: tuple[str, ...] = ()


def block(lines: list[str]) -> str:
    """The prompt section for some felt lines, or "" for none. The header doesn't name the body or a state."""
    return HEADER + "\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def _known_arm(arm: str) -> str:
    if arm not in cues.ARMS:
        raise ValueError(f"unknown arm {arm!r}; one of {cues.ARMS}")
    return arm


class Component:
    """What every component can do. By default it feels nothing and ignores events, so each one below overrides only
    what makes it different."""

    def lines(self, state: Body) -> list[str]:
        """The bare felt lines, with no header: what Senses joins and what a log keeps."""
        return []

    def pre_act(self, state: Body) -> str:
        return block(self.lines(state))

    def update(self, event: Moment) -> None:
        return None


class Situation(Component):
    """The scene's fixed words: who the agent is and where it finds itself. The same at every level of a sweep, and
    no event changes it."""

    def __init__(self, who: str, situation: str) -> None:
        self.who, self.situation = who, situation

    def pre_act(self, state: Body | None = None) -> str:
        return f"{self.who}\n\nSituation: {self.situation}"


class Interoception(Component):
    """The body felt from inside: food, energy and warmth as cue lines, plain labels, or nothing (the arm).

    paraphrase picks one of a band's wordings (a sweep runs each); None lets the tick pick.
    """

    def __init__(self, arm: str, paraphrase: int | None = None, tick: int | None = None) -> None:
        self.arm, self.paraphrase, self.tick = _known_arm(arm), paraphrase, tick

    def lines(self, state: Body) -> list[str]:
        return cues.sensations(state.values(), self.arm, paraphrase=self.paraphrase, tick=self.tick)

    def update(self, event: Moment) -> None:
        self.tick = event.tick


class Contact(Component):
    """What the body touched since the last decision: a hot pan, a cold floor. Each thing once, in the order it
    happened, and only for the decision that follows it: the next Moment replaces the list.

    words maps a thing to (the felt line, the plain label). A scene with touches of its own passes its own table.
    """

    def __init__(self, arm: str, words: dict[str, tuple[str, str]] | None = None) -> None:
        self.arm = _known_arm(arm)
        self.words = cues.CONTACT if words is None else words
        self.touched: tuple[str, ...] = ()

    def lines(self, state: Body | None = None) -> list[str]:
        if self.arm == "none":
            return []
        which = 0 if self.arm == "cue" else 1
        return [self.words[thing][which] for thing in self.touched if thing in self.words]

    def update(self, event: Moment) -> None:
        self.touched = tuple(dict.fromkeys(event.touched))   # each thing once, first touch first


class Senses(Component):
    """Several feeling components read as one: their lines in the order given, under one header. An event goes to
    every one of them."""

    def __init__(self, *components: Component) -> None:
        self.components = components

    def lines(self, state: Body) -> list[str]:
        return [line for component in self.components for line in component.lines(state)]

    def update(self, event: Moment) -> None:
        for component in self.components:
            component.update(event)
