# Gates to the 30 minute run

In order. Each gate should pass before spending on the next. A full run is 60 ticks: SimWorld, Cosmos and Qwen on NVIDIA GPUs. The Mac can't be the route, since a real 30 seconds takes about 2 hours there.

**Nothing real has run through this loop yet.** Everything marked done was tested against mocks or fake servers.

| # | Gate | Check | Status | Blocked by |
|---|---|---|---|---|
| 1 | Loop works end to end | `python -m unittest discover -s runtime/tests -t .`, both Pythons | Done on fakes | |
| 2 | Tools hold up at full scale | 60 ticks in the real shape on mocks, then `runtime.check_video --expect-seconds 1800` | Done on mocks: 240 clips joined into 43,201 frames, exactly 1800.0 s, in about 6.5 minutes. Its speed and storage don't predict a real run | |
| 3 | Real models in the loop | 3 ticks on the Mac: real Cosmos and Qwen, mock sim, real life text. Passes only with valid decisions that weren't forced waits | Passed: `runs/wmloop_demo_real2`, 3 of 3 valid on the first try, video with no cuts. See the repeat warning under "What could change the plan" | |
| 4 | Lower-RAM mode | 4-bit Qwen conversion, then 3 ticks with `--low-memory` | Passed: `runs/wmloop_demo_lowmem2`. Demo only, not for experiment results | |
| 5 | PACE access filled in | `CHANGE_ME` values in `scripts/pace/env.sh` and both `.sbatch` files; `WMLOOP_DRY_RUN=1 bash scripts/pace/wmloop_run.sbatch` | Not started | Owner: account, partition, GPU type |
| 6 | SimWorld on a real server | `sbatch scripts/pace/wmloop_gate.sbatch`; every checklist line passes | Not started | Gate 5, package download |
| 7 | Cosmos server on a GPU | One real chunk through `/v1/videos/sync`; `runtime.preflight` sees the model | Not started | Gate 5 |
| 8 | Qwen server on a GPU | One real decision with images; replies validate | Not started | Gate 5 |
| 9 | 10 ticks, everything real | `WMLOOP_TICKS=10 sbatch scripts/pace/wmloop_run.sbatch` | Not started | Gates 6 to 8 |
| 10 | Preemption on the real stack | Cancel gate 9's job partway, then rerun with the same `WMLOOP_RUN_NAME`; it continues | Done on fakes only | Gate 9 |
| 11 | Drift control earns its place | Same seed with and without `--no-drift-control`, then `runtime.compare` | Done on mocks only | Gate 9 |
| 12 | Budget | `runtime.plan` on gate 9's run gives hours, GPU-hours, storage and fallbacks; choose one | Tool done | Gate 9, then owner's decision |
| 13 | Null agent on the real sim | Same seed with `--agent null --wm mock`, then `runtime.compare` | Tool done | Gate 9 |
| 14 | The 60 tick run | `WMLOOP_TICKS=60 WMLOOP_RUN_NAME=full sbatch scripts/pace/wmloop_run.sbatch` | Not started | Gates 9 to 12 |
| 15 | Result checks out | `runtime.check_video --expect-seconds 1800`, then watch it; replay in `runtime.viewer` | Tool done | Gate 14 |

## Measured so far

Passing real run, on the Mac at 448x256, 16 frames per tick, so about 0.7 s of video rather than 30 s: 436 s for 3 ticks, of which Cosmos was 395 s and Qwen 41 s. The machine's peak RAM was 30.9 GB from a 12.0 GB baseline, with Cosmos and Qwen taking turns.

The low-memory run, at 256x256 with 20 steps, took 222 s for 3 ticks. The machine's peak while Qwen ran fell from 30.9 to 20.0 GB, but its peak while Cosmos ran only fell from 29.5 to 28.2 GB, so 8-bit Cosmos barely reduces its peak. These compare one short run each, from baselines of 12 and 13 GB.

## What could change the plan

Most likely to bite first:

0. **What drives the agent's choices.** Over 20 real ticks it does change course, so it isn't stuck. `runtime/probe_decisions.py` re-asked 3 logged moments, about 27 replies, so these are first reads:
   - Frames matter: blank frames moved it from the door to Ana.
   - Hidden notes didn't change its action, only some diary wording, so its notes aren't what picks the action. They may still explain its repeated phrases.
   - A named target in the prompt's example changed its choice, so the prompt no longer names one.
   - List order didn't matter, and 0.7 temperature still gave the door 9 of 9, so at this moment it's a real preference.
   - It sometimes targets things from the life text, such as a clock, which the sim doesn't have. Those replies are rejected. This is the scene mismatch in the first owner decision below.
1. **Do SimWorld's actions play out while paused?** The adapter steps a paused game, but every SimWorld example runs unpaused. If movement doesn't advance on paused ticks, stepping needs a redesign. Gate 6 answers this. `runtime/SIMWORLD.md` has the full list.
2. **Does `/v1/models` exist on the vLLM-Omni Cosmos server?** The README shows it on plain vLLM, not with `--omni`. The PACE job waits on it, so if it's missing the job fails at startup. The fix is a small change to the wait and to preflight. Gate 7 answers this.
3. **Is Cosmos's video good enough across a whole run?** Each chunk continues from one frame, so motion may not carry between chunks. A re-anchor may also show as a jump. Only gate 9 can show this.
4. **Cosmos's safety guardrails may refuse a prompt.** That comes back as a 4xx error, which stops the run instead of retrying. It's resumable, but the same prompt would refuse again.
5. **GPU type and count on PACE.** The job assumes 3 GPUs on one node, one each. NVIDIA recommends H200s for Cosmos, and I don't know what PACE offers or whether smaller cards fit it.

## Decisions for the owner

| Decision | Why it matters | Needed by |
|---|---|---|
| Which half hour of which life? | The latest real tree only has text for a few days at age 2, in an apartment, and SimWorld is an outdoor city. The sim, the prompt and the agent's life will disagree until these match. | Gate 9 |
| Write more of the tree, or use coarse nodes? | Most moments have no `sec30` node, so the prompt reuses the deepest node for many ticks. | Gate 9 |
| What counts as the tree's "default" action? | The autonomy metric uses a stand-in mapping, `VERB_TO_ACTION` in `adapters/life_db.py`. | Gate 13 |
| Use `--mind`? | It wraps the agent in the feeling loop and works with the rest of this path, but doubles Qwen's time on decision ticks. See `mind/OPEN_DECISIONS.md`. | Gate 9 |
| Which fallback, if the run is too slow? | `runtime.plan` lists them in order, but only its first row is measured. | Gate 12 |

## Known gaps that won't stop a run

- `--mind` imports `mind/`, which isn't committed on this branch, so it has to be on the path. It builds prompts from the loop's prompt plus its own past rows, and those added rows don't pass through the leak guard. They only hold earlier feelings.
- The agent's list of things it can see comes from the sim, not from what the world model drew.
- Drift scores compare pixels only. Depth, segmentation and key objects need an estimator model.
- Real-sim replays drift by an amount only gate 13 can measure, and that sets how far to trust the null-agent comparison.
- `runtime/HANDOFF.md` lists proposed changes outside this folder, none applied.
