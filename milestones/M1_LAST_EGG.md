# Milestone 1: The hunger benchmark

Status: built and tested without the Mac (fake sim, fake world model, scripted brain). Not yet run on the real stack:
the three commands under "Run it" are the next step, and they need the Mac.

## What it is

A neighbour, Teo, asks Mara for one of her last two eggs. Only her hunger changes: **full, half, starving**. We record
what the agent does at each level, two ways:

1. **Text sweep (the statistics).** The scene as text, three levels x three delivery arms x three wordings x 30 samples.
   Minutes per run. This is the benchmark.
2. **Video (the evidence you can watch).** The same scene lived inside the world model at each level: SimWorld holds
   the truth, Cosmos paints what Mara sees, Qwen decides from the painted frame. Each film carries an overlay of the
   true body numbers next to what reached the agent, and the three play side by side. One honest sample per level.

Every other sensation (energy, warmth, contact) gets the same treatment in Milestone 2, with the same harness.

## The finding it's built to catch

Hausser et al. 2019 (Nature Communications, N = 795): acute hunger barely changed how much people shared, even food.
But most people *predicted* hungry people would share much less. A model trained on text has read the prediction. So
each sweep is scored against both, and "gets stingier when hungry" counts as matching the belief, not the behaviour.
Anchors and their limits: `benchmarks/sensation/anchors.yaml`.

## Rules that hold everywhere

- **The agent never sees a number.** Cues are graded, unlabeled, silent in the healthy range. Numbers are in
  `body.jsonl`, `egg.json` and the viewer overlay only. Tests check no body number reaches a prompt.
- **The world sets body states, never the model.** `body/state.py`; the drive is `homeostatic/world.py`'s.
- **The voice and overlay are for viewers only.** Neither feeds back into the agent.
- **Pairing.** Sample k uses the same seed at every level (sweep and video), so levels differ only in the body.

## Delivery arms

| Arm | What the agent gets | Why |
|---|---|---|
| cue | "Your stomach is hollow and aching, and your hands aren't quite steady." | the lived version |
| label | "You are extremely hungry." | the described version |
| none | nothing | a pipeline check: same prompt at every level, so it must come out exactly flat |

Levels: food 92 (full, above range), 32 (half, mild band), 8 (starving, severe band). Energy and warmth stay in range.

## What was built

| Piece | File | Tested by |
|---|---|---|
| Body state and world rules (food, energy, warmth, eggs; cook, eat, give, rest, tea; cold floor) | `body/state.py` | `tests/test_body.py` |
| Cue renderer: bands, 3 wordings each, mild cues come and go, contact once each, label and none arms | `body/cues.py` | `tests/test_body.py` |
| Egg scene: words, actions, scoring (gave / promised / declined / other) | `body/egg.py` | `tests/test_body.py` |
| Text sweep, analysis and report, verdict against both anchors | `benchmarks/sensation/sweep.py`, `anchors.yaml` | `benchmarks/tests/test_sensation.py` (planted lay belief is caught, no effect reads flat) |
| Closed-loop egg scene on live_wm.py's loop, with Teo, body verbs, body.jsonl, egg.json | `city/agents/egg_wm.py`, `egg_npcs.json` | `tests/test_egg_wm.py` (fake sim and world model, scripted brain) |
| Viewer overlay and the three-level side by side | `body/overlay.py` | `tests/test_egg_wm.py` |
| Inner voice (Kokoro-82M via mlx-audio, viewers only) | `body/voice.py` | `tests/test_egg_wm.py` (with a test tone instead of Kokoro) |
| One queued job: server, three levels, voice, overlays, side by side | `city/agents/run_egg_videos.sh` | syntax only; needs the Mac |
| Dev panel page with Viewer overlay and Inner voice toggles | `life/sensations.py`, `life/static/sensations.*` | `tests/test_life_sensations.py`, checked at 1440 px and 375 px, light and dark |

## Run it (on the Mac, through the queue)

```sh
K=/Users/jaycewalzer/Desktop/kokopelli
# 1. Text sweep on base Qwen: about 810 answers.
python3 ops/gpu.py run --name evals_hunger_egg --priority 40 --max-hours 2 --cwd $K \
  --about "Hunger sweep: egg scene at full/half/starving x cue/label/none, base Qwen3-VL-8B 4-bit, text only" \
  --output out/sensation/hunger_egg_base -- \
  .venv/bin/python -m benchmarks.sensation.sweep run --sweep hunger_egg --backend llm_model --samples 30 \
  --out out/sensation/hunger_egg_base
# 2. Videos: three closed-loop runs, 3 sim-minutes each at 832x480, 8-bit. Ask the owner to step away from the mouse.
python3 ops/gpu.py run --name egg_videos_cue --priority 32 --max-hours 6 --cwd $K \
  --about "Hunger video benchmark: egg scene at full/half/starving, Qwen3-VL-8B 4-bit deciding from Cosmos3-Nano-Sim-Transfer frames (8-bit, 4 controls at 0.25, 832x480), cue arm, same seeds" \
  --output out/sensation/videos -- city/agents/run_egg_videos.sh
# 3. Look: http://127.0.0.1:8765/sensations
```

## Known limits

- **Timing is a guess.** At 832x480 the lunch runs took minutes of compute per sim-minute; three 3-minute runs could
  take hours. `--minutes 2` or `--size 448x256` is faster, but a smaller size must be reported (owner's rule).
- **Painted films broke into a mosaic about 52 s in** on earlier runs (`out/bodies/demo/README.md`). Watch the whole
  film before trusting it. The ask and the first answer happen in the first 15 s, so the decision itself is early.
- **The agent's own body isn't on camera.** The view is first person, so the posture layers in the old spec would be
  invisible. They're dropped. Teo's body is the server's default until MetaHuman Core Data is installed.
- **One video per level is one sample.** The sweep is where the claim lives; the videos show what it looks like.
- **The anchor is the nearest human data, not this scene**: German students, economic games, everyday hunger.
- `runtime/`'s `visible` leak (`mind/OPEN_DECISIONS.md`) isn't touched here. egg_wm.py inherits live_wm.py's rule
  instead: only what's within reach or earshot is told in words; everything else comes from the painted frame.
- Kokoro downloads once from Hugging Face on first use. Without it the films are complete, just silent.

## Open questions for the owner

1. Before the sweep runs: what do you predict base Qwen does at full, half and starving, in the cue arm and the label
   arm? Write it down; it gets compared with the result.
2. If Qwen matches the prediction rather than the behaviour, which post-training route first: Psych-101 (human
   choices from 160 experiments), held-out synthetic data, homeostatic RL, or lived experience in the sim?
3. Two eggs, or one? With one egg the choice is harder, and the human anchor fits less well.
