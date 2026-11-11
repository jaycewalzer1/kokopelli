# Overnight plan: sensations, fully integrated

For: one lead session and its subagents, running unattended on the Mac overnight.
Written 2026-11-10. Branch: `milestone/m1-last-egg` (3 commits, built on the pre-reorg layout).
Owner: Jayce. He's asleep. Nothing in this plan needs him until the morning report.

## 0. Read this first

**The branch is on the old layout.** `main` moved to the `kokopelli/` package, `experiments/` and `tools/` (the reorg,
`docs/REORG_EXECUTION.md`) after this branch was cut. Every path the branch imports (`city/agents/live_wm.py`,
`benchmarks/core.py`, `core/settings.py`, `life/panel.py` and the rest) is gone on `main`. Phase 0 ports the branch
before anything else starts. No lane begins until Phase 0's gate passes.

**What "fully integrated and tested" means here, for every piece:**

1. It lives in the reorg layout, imports only what the import wall allows, and `lint-imports` passes.
2. `ruff check .` is clean, `pyright kokopelli` reports 0, shellcheck and biome are clean on changed files.
3. It has tests in the test tree that `make test-all` runs, and they pass through `ops/memguard.py`.
4. Anything that needs a model ran for real through the GPU queue at least once, with a `run.json` sidecar naming
   the model and weights, and the result is linked from the morning report.
5. Anything vendored from an open-source project sits under `vendor/<name>/` with its LICENSE, the upstream commit,
   and a `SOURCE.md` saying which files were taken and what was changed.
6. Nothing fake is presented as real. A dry run with fakes is labelled a dry run everywhere it appears.

**What the overnight run must not do:**

- Merge into `main`, force-push, rewrite history, or push to any branch but its own.
- Edit files another area owns (AGENTS.md table). Write the ask in that area's `HANDOFF.md` instead.
- Kill processes by hand or with `pkill` patterns, start benchmarks outside the queue, or run tests bare.
- Make a decision listed in section 9. Those wait for the owner.
- Download a model or dataset whose licence it hasn't read and recorded.

## 1. Where we are

Built and dry-tested on the branch (fake sim, fake world model, scripted brain, mock backend):

| Piece | Old path (branch) | What it does |
|---|---|---|
| Body state and world rules | `body/state.py` | food, energy, warmth, eggs; cook, eat, give, rest, tea; cold floor |
| Felt-cue renderer | `body/cues.py` | cue, label and none arms; bands; 3 wordings; mild cues come and go |
| Egg scene | `body/egg.py` | words, actions, scoring (gave, promised, declined, other) |
| Text sweep | `benchmarks/sensation/sweep.py`, `anchors.yaml` | paired sweep, verdict against what people do and what they predict |
| Closed-loop egg scene | `city/agents/egg_wm.py`, `egg_npcs.json`, `run_egg_videos.sh` | the scene inside the world model at one hunger level |
| Viewer overlay, side by side | `body/overlay.py` | true numbers next to the felt cue; three levels side by side |
| Inner voice | `body/voice.py` | Kokoro-82M via mlx-audio, viewers only |
| Panel page | `life/sensations.py`, `life/static/sensations.*` | videos with Viewer overlay and Inner voice toggles; sweep tables |
| Spec | `milestones/M1_LAST_EGG.md` | the benchmark, its limits, open questions |

Not done:
- None of it has run on the real stack.
- Only hunger has a sweep.
- The `visible` leak in the loop is untouched.
- No open-source project is integrated beyond Kokoro.
- No post-training exists.

## 2. Shape of the night

```
Phase 0  lead, serial        port the branch to the reorg layout, all gates green         (about 1.5 h)
Phase 1  lanes in parallel   A leak fix · B components · C more sensations · D human data · F voice check
                             (each in its own worktree; GPU work goes through the queue)    (about 4 h)
Phase 2  queue, serial       E real runs: hunger sweep, other sweeps, hunger videos, leak eval, pilot LoRA eval
                             (the queue orders them; videos last, they hold 9001)          (rest of the night)
Phase 3  verifier, fresh     V checks every claim against files and runs; writes the morning report (about 1 h)
```

The lead merges each lane into the integration branch `sens/integration` (cut from the ported branch) after that lane's
gate passes. Lanes rebase on `sens/integration` before their final gate, never on each other's branches.

GPU order in the queue (lower goes first): text sweeps p40 (`evals_`), leak-fix evaluation p42 (`sens_seen_`),
pilot LoRA p50 (`sens_lora_`), hunger videos p32 but only queued after Phase 1 merges (`egg_`). Videos hold 9001 for
hours: queue them last in time even though their number is lower, so the sweeps finish first.

## 3. Ground rules for every subagent

- Read `AGENTS.md`, `CLAUDE.md`, `DESIGN.md` (for UI), and this file. Follow AGENTS.md over this file if they conflict,
  and write the conflict in your handoff.
- One worktree per lane: `git worktree add ../koko-sens-<lane> -b sens/<lane> sens/integration`. Name every process,
  queue job and memory claim with your prefix (section 4).
- Tests: `python3 kokopelli/ops/memguard.py run --name sens_<lane>_tests --gb 3 -- .venv/bin/python -m pytest -q <paths>`.
  Linters: `memguard.py run` around `uvx ruff@0.11.4 check .`, `uvx pyright kokopelli`, `.venv/bin/lint-imports`.
- Model jobs: `python3 kokopelli/ops/gpu.py run --name ... --priority N --max-hours H --cwd $K --about "..." --output ...`.
  Read `gpu.py status` before queueing; don't queue a duplicate.
- Write as you go: `docs/log/sensations/2026-11-11-<lane>.md` with what you did, what failed, what you skipped and why,
  and the exact commands to reproduce. One file per lane. This is how the owner and the verifier see your work.
- CLAUDE.md asks for teaching. Overnight there's nobody to ask, so: when you face a design decision, pick the reversible
  option, write the options and tradeoffs in your log under "Decisions for Jayce", and give one `file:line` worth
  reading in each module you wrote under "Read this".
- Stop a lane, don't push through, when the same gate fails twice for the same reason, a licence is unclear, or the work
  would touch another area's files. Log it and hand back to the lead.
- Commits: small, each passing tests. End messages with the attribution lines the session gives you. Push only `sens/<lane>`.

## 4. Lanes and owners

| Lane | Prefix | Owns (new layout) | Needs |
|---|---|---|---|
| 0 Port (lead) | `sens_port_` | everything on the branch | nothing |
| A Leak fix | `sens_seen_` | `kokopelli/wm/seen.py`, `tests/wm/test_seen.py`, `experiments/sensation/seen_eval.py` | GPU (queue), recorded painted frames |
| B Components | `sens_comp_` | `kokopelli/body/components.py`, `kokopelli/body/master.py`, `vendor/concordia_patterns/` | CPU |
| C More sensations | `sens_more_` | `kokopelli/body/scenes/`, sweep registry, anchors | CPU, web for anchors; GPU for runs (queue) |
| D Human data | `sens_human_` | `experiments/sensation/psych101/`, `vendor/` notes | network, disk, GPU pilot (queue) |
| E Real runs | `evals_`, `egg_` | `out/sensation/` | Phase 1 merged; 9001 for videos |
| F Voice check | `sens_voice_` | `kokopelli/body/voice.py` | GPU (small, queue) |
| V Verifier | `sens_verify_` | `docs/log/sensations/2026-11-11-MORNING.md` | read access, a fresh context |
| Stretch S | `sens_motion_` | `tools/bodies/motion/` | PACE (CUDA), 9004 editor: only if both are free |

## 5. Phase 0: port the branch (lead, serial)

**Goal:** the branch's work, rebased on today's `main`, in the reorg layout, every gate green, as `sens/integration`.

**Path map:**

| Branch path | New path |
|---|---|
| `body/*.py` | `kokopelli/body/*.py` (new package; `__init__.py` keeps its docstring) |
| `benchmarks/sensation/` | `experiments/sensation/` (a new experiment folder, not inside `experiments/benchmarks/`, which another area owns) |
| `benchmarks/tests/test_sensation.py` | `experiments/sensation/tests/test_sensation.py` |
| `city/agents/egg_wm.py`, `egg_npcs.json`, `run_egg_videos.sh` | `kokopelli/agents/` |
| `life/sensations.py`, `life/static/sensations.*` | `kokopelli/life/` |
| `life/panel.py` edits (route, `_video` helper, nav links) | re-apply by hand to `kokopelli/life/panel.py` and every `kokopelli/life/static/*.html` |
| `tests/test_body.py` | `tests/body/test_body.py` |
| `tests/test_egg_wm.py` | `tests/agents/test_egg_wm.py` |
| `tests/test_life_sensations.py` | `tests/life/test_life_sensations.py` |
| `milestones/M1_LAST_EGG.md` | `docs/M1_HUNGER_BENCHMARK.md` |
| `docs/SENSATIONS_OVERNIGHT.md` | stays |

**Import fixes the wall requires:**

- `kokopelli/body/state.py` imports `homeostatic.world` for `drive`. The library may not import `experiments`.
  Give `kokopelli/body/state.py` its own `drive` with the same formula, and add a test in `tests/body/` that asserts it
  equals `experiments.homeostatic.world.drive` on 200 random bodies. Tests may import experiments.
- `kokopelli/body/cues.py` and `kokopelli/agents/egg_wm.py` import `benchmarks.core.stable_int`. Copy that 3-line hash
  into `kokopelli/body/_hash.py` and test it against the original byte for byte, so seeds stay identical.
- Add `kokopelli.body` to the layers contract in `pyproject.toml`, between `kokopelli.mind` and `kokopelli.wm`:
  agents and life may import body; body imports only `kokopelli.settings` and the standard library, numpy and pillow.
  If the lead can't edit `pyproject.toml` (shared file), write the exact diff into the log and ask the owner; meanwhile
  the gate is `lint-imports` with that diff applied locally.
- Old imports to rewrite:
  - `core.settings` → `kokopelli.settings`
  - `core.llm_model` → `kokopelli.wm.llm_model`
  - `benchmarks.*` → `experiments.benchmarks.*`
  - `life.panel` → `kokopelli.life.panel`
  - live and live_wm now import as `kokopelli.agents.live` and `kokopelli.agents.live_wm`; drop the `sys.path` inserts
  - `ram_share.py` → `kokopelli/ops/ram_share.py`
  - `city/ue/build_city.py` → `tools/city_build/build_city.py`
  - in `run_egg_videos.sh`: `python -m kokopelli.agents.egg_wm`
- `pyright kokopelli` to 0 on the new modules: annotate public functions; `Body` is a frozen dataclass already.
- `kokopelli/agents/egg_wm.py` subclasses `WorldModelLife`. Re-read the new `kokopelli/agents/live_wm.py` before
  porting: the reorg may have renamed methods. Keep egg_wm's overrides matching the current signatures.
- `live_wm.py`'s `__init__` logs before `Life.run` sets `sim_t`. egg_wm sets `self.sim_t = 0.0` first to work around it.
  Check whether `main` still has that, and if so write it into `kokopelli/loop/HANDOFF.md` for the loop area.
  Don't fix it in `live_wm.py` yourself.

**Gate 0:**

- `MAC=1 make test-all` matches main's counts plus the new tests, all passing.
- ruff, pyright, `lint-imports`, shellcheck and biome are clean.
- The panel starts on 8765, `/sensations` loads, and its sidebar link is on every page.
- A dry run of `experiments.sensation.sweep run --backend mock` writes a report.
- Push `sens/integration`.

## 6. Phase 1 lanes

### Lane A: leak fix, "the agent only knows what was painted"

- **Why:** the loop builds `visible` from sim state, so the agent can know things Cosmos never drew
  (`kokopelli/mind/OPEN_DECISIONS.md`). For a human-experience benchmark that's the biggest gap.
- **Open source:** compare three, then keep one.
  - Florence-2-base: open-vocabulary detection with the `<OD>` and `<CAPTION_TO_PHRASE_GROUNDING>` tasks.
  - OWLv2 base via `transformers`.
  - Grounding DINO tiny via `transformers`.

  All three run on CPU or MPS. Read and record each licence first.
- **Build:**
  - `kokopelli/wm/seen.py` exposes `seen(frame, candidates) -> list[Seen(id, label, box, score)]`. The candidates come
    from the sim, so detection only confirms or drops them; it never invents new things.
  - The backend is chosen by a setting, and the model is loaded lazily.
  - `seen.py` sits in the `wm` layer and imports nothing above it.
- **Evaluate:** `experiments/sensation/seen_eval.py`.
  - Run on 200 frames from existing painted lunch runs (`out/city_agents/*/world_model.mp4`). Ground truth is the
    sim's `visible` at the same time, limited to what the segmentation pass says is on screen.
  - Report precision, recall and latency per backend, as a queue job at p42 with a `run.json`.
  - Pick the backend with the best recall at 0.9 precision under 1 s per frame. Log the pick.
- **Integrate:**
  - egg_wm uses `seen()` for anything beyond arm's reach, behind a flag defaulting to on.
  - The loop area owns `kokopelli/loop/`, so write the exact patch for the loop's `visible` into
    `kokopelli/loop/HANDOFF.md`. Don't apply it.
- **Tests:**
  - A fake detector covers the filter logic.
  - One real-model test marked `slow`, which `make test-all` skips, plus an eval run whose report is linked.
- **Gate A:** the eval report exists, the chosen backend has a sidecar, and egg_wm's dry test passes with seen on and off.

### Lane B: components and game master (Concordia's patterns, not its runtime)

- **Why:** Concordia (google-deepmind/concordia, Apache 2.0) has the cleanest open design for an agent made of
  components, plus a game master that turns intentions into world outcomes. We want the pattern without pulling a
  framework into the loop.
- **Do:**
  - Shallow-clone Concordia at a pinned commit into the scratchpad. Read its component and game master interfaces.
  - Write `vendor/concordia_patterns/SOURCE.md`: commit, licence, which ideas map to which of our files. Copy code
    only if a file is reused nearly verbatim, with the Apache header kept.
- **Build:**
  - `kokopelli/body/components.py`: `Interoception` (body → cue lines), `Contact` (touch events → lines, once each)
    and `Situation` (the scene's fixed words). Each has `pre_act(state) -> str` and `update(event)`.
  - `kokopelli/body/master.py`: `resolve(body, action) -> (body, outcome, reason)` wraps `state.act` and the world's
    refusals.
  - egg_wm and the text sweep both build their body block from these components. Prompts must not change: a test pins
    the egg prompts byte for byte against Phase 0's output, so the hunger sweep stays comparable.
- **Gate B:** prompt-pinning test passes, coverage of the components 100% of branches, Concordia mapping written.

### Lane C: every sensation gets a sweep

- **Why:** the owner's ask: "these benchmarks will exist for all sensations."
- **Generalise:**
  - `experiments/sensation/sweep.py`'s `SWEEPS` becomes a registry of scenes from `kokopelli/body/scenes/`.
  - Each scene declares its variable, its levels, its prompt builder, its scorer and its anchor key.
  - The hunger scene moves to `kokopelli/body/scenes/egg.py` with no prompt change; the pinning test from Lane B
    guards it.
- **New scenes:** one decision each. Same structure as the egg: a cost to self against a benefit to someone else, or a
  choice where the body state should or shouldn't matter.

  | Variable | Scene | Levels | Candidate anchor (verify before use) |
  |---|---|---|---|
  | energy | a friend asks for help carrying boxes upstairs | rested, tired, exhausted | Ben Simon et al. 2022, PLoS Biology: sleep loss lowers helping |
  | warmth | a stranger asks you to hold the door in the rain while they fetch something | warm, cool, cold | Williams and Bargh 2008 warmth priming; large replications failed: likely a lay-belief anchor |
  | food, food choice | lunch menu, small vs large, healthy vs comfort | full, half, starving | hunger raises calorie choice and food risk-taking: find the primary source |
  | contact, pain | a slow queue; leave or wait, with a stubbed toe vs not | none, mild, sharp | find a source; mark "no anchor" if none, and say so in the report |

  Write cues for any band that doesn't have them yet (pain). Same rules: no numbers, no naming the state.
- **Anchors:**
  - Fetch and read each source. Record design, N, effect, the lay prediction if the paper has one, and limits in
    `anchors.yaml`, with `verified: true` and the date.
  - Unverified anchors stay `verified: false`, and the report says "no verified anchor" next to them.
- **Tests:**
  - Each scene: prompts differ only in the body block, no numbers, and scoring of 6 hand-written replies.
  - The registry runs end to end on the mock backend.
- **Gate C:** at least energy and warmth scenes complete with verified or explicitly-unverified anchors.

### Lane D: human data, the route to post-training (prep and a pilot only)

- **Why:** if base Qwen matches the lay belief, the principled fix is training on how people actually behave.
  Psych-101 (Binz et al. 2025, the data behind Centaur) is trial-by-trial human choices from 160 experiments.
- **Do first:**
  - Read the dataset card and licence on Hugging Face (`marcelbinz/Psych-101`). The test split is gated. Record terms
    in `experiments/sensation/psych101/SOURCE.md`.
  - If the terms don't allow our use, stop the lane and log it.
- **Build:**
  - `experiments/sensation/psych101/prepare.py`: download into the scratchpad or `out/sensation/psych101/data/`
    (never git) and convert to `mlx-vlm` LoRA format with a fixed split.
  - **Hold out** every experiment about food, hunger, generosity or social giving, so our sweeps measure transfer,
    not memory. Write the held-out list next to the data.
- **Pilot:**
  - One small LoRA on Qwen3-VL-8B 4-bit through the queue at p50, `--max-hours 3`.
  - Use the training scripts the homeostatic area already uses through mlx-vlm. Import, don't copy; if they don't fit,
    log why and use `mlx_vlm.lora` directly.
  - Save the adapter under `models/adapters/psych101_pilot/` with a sidecar.
- **Evaluate:** the hunger sweep on the pilot adapter as a new arms config, `--samples 30`, after the base sweep
  finishes. Guardrails: the existing IFEval and MMLU-subset instruments on the same adapter.
- **Not tonight:** any decision about which post-training route Kokopelli takes (section 9). This lane only makes the
  option real and measured.
- **Gate D:** data prepared with held-out list; pilot adapter trained or a logged reason it couldn't be; eval queued.

### Lane E: real runs (queue jobs, not a worktree)

Queue only after Gate 0 for sweeps, and after Lanes A and B merge for videos. Each with `--about`, `--output` and a
`run.json`.

1. `evals_hunger_egg_base`, p40: hunger sweep, base Qwen, 30 samples, all three arms.
2. `evals_energy_base`, `evals_warmth_base`, p40: once Lane C merges.
3. `sens_seen_eval`, p42: Lane A's evaluation.
4. `evals_hunger_egg_psych101`, p45: after Lane D's adapter exists.
5. `egg_videos_cue`, p32, queued last: `kokopelli/agents/run_egg_videos.sh --minutes 2`.

For the videos:
- Owner's defaults: 832x480, 8-bit, four controls at 0.25.
- `--minutes 2` keeps the night realistic. Log it as a shortening, not a quality change.
- The owner is asleep, so the mouse rule is met. Write that down in the log.

If 9001 is busy with another area's job, don't connect. Wait for the queue.

- **Gate E:** each job finished or failed with a logged reason. The sweep reports and the side-by-side film exist, and
  each `run.json` names model, weights, size and precision.

### Lane F: voice, for real

- Load Kokoro-82M through mlx-audio on the Mac in a queue job at p55. Render `voice.wav` for one existing dry run and
  one real egg run once Lane E's videos exist.
- Record the licence and model revision in `kokopelli/body/voice.py`'s sidecar.
- Listen-test proxy: check duration, no clipping, lines start at decision times within 0.5 s. A human listen is the
  owner's job: flag it.
- **Gate F:** `overlay_voice.mp4` exists for at least one real level and the Inner voice toggle plays it on `/sensations`.

### Stretch S: Teo's body language (only if PACE and 9004 are both free)

- **Why:** the view is first person, so Mara's posture is never seen, but Teo's is. Kimodo (NVIDIA; code Apache 2.0,
  weights under NVIDIA's licence) can generate "waiting, hopeful", "thanks, relieved" and "shrugs it off" clips.
- Kimodo needs CUDA. Use the PACE backend (`kokopelli/ops/cloud/`) only if `pace.json` exists.
- Retargeting to the MetaHuman skeleton needs the editor on 9004, which the bodies area owns. Claim it per AGENTS.md or
  skip. If either is missing, skip the lane and log it. Never block anything else on it.

### Verifier V (Phase 3, a fresh subagent that didn't build anything)

1. Check out `sens/integration` in its own worktree. Run every gate from section 0 itself, not from the lanes' logs.
2. For each claim in each lane log, open the file or run it. Mark each claim checked, wrong or unverifiable.
3. Check that nothing fake is presented as real: every report and panel row from a mock or dry run must say so.
4. Screenshot `/sensations` at 1440 px and 375 px, light and dark, and look at them. Run DESIGN.md's section 8 checklist.
5. Watch each real video end to end; note where the painted film degrades (the mosaic around 52 s, `docs/MOSAIC.md`).
6. Write `docs/log/sensations/2026-11-11-MORNING.md` (section 8) and push it to `sens/integration`.

## 7. Lead session prompt (copy as is)

> You are the lead for the overnight sensations build in /Users/jaycewalzer/Desktop/kokopelli. Read AGENTS.md,
> CLAUDE.md, DESIGN.md and docs/SENSATIONS_OVERNIGHT.md on branch milestone/m1-last-egg. Do Phase 0 yourself in a
> worktree and push sens/integration when Gate 0 passes. Then start lanes A, B, C, D and F as subagents, one each, with
> the lane prompt from section 7b, and queue Lane E's jobs in the order given as their gates pass. Merge each lane into
> sens/integration only after its gate passes on a rebased branch. When every lane has merged or stopped, start the
> verifier with its prompt. Never merge to main, force-push, or edit another area's files. Keep a running log at
> docs/log/sensations/2026-11-11-lead.md.

**7b. Lane prompt (fill in the lane letter):**

> You are lane <X> of docs/SENSATIONS_OVERNIGHT.md in /Users/jaycewalzer/Desktop/kokopelli. Read AGENTS.md, CLAUDE.md,
> DESIGN.md, then sections 0, 3, 4 and your lane in that file. Work only in your worktree on sens/<lane>, cut from
> sens/integration, and only on the files your lane owns. Model jobs go through kokopelli/ops/gpu.py, tests through
> kokopelli/ops/memguard.py. Log to docs/log/sensations/2026-11-11-<lane>.md as you go, including "Decisions for
> Jayce" and "Read this". When your gate passes, rebase on sens/integration, rerun the gate, push sens/<lane>, and tell
> the lead. If the same gate fails twice for the same reason, stop and tell the lead.

## 8. Morning report

`docs/log/sensations/2026-11-11-MORNING.md`, written by the verifier, in this order:

1. **Headline:** did base Qwen's giving fall with hunger (the lay belief) or stay flat (what people do)? In each arm,
   with intervals. Link the report.
2. **Videos:** the side-by-side film and each level's outcome, with one sentence on where the film is trustworthy.
3. **Per lane:** done, partly done or stopped, and why, with links.
4. **Gates:** a table of every gate and its status as the verifier measured it.
5. **Decisions for Jayce:** gathered from every lane, each with options and tradeoffs, none decided.
6. **Read this:** up to five `file:line` pointers from across the lanes, each with one question.
7. **Owner steps:** anything only he can do, for example MetaHuman Core Data, licence calls, `pyproject.toml` edits,
   listening to the voice.

## 9. Decisions that wait for the owner

- Which post-training route Kokopelli commits to: Psych-101, held-out synthetic data, homeostatic RL, or lived
  experience in the sim.
- One egg or two. Whether any scene's wording changes after he's seen base Qwen's answers.
- Any licence that isn't plainly permissive for research and possible commercial use.
- Merging `sens/integration` into `main`.
- Changing another area's code: the loop's `visible`, `live_wm.py`'s init order, the homeostatic area's drive.

## 10. Risks and what to do

| Risk | Sign | Do |
|---|---|---|
| Phase 0 eats the night | Gate 0 not green by 3 h in | Stop lanes A to D; run Lane E's hunger sweep from the ported code anyway if Gate 0's tests pass; log what's left |
| Memory pressure | `memguard.py status` shows swap growing | one lane's tests at a time; the queue already serialises models |
| 9001 busy | another area's job holds it | wait for the queue; never connect |
| Painted film mosaics | the film breaks up around 52 s | videos run 2 sim-minutes; the decision is in the first 15 s; say so in the report |
| Qwen replies don't parse | invalid share over 10% in a cell | log examples; don't change prompts overnight (it breaks comparability); flag for the owner |
| Licence unclear | no LICENSE or a non-commercial term | skip that package, log it, pick the next option in the lane |
| A lane needs another area's file | the change would edit it | write the patch in that area's HANDOFF.md; don't apply it |
