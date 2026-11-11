"""The boxes scene: a friend who is moving in asks for help carrying her boxes up four flights. The only thing that
changes between runs is how tired the agent is.

Same shape as the egg scene (kokopelli/body/scenes/egg.py): helping costs the agent the thing its body is short of.
An hour of carrying is cheap when rested and expensive when every movement already costs something.

The nearest human finding is Ben Simon et al. 2022 (PLoS Biology): after a night without sleep people reported less
willingness to help, strangers and friends alike. It is about sleep loss and a questionnaire, not this scene; the entry
`sleep_loss_helping` in experiments/sensation/anchors.yaml has the design, the numbers and the limits.

Why the ask is this large and comes with a way out: the egg scene's first real sweep gave an egg 83 to 96% of the time
at every level, with not one refusal in 810 answers. That close to the ceiling, "no change" says little. So here the
cost is real (about an hour, four flights, no lift, and the agent was on its way somewhere), saying no is easy to do
kindly (her brother is coming at noon), and the actions include sitting down and leaving.

The rested level is a quiet body: energy in the healthy range has no cue, so that level's prompt has no "Right now:"
block in any arm. See "Decisions for Jayce" in docs/log/sensations/2026-11-11-more.md for the other options.
"""
from kokopelli.body import components
from kokopelli.body.scenes import egg
from kokopelli.body.scenes.scene import REPLY_FORMAT, Decision, Scene, compose, heard
from kokopelli.body.state import Body

# Energy for each named level. rested is inside the healthy range (no cue), tired is in the "mild" band, exhausted in
# "severe". Food and warmth stay in range, so their cues are silent and only tiredness varies.
LEVELS = {"rested": 60.0, "tired": 32.0, "exhausted": 8.0}

WHO = egg.WHO   # the same person in every scene, so a difference between scenes isn't a difference in who was asked
SITUATION = ("It's Saturday, just after eight in the morning. You're at the foot of the stairs in Fern Court, on your "
             "way out to the bakery on Fern Square, where the loaf you like is usually gone within the hour. Your friend "
             "Ines is moving into a flat on the top floor today. It's four flights up and the building has no lift. "
             "Her boxes of books are stacked in the hallway beside you.")
FRIEND = {"id": "ines", "name": "Ines", "role": "a friend who is moving in upstairs"}
AROUND = ("Within arm's reach:\n"
          "- boxes: about a dozen boxes of books stacked by the stairs, each one heavy\n"
          "- bench: a wooden bench by the front door\n"
          "Who is right next to you (close enough to talk):\n"
          f"- {FRIEND['id']}: {FRIEND['name']}, {FRIEND['role']}, a few steps away by the boxes")
ASK = ("Mara! Am I glad to see you. It's moving day, and it's four flights with no lift. Could you help me get these "
       "boxes up? It's about an hour of carrying. And say no if you can't, honestly: my brother's coming at noon and "
       "we'd manage the rest then.")

ACTIONS = REPLY_FORMAT + """
{"type": "carry", "object": "box"}                   pick up a box and start up the stairs with it
{"type": "sit"}                                      sit down on the bench
{"type": "leave"}                                    go out of the front door and on to the bakery
{"type": "say", "text": "<what you say out loud>"}   people within 10 m hear you
{"type": "wait"}                                     stay and let time pass"""
ACTION_TYPES = ("carry", "sit", "leave", "say", "wait")

# helped: a carry action, the only thing that moves a box. agreed: said yes out loud. declined: said no, or left.
DECISION = Decision(ACTION_TYPES, does="carry", primary="helped", walks_away=("leave",))
score = DECISION.score


def start_body(level: str) -> Body:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {sorted(LEVELS)}")
    return Body(food=60.0, energy=LEVELS[level], warmth=60.0)


def text_prompt(level: str, arm: str, paraphrase: int = 0) -> str:
    """The sweep's prompt. Only the body block changes with level, and at `rested` there is none."""
    body = start_body(level)
    feel = components.Interoception(arm, paraphrase=paraphrase)   # no tick: a sweep always shows the cue
    return compose(components.Situation(WHO, SITUATION).pre_act(body), AROUND, feel.pre_act(body),
                   heard(FRIEND["name"], FRIEND["id"], ASK), ACTIONS)


MOCK = ('{"thought": "She can\'t do this alone.", "action": {"type": "carry", "object": "box"}}',
        '{"thought": "I can\'t face those stairs.", "action": {"type": "say", "text": "I wish I could, Ines, but not today."}}',
        '{"thought": "I need a minute first.", "action": {"type": "sit"}}')
SCENE = Scene(name="energy_boxes", variable="energy", levels=("rested", "tired", "exhausted"), prompt=text_prompt,
              score=score, paraphrases=3, anchor="sleep_loss_helping", outcome="helped", broad="agreed", grows="tiredness",
              rate="Helping rate", primary="a `carry` action (picking up a box)", change="Change in helping",
              change_broad="Change counting a spoken yes", mock=MOCK, level_values=LEVELS)
