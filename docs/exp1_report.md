# Experiment 1: first long run (draft, filled in when the run finishes)

Run `exp1_lived_s0_lr2e-5`, started 2026-11-07 12:52. Base model Qwen3-VL-8B-Instruct, bf16 (`models/Qwen3-VL-8B-Instruct`),
fresh LoRA r16 on q and v. Lived arm, seed 0, 25 free days after 8 forced exploration mornings. lr 2e-5, β 0.05, 2 steps
per night, 5 replay days, choice temperature 1.0 (the spec). Folder: `out/exp1/runs/exp1_lived_s0_lr2e-5/`.

## What's ready

- Phase 1: the 3-decision world with homeostatic reward, balance and leak tests, and the tabular reference. See
  `docs/exp1_phase1.md`. D1 is kept as written (a weak decision under the capped drive).
- Phase 2: `python -m exp1.run`. Scores options, samples at T=1, writes the reason after the choice, sleeps each free night,
  checkpoints after every night and resumes with the same command. Guardrails and baselines run at the end.
- Phase 3: the `/exp1` panel page. It has the pipeline strip with file:line references, the causal trace, the timelines,
  shares against the tabular band and the untrained model, the training charts beside the random and always-safe
  baselines, what changed overnight, the arm comparison and the glossary.
- 40 tests: phase 1 (16), the learner, run loop, resume and panel data (13), and the existing scenario tests. Two phase 1
  tests are expected failures (D1 under the cap).
- The table policy run through the same loop reproduces the hot-stove pattern in all three arms (150 lives, lr 0.01). This
  checks the update rule itself.

## Smoke test on Qwen

- On all 4 probe states, scoring `{"choice": "<id>"` agrees with the model's own greedy reply.
- A full 18-row sleep step takes 207 s and peaks at 18.5 GB. That needed backpropagating one option sequence at a time,
  and slicing logits before the softmax. KL is exactly 0 before the first update.

## The main finding so far: the untrained policy is nearly deterministic

From the untrained model's exact log-probs on every state this life saw (39 decisions, no GPU needed):

| τ (choice temperature) | D1 top option | D2 top option | D3 top option | mean entropy, share of max |
|---|---|---|---|---|
| 1 (spec) | 0.97 | 0.92 | 0.96 | 0.07 to 0.21 |
| 2 | 0.88 | 0.80 | 0.94 | 0.12 to 0.47 |
| 5 | 0.64 | 0.59 | 0.81 | 0.40 to 0.82 |

At τ = 1 the agent almost never tries anything but its favourite. Where π is about 1, the policy-gradient (∇ log π) is about
0, so a lived bad outcome barely moves it. On day 4, leave_early hit its rare bad outcome (reward −0.30), and π(leave_early)
on the D3 probe stayed at 100%. The base model's prior is leave_early at D3 and side_path at D1. So the lived arm's D3
"keeps rare-bad" reading would show up even with no learning. Only the flipped and shuffled arms can tell learning from
prior.

## Results

(Filled in at the end: shares against the tabular band and the untrained model, reward against random and always-safe,
KL and π over nights, guardrails, the direction table.)

## Decisions for you

1. **Choice temperature.** Keep 1.0 (the spec; this run), or flatten π with `--choice-temperature`. τ doesn't change the
   model, only how far the sampled choice strays from its favourite and how big the gradient is.
2. **The lr sweep.** Planned for 3 values.
3. **Flipped and shuffled runs.** They're what separates learning from prior.
