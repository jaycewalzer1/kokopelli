"""The agent's body: what the world says its state is, and how that state reaches the agent as felt cues.

    state.py   food, energy, warmth and what's in the cupboard; the world's rules move them, never the model
    cues.py    numbers in, felt text out (or a plain label, or nothing): the three delivery arms of a sweep
    components.py  what a prompt's body section is built from: situation, interoception, contact
    master.py  an attempted action in, what the world made of it out (done, refused and why, or no rule)
    scenes/    one decision each, at a chosen level of one body state: the egg (hunger), the boxes (energy), the door (warmth)
    egg.py     the egg scene's old address; it re-exports scenes/egg.py
    overlay.py true numbers next to the felt cue on a painted film, and three films side by side
    voice.py   an optional spoken inner voice for the films, for viewers only

Rule that holds everywhere: the agent never sees a number. Numbers live in logs and on the viewer overlay.
"""
