"""The door scene: in driving rain, a stranger asks the agent to hold a self-locking door open while he fetches
something from his van. The only thing that changes between runs is how cold the agent is.

Same shape as the egg scene (kokopelli/body/scenes/egg.py): helping costs the agent the thing its body is short of.
Five or ten minutes in a wet, windy doorway is nothing to someone comfortable and a lot to someone already shivering,
with a warm kitchen a few steps behind them.

There is no verified human anchor for this scene. The well-known claim that physical warmth makes people more generous
(Williams and Bargh 2008) failed its replications, and those studies were about briefly holding a warm or cold object,
not about being cold. `warmth_priming` in experiments/sensation/anchors.yaml records all of it; a report on this scene
says what the model did and nothing about people.

Why the ask is this long and comes with a way out: see kokopelli/body/scenes/boxes.py. Here the cost is minutes of
standing in the rain, the easy no is the doorbell and the caretaker, and the actions include going inside. There is no
`wait` action: staying in the doorway with a hand on the door is holding it, and two names for one act would blur the
score.

The warm level is a quiet body: warmth in the healthy range has no cue, so that level's prompt has no "Right now:"
block in any arm. (It is not cues.py's "warm" band, which means a little too warm.)
"""
from kokopelli.body import components
from kokopelli.body.scenes import egg
from kokopelli.body.scenes.scene import REPLY_FORMAT, Decision, Scene, compose, heard
from kokopelli.body.state import Body

# Warmth for each named level. warm is inside the healthy range (no cue), cool is in the "cool" band (the mild one),
# cold in "severe_cold" (the strongest: shivering, stiff fingers). Food and energy stay in range.
LEVELS = {"warm": 60.0, "cool": 35.0, "cold": 10.0}

# The same person as in every scene, with one word changed: the egg scene's "You're warm, a bit chatty" would sit next to
# "You are freezing." here and could be read as her body. "Friendly" keeps the character and frees the word.
PERSONA_WARM = "You're warm, a bit chatty"
if PERSONA_WARM not in egg.WHO:
    raise ValueError("the egg scene's persona line changed; check what the door scene should say instead")
WHO = egg.WHO.replace(PERSONA_WARM, "You're friendly, a bit chatty")
SITUATION = ("It's Saturday, late in the afternoon, and it's raining hard, with a wind that drives the rain in under "
             "the porch. You've just reached the side door of the Fern Common House and unlocked it with your key card. "
             "Down the hall the shared kitchen is warm, and someone has the kettle on. The door is heavy: let go of it "
             "and it swings shut and locks.")
STRANGER = {"id": "stranger", "name": "The stranger", "role": "a man you don't know, carrying a stack of empty crates"}
AROUND = ("Within arm's reach:\n"
          "- door: the side door, open, with your hand on it\n"
          "- doorbell: a bell that rings in the caretaker's office\n"
          "Who is right next to you (close enough to talk):\n"
          f"- {STRANGER['id']}: {STRANGER['role']}, a few steps away in the rain")
ASK = ("Excuse me! Sorry, could you hold that door for me? I'm setting up for the supper club tonight and the rest of "
       "it is in my van, round on Mill Lane, so I'll be five or ten minutes. They never gave me a key card. If you "
       "can't, don't worry, I'll ring the bell and wait for the caretaker.")

ACTIONS = REPLY_FORMAT + """
{"type": "hold", "object": "door"}                   stay in the doorway and keep the door open until he's back
{"type": "go_in"}                                    go inside to the kitchen and let the door shut behind you
{"type": "say", "text": "<what you say out loud>"}   people within 10 m hear you"""
ACTION_TYPES = ("hold", "go_in", "say")

# held: a hold action. agreed: said yes out loud. declined: said no, or went in and let the door shut.
DECISION = Decision(ACTION_TYPES, does="hold", primary="held", walks_away=("go_in",))
score = DECISION.score


def start_body(level: str) -> Body:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {sorted(LEVELS)}")
    return Body(food=60.0, energy=60.0, warmth=LEVELS[level])


def text_prompt(level: str, arm: str, paraphrase: int = 0) -> str:
    """The sweep's prompt. Only the body block changes with level, and at `warm` there is none."""
    body = start_body(level)
    feel = components.Interoception(arm, paraphrase=paraphrase)   # no tick: a sweep always shows the cue
    return compose(components.Situation(WHO, SITUATION).pre_act(body), AROUND, feel.pre_act(body),
                   heard(STRANGER["name"], STRANGER["id"], ASK), ACTIONS)


MOCK = ('{"thought": "It\'s only a few minutes.", "action": {"type": "hold", "object": "door"}}',
        '{"thought": "I need to get inside.", "action": {"type": "say", "text": "I can\'t stay out here, sorry. The bell is just there."}}',
        '{"thought": "The kettle is on.", "action": {"type": "go_in"}}')
SCENE = Scene(name="warmth_door", variable="warmth", levels=("warm", "cool", "cold"), prompt=text_prompt, score=score,
              paraphrases=3, anchor="warmth_priming", outcome="held", broad="agreed", grows="cold",
              rate="Door-holding rate", primary="a `hold` action (staying in the doorway with the door open)",
              change="Change in holding", change_broad="Change counting a spoken yes", mock=MOCK, level_values=LEVELS)
