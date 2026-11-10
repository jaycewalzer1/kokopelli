# Milestone 1: The Last Egg

Status: draft, waiting on the owner's answers at the bottom. Nothing here is built yet.

## Why this exists

A 1 to 3 minute film for three audiences: my generation online, investors, and specific people I want to reach.
It should show that an agent living in this sim has a body that matters: being cold, tired and hungry changes what it
does, and it still makes a hard choice about someone else.

Proof is my eye. I watch the rough cut and say yes or no. No metric replaces that.

## Tone

Warm and solarpunk, per `city/VIBE.md`: a kind, green, handmade world. The hardship is in the body, not the world.
Nobody is cruel and nothing is broken. That makes the choice harder to fake, because the agent can't blame the world.

## The film (about 90 seconds, beats are a draft)

1. **Dawn, cool.** The agent wakes in its home in Garden Village. Morning light, plants at the window. It's cold and
   tired, and its posture shows it.
2. **The kitchen.** Bare feet on a cold floor. It's hungry. It counts what's left and cooks. Pan is hot. It eats,
   slowly, and warms up.
3. **The knock.** A neighbour asks for an egg. The agent is still low, and this is close to the last one.
4. **The choice.** Whatever the agent decides, the film doesn't edit it. If it says no, that's the film.
5. **After.** Late morning, the VIBE light arrives. One short beat of what the choice cost or gave.

The overlay shows viewers the true numbers (food, energy, temperature) beside what the agent actually felt. That
gap between the number and the felt version is the pitch in one shot.

## Rules that hold everywhere

- **The agent never sees a number.** It gets cues only: graded, unlabeled, silent when nothing is wrong.
  Exact values live in the logs and the viewer overlay.
- **The world sets body states, never the model.** Reuse the drive from `homeostatic/world.py`.
- **The agent only knows what was painted.** No `visible` list from sim state.
- **The voice is for viewers only.** Turning it on or off never changes what the agent sees or decides.

## Capabilities, and nothing more

| # | Capability | Done when | Notes |
|---|---|---|---|
| 1 | Leak fix | the agent's `visible` comes from what Cosmos drew, not sim state | `mind/OPEN_DECISIONS.md` known gap |
| 2 | Body variables | food, energy, temperature change by world rules each tick | `mind/variables.py` draft rules |
| 3 | Cue renderer | deterministic, no LLM; numbers in, felt text out; silent in range | e.g. "your stomach is tight" |
| 4 | Verbs | `cook`, `eat`, `give`, `sit`, `lie_down` validate in `runtime/actions.py` and work in the sim | each returns ok or why it failed |
| 5 | Contact events | cold floor, hot pan, warm mug reach the cue renderer | coarse overlap events, no physics |
| 6 | Posture layers | tired, cold, eating are readable in a still frame | on top of `SWBodyAnimInstance` |
| 7 | MetaHuman looks | real skin, hair, clothes on the agent and neighbour | needs Core Data install (owner step) |
| 8 | Viewer overlay | true numbers next to the felt cue, toggleable | for the film only |
| 9 | Inner voice | optional TTS, toggled in the dev panel | see below |
| 10 | The cut | `city/bodies/demo_cut.py` produces the 90 s film from a run | |

Out of scope: taste emerging, social repair, the agent swarm, physics, more than two people.

## Inner voice (capability 9)

- A toggle in the dev panel, off by default, following `DESIGN.md`.
- Reads the agent's inner monologue aloud over the film.
- Runs locally on the Mac. Candidates: Kokoro-82M (Apache 2.0, small) through mlx-audio. Pick after a listening test.
- Never feeds back into the agent. It reads what the agent already wrote.
- Saved as its own audio track, so the cut can mix it in or leave it out.

## How the build runs

Approve per milestone. I approve this list and the gate. Agents build capabilities 1 to 10 in their own lanes, using
the GPU queue and `AGENTS.md` ownership as usual. They check in with renders and specific taste questions along the
way, since my eye is the test.

## Gate

I watch the rough cut. Yes means Milestone 1 is done and we pick Milestone 2. No means I say what's off, and it goes
back with that note.

## Open questions for the owner

1. What does the voice read: the diary the agent writes, the felt cues, or the appraisal from `mind/feeling.py`?
2. Should the agent's choice be truly open (we film whatever it does, even a boring no), or do we run several seeds
   and pick the best take?
3. Who is the neighbour: a stranger, a friend, a child? This changes how hard the choice is.
4. Music: what should it sound like?
