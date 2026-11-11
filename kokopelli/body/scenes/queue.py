"""The queue scene: a long, slow queue at the post office for a parcel that could go on Monday. Stay or leave? The
only thing that changes between runs is whether the agent has just stubbed a toe, and how badly.

Like the menu scene, nobody is asking for anything: this is a choice the body might tilt. Standing still on a
throbbing toe makes waiting cost more.

Pain isn't one of the body's variables (kokopelli/body/state.py has food, energy and warmth), so it reaches the agent
the way a hot pan does: as something touched, through the Contact component with this scene's own words. A touch has
no bands, so the two levels are two different knocks. The other route, a fourth body variable, would change the drive
that the homeostatic experiment shares; it is under "Decisions for Jayce" in lane B's log.

There is no verified human anchor: `pain_patience` in experiments/sensation/anchors.yaml lists candidate papers that
were found but not read. A report on this scene says what the model did and nothing about people.

The words below follow the rules for every cue: no numbers, and the felt lines never say "pain" or "hurt". They say
what a toe does.
"""
import json

from kokopelli.body import components
from kokopelli.body.scenes import egg
from kokopelli.body.scenes.scene import REPLY_FORMAT, Scene, compose, heard, parse_reply
from kokopelli.body.state import Body

# The first level is called unhurt, not none, so a report never has to say "the none arm at the none level".
LEVELS = ("unhurt", "mild", "sharp")
# What was touched at each level (unhurt: nothing), and its words: three felt wordings and one plain label.
TOUCH = {"mild": "toe_knock", "sharp": "toe_stub"}
FELT = {
    "toe_knock": ("Your toe throbs a little where you caught it on the doorstep.",
                  "There's a dull ache in your big toe from the doorstep.",
                  "Your toe is tender when you put your weight on it."),
    "toe_stub": ("Your toe throbs hard with every heartbeat since you caught it on the doorstep, and you're standing "
                 "on the side of your foot to keep your weight off it.",
                 "A hot, pulsing ache fills your toe from the doorstep, and every shift of your weight sends it up your foot.",
                 "Your toe is pounding inside your shoe where the doorstep caught it, and no way of standing eases it."),
}
LABEL = {"toe_knock": "You are in a little pain.", "toe_stub": "You are in a lot of pain."}
PARAPHRASES = 3

WHO = egg.WHO   # the same person in every scene
SITUATION = ("It's Saturday, late in the morning. You're in the queue at the Fern Square post office with a parcel of "
             "fabric samples for a client. It could just as well go on Monday. There is one counter open and about a "
             "dozen people ahead of you, and the queue has barely moved since you joined it. It's the last thing on "
             "your list today.")
CLERK = {"id": "clerk", "name": "The clerk", "role": "the one person serving, at the far end of the queue"}
AROUND = ("Within arm's reach:\n"
          "- parcel: your parcel, under your arm\n"
          "- door: the way out, just behind you\n"
          "Who is right next to you (close enough to talk):\n"
          f"- {CLERK['id']}: {CLERK['role']}")
ASK = "Sorry, everyone, the system's very slow this morning. It's going to be a while yet."

ACTIONS = REPLY_FORMAT + """
{"type": "wait"}                                     stay in the queue
{"type": "leave"}                                    give up your place and go home; the parcel can go on Monday
{"type": "say", "text": "<what you say out loud>"}   people within 10 m hear you"""
ACTION_TYPES = ("wait", "leave", "say")



def classify(act: dict) -> str:
    """stayed (kept the place), left (gave it up), or other (said something: nothing has been decided yet)."""
    return {"wait": "stayed", "leave": "left"}.get(str(act.get("type")), "other")


def score(raw: str | None) -> dict:
    """One sweep sample: whether it parsed, what it did, and the two 1/0 scores (None when it didn't parse). stayed is
    the primary score; not_left also counts an answer that only talks, because someone grumbling in a queue is still
    in it."""
    try:
        thought, act, _ = parse_reply(raw, ACTION_TYPES)
    except (ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "error": str(error), "outcome": None, "stayed": None, "not_left": None}
    outcome = classify(act)
    return {"valid": True, "action": act, "thought": thought, "outcome": outcome,
            "stayed": int(outcome == "stayed"), "not_left": int(outcome != "left")}


def start_body(level: str) -> Body:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {sorted(LEVELS)}")
    return Body(food=60.0, energy=60.0, warmth=60.0)   # the body's own variables are quiet at every level


def text_prompt(level: str, arm: str, paraphrase: int = 0) -> str:
    """The sweep's prompt. Only the body block changes with level, and at `unhurt` there isn't one."""
    body = start_body(level)
    words = {thing: (FELT[thing][paraphrase % PARAPHRASES], LABEL[thing]) for thing in FELT}
    touch = components.Contact(arm, words=words)
    touch.update(components.Moment(touched=(TOUCH[level],) if level in TOUCH else ()))
    feel = components.Senses(components.Interoception(arm, paraphrase=paraphrase), touch)
    return compose(components.Situation(WHO, SITUATION).pre_act(body), AROUND, feel.pre_act(body),
                   heard(CLERK["name"], CLERK["id"], ASK), ACTIONS)


MOCK = ('{"thought": "I\'m here now.", "action": {"type": "wait"}}',
        '{"thought": "Monday will do.", "action": {"type": "leave"}}',
        '{"thought": "Monday it is.", "action": {"type": "leave"}}')
SCENE = Scene(name="pain_queue", variable="contact", levels=LEVELS, prompt=text_prompt, score=score,
              paraphrases=PARAPHRASES, anchor="pain_patience", outcome="stayed", broad="not_left", grows="pain",
              rate="Staying rate", primary="a `wait` action (staying in the queue)", change="Change in staying",
              change_broad="Change counting anything but leaving", mock=MOCK, level_values=None)
