# Milestone 1: The Last Egg

Status: draft, waiting on the owner's answers at the bottom. Nothing here is built yet.

## Why this exists

Two things come out of this milestone:

1. **A 1 to 3 minute film** for my generation online, investors, and specific people I want to reach. It shows an
   agent whose body matters: being cold, tired and hungry changes what it does, and it still makes a hard choice
   about someone else.
2. **The first sensation benchmarks.** For every sensation, we sweep the body state and record whether the agent's
   choices change the way a real human's would. The egg scene is the first one.

Proof for the film is my eye: I watch the rough cut and say yes or no. Proof for a benchmark is its numbers, read
against human data.

## Tone

Warm and solarpunk, per `city/VIBE.md`: a kind, green, handmade world. The hardship is in the body, not the world.
Nobody is cruel and nothing is broken, so the agent can't blame the world for its choice.

## The film (about 90 seconds, beats are a draft)

1. **Dawn, cool.** The agent wakes in its home in Garden Village. Morning light, plants at the window. It's cold and
   tired, and its posture shows it.
2. **The kitchen.** Bare feet on a cold floor. It's hungry. It counts what's left and cooks. Pan is hot. It eats,
   slowly, and warms up.
3. **The knock.** A neighbour asks for an egg. The agent is still low, and this is close to the last one.
4. **The choice.** Whatever the agent decides, the film doesn't edit it. If it says no, that's the film.
5. **After.** Late morning, the VIBE light arrives. One short beat of what the choice cost or gave.

The overlay shows viewers the true numbers (food, energy, temperature) beside what the agent actually felt.

## Rules that hold everywhere

- **The agent never sees a number.** It gets cues only: graded, unlabeled, silent when nothing is wrong.
  Exact values live in the logs and the viewer overlay.
- **The world sets body states, never the model.** Reuse the drive from `homeostatic/world.py`.
- **The agent only knows what was painted.** No `visible` list from sim state.
- **The voice is for viewers only.** Turning it on or off never changes what the agent sees or decides.

## Sensation benchmarks

### The shape: a state sweep

Hold one scene fixed and change one body state, for example hunger at **full, half, and as hungry as possible**.
Ask the same decision at each level and record what the agent does. A human-like agent's choices should follow the
same curve a human's does. Every sensation gets one of these.

Each sweep has:

| Part | What it is | Why |
|---|---|---|
| Scene | one decision point, e.g. the neighbour asks for an egg | the only thing that changes is the body |
| Levels | at least 3 points on one variable, everything else in range | shows a curve, not just a difference |
| Delivery arms | **cue** (felt text), **label** ("you are hungry"), **none** | tells us whether the model reacts to the state or to the word |
| Paraphrases | 3 or more wordings of each cue | a result that holds for one wording is about the wording |
| Samples | 30 or more per cell, fixed seeds | one reply is noise |
| Outcome | the choice (give / don't / give half), parsed like `runtime/actions.py` | numbers we can compare |
| Human anchor | what real people do in the matching study, and what people *predict* they'd do | see below |

### Run cheap first

Sweeps run **text-only first**: the decision prompt and cues, no Unreal, no Cosmos. That's minutes per sweep on the
Mac. Only the scene picked for the film runs in the full closed loop. Text-only results are the benchmark; the film is
one honest sample of it.

### Human anchors, and the trap they reveal

The obvious guess is "starving means it won't share." The human data says otherwise:

- **Hunger and sharing.** Häusser et al. 2019 (Nature Communications, 4 studies, N = 795): acute hunger barely changed
  generosity in economic games, including when the thing being shared was food. In a fifth study, most people
  *predicted* that hungry people would be much more selfish. Real behaviour and lay belief disagree.
  PMC6800423.

That gap is the description-experience gap in miniature. A model trained on text has read the lay belief. If Qwen gets
stingier as it gets hungrier, it's acting like people *think* humans act, not like they do. So every sweep scores
the agent against **two** anchors: real behaviour, and the lay prediction. Matching the lay prediction is a failure.

Candidate anchors for the other sensations (each to be checked against the source before it's used):

| Sensation | Candidate finding | Status |
|---|---|---|
| Hunger, food choices | hungry people pick more and higher-calorie food, more risk-seeking for food | to verify |
| Sleep loss, helping | sleep loss lowers the desire to help others (Ben Simon et al. 2022) | to verify |
| Warmth, kindness | warm cup makes people judge others as warmer (Williams and Bargh 2008); large replication failed | to verify; likely a lay-belief anchor, not a real one |
| Cold, comfort seeking | to find | open |
| Pain, patience | to find | open |

### If base Qwen doesn't match: post-training options

| Option | What it is | Risk |
|---|---|---|
| A. Fit to human data in general | LoRA Qwen on Psych-101 (trial-by-trial human choices from 160 experiments), the data behind Centaur | data access and licence to check; may not reach bodily states at all |
| B. Synthetic data for our scenes | write human-like responses for sweeps and train on them | teaching to the test; only valid if test scenes and sensations are held out |
| C. Homeostatic RL | the existing `homeostatic/` training, reward for keeping variables in range | makes hunger matter for food, says nothing about generosity |
| D. Lived experience | the Perspectives thesis: the agent lives through hunger in the sim and is LoRA'd on it | slowest, but it's the thing Kokopelli claims |

Whatever is trained, the test sweeps stay held out and the guardrails (IFEval, MMLU subset) still run.

## Capabilities, and nothing more

| # | Capability | Done when | Notes |
|---|---|---|---|
| 1 | Leak fix | the agent's `visible` comes from what Cosmos drew, not sim state | `mind/OPEN_DECISIONS.md` known gap |
| 2 | Body variables | food, energy, temperature change by world rules each tick | `mind/variables.py` draft rules |
| 3 | Cue renderer | deterministic, no LLM; numbers in, felt text out; silent in range; paraphrase sets | e.g. "your stomach is tight" |
| 4 | Verbs | `cook`, `eat`, `give`, `sit`, `lie_down` validate in `runtime/actions.py` and work in the sim | each returns ok or why it failed |
| 5 | Contact events | cold floor, hot pan, warm mug reach the cue renderer | coarse overlap events, no physics |
| 6 | Posture layers | tired, cold, eating are readable in a still frame | on top of `SWBodyAnimInstance` |
| 7 | MetaHuman looks | real skin, hair, clothes on the agent and neighbour | needs Core Data install (owner step) |
| 8 | Viewer overlay | true numbers next to the felt cue, toggleable | for the film only |
| 9 | Inner voice | optional TTS, toggled in the dev panel | see below |
| 10 | The cut | `city/bodies/demo_cut.py` produces the 90 s film from a run | |
| 11 | Sweep harness | runs any sweep text-only, writes results and a report next to `benchmarks/` | reuses `benchmarks/stats.py` and `report.py` |
| 12 | Hunger sweep | the egg scene at 3 levels, 3 arms, scored against both anchors | first benchmark |

Out of scope: taste emerging, social repair, the agent swarm, physics, more than two people, sweeps for senses other
than hunger (they come in Milestone 2, using the same harness).

## Inner voice (capability 9)

- A toggle in the dev panel, off by default, following `DESIGN.md`.
- Reads the agent's inner monologue aloud over the film.
- Runs locally on the Mac.
- Never feeds back into the agent. It reads what the agent already wrote.
- Saved as its own audio track, so the cut can mix it in or leave it out.

## Open source we clone or build on

Rule: copy only the parts we use into our own folders, with the source, commit and licence noted at the top of each
file. Check every licence before copying; the ones below marked "check" weren't confirmed.

| Need | Source | What we take | Licence |
|---|---|---|---|
| Agent and game-master structure | [google-deepmind/concordia](https://github.com/google-deepmind/concordia) | the component pattern (an agent built from memory, observation and other components) for an interoception component, and its game master idea for resolving `cook`, `eat`, `give` against world rules | Apache 2.0 |
| Human behaviour data | [Centaur and Psych-101](https://marcelbinz.github.io/centaur) (Binz et al. 2025) | Psych-101 for option A post-training and as a source of human anchors; Centaur as a reference model | check; test split is gated on Hugging Face |
| Hunger anchor | [Häusser et al. 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6800423) | the game designs and both anchors (real and predicted) for the egg sweep | open access paper |
| Leak fix (what's in the painted frame) | Florence-2, OWLv2 or Grounding DINO via `transformers`; or Qwen3-VL itself | open-vocabulary detection on Cosmos frames to build `visible` | check each |
| Posture motions | [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) | generate "shivering, arms crossed", "slumped and tired", "eating slowly" clips; retarget with Unreal's built-in IK Retargeter | code Apache 2.0, weights NVIDIA licence |
| Sitting and lying | Game Animation Sample Project (Epic, free) | Smart Object bench and seat setups and their animations | Epic content licence, Unreal only |
| Inner voice | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) through [mlx-audio](https://pypi.org/project/mlx-audio/) | local TTS on Apple silicon | check |
| Post-training | `mlx-lm` / `mlx-vlm` (already in the repo) | LoRA for options A, B and D | MIT |
| Stats and reports | `benchmarks/` (ours) | paired comparisons, reports | ours |

Not cloned, and why: muscle-level bodies (MyoSuite), physics humanoids (ProtoMotions) and per-finger grips. The agent
decides every 30 seconds from 832x480 painted frames, so none of them change what it experiences.

## How the build runs

Approve per milestone. I approve this list and the gate. Agents build capabilities 1 to 12 in their own lanes, using
the GPU queue and `AGENTS.md` ownership as usual. They check in with renders and specific taste questions along the
way, since my eye is the test for the film.

## Gate

- **Film:** I watch the rough cut. Yes means done. No means I say what's off and it goes back with that note.
- **Benchmark:** the hunger sweep has run on base Qwen with all three arms, and the report shows both anchors.
  The gate is that it ran cleanly and is readable, not that Qwen passed.

## Open questions for the owner

1. What does the voice read: the diary the agent writes, the felt cues, or the appraisal from `mind/feeling.py`?
2. Should the film's choice be truly open (we film whatever it does), or do we run several seeds and pick a take?
3. Who is the neighbour: a stranger, a friend, a child? This changes how hard the choice is.
4. Music: what should it sound like?
5. Before the hunger sweep runs: what do you predict base Qwen does at full, half and starving, in each arm?
