# Experiment 1: first long run

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
- Tests: `tests.test_exp1` (phase 1, 16, two expected failures for D1 under the cap) and `tests.test_exp1_learn`
  (the learner, run loop, resume, polite pause, probes, panel data and baselines, 14) pass, as do the scenario, world,
  watch and benchmark suites. `test_homeostatic_grpo` and `test_homeostatic_export` error in this worktree only because
  they load `models/Qwen3-VL-8B-Instruct` from the worktree, which has no models folder; they don't touch exp1.
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

This table covers the 39 decisions available when it was written. The full check over all 99 rows is in
`diagnostics/temperature.json`, and it reads higher at τ = 5 (D3 top option 0.90).

At τ = 1 the agent almost never tries anything but its favourite. Where π is about 1, the policy-gradient (∇ log π) is about
0, so a lived bad outcome barely moves it. On day 4, leave_early hit its rare bad outcome (reward −0.30), and π(leave_early)
on the D3 probe stayed at 100%. The base model's prior is leave_early at D3 and side_path at D1. So the lived arm's D3
"keeps rare-bad" reading would show up even with no learning. Only the flipped and shuffled arms can tell learning from
prior.

## Results

Finished 2026-11-08: 99 decisions (24 forced, 75 free), 25 trained nights, 50 LoRA steps. It was paused overnight at its
night-24 checkpoint for the bodies demo and resumed with the same life (checked by replay). Panel: `/exp1`.

**What it picked (free days, second half, 13 picks each):**

| Decision | Trained run | Untrained π on the same states |
|---|---|---|
| D1 | side_path 100% | side_path 100% |
| D2 (gate always closed) | back_row 77%, lawn_edge 23% | back_row 78%, lawn_edge 22% |
| D3 | leave_early 100% | leave_early 100% |

The gate never opened on a free day: side_path gets there at 9:12 or 9:16, so front_gap was never offered and the D2
rare-bad/rare-good pair was never tested.

**Direction readings:** D1, no reading (neither run_main nor check_desk was picked; I changed `baselines.direction` to say
so instead of counting it as a fail). D2, no reading (gate closed). D3, "pass" at 100/0, but the untrained model is also at
100/0, so this is the prior, not learning.

**Reward:** 0.151 per decision against 0.126 for random choices on the same seed (random across 200 lives: 0.129 to 0.165,
p10 to p90) and 0.150 for always-safe. It does about as well as always-safe, because it nearly always picks a safe or
50/50 option.

**What moved on the D2 probe, and what the check found.** On the one fixed gate-closed probe prompt, π(back_row) went from
1–5% to 100% over nights 28–30 (free days 21–23). That size is an artifact of that one prompt. Over 4 wordings and all 6
option orders the untrained model already gives back_row 0.685 on average (0.388 in the original wording, 0.74 to 0.85 in the
paraphrases), so there was no strong lawn_edge prior to overturn. A smaller shift is real: replaying the three nights from a
rebuilt pre-shift adapter moves that average from 0.754 to 0.893, and removing the one penalty moves it to 0.674 instead. It
comes from a single transition, day 18 lawn_edge "busy" (advantage −0.128). back_row and lawn_edge have the same expected
reward (0.15 on every free day), so this is an overreaction to one bad outcome, not the agent finding a better option.

Details are in `out/exp1/runs/exp1_lived_s0_lr2e-5/diagnostics/d2.json`. Model for the diagnostic: base Qwen3-VL-8B-Instruct,
bf16 (`models/Qwen3-VL-8B-Instruct`), plus a LoRA r16 rebuilt from a new seeded start on this run's logged rows, because
each night's checkpoint overwrote the last and the real pre-shift adapter no longer exists.

**Training:** KL from the untrained model was 0.06 or less through night 22, rose to 0.07–0.19 over the next nights while the D2 probe moved, and ended at 0.045.
Grad norm was mostly under 0.3 and went to 0 in the last two nights, because π is saturated on every state it sees.

**Guardrails** (untrained against trained, same questions):

| Check | Questions | Untrained | Trained | Difference | Flag |
|---|---|---|---|---|---|
| MMLU | 200 | 75.0 | 75.0 | +0.0 ± 0.7 | ok |
| IFEval subset | 30 | 66.7 | 60.0 | −6.7 ± 6.7 | flagged (more than 1 point down) |

IFEval is 2 prompts out of 30 and is within one standard error of zero. The flag is doing its job, but at this size it
can't tell harm from noise. Before the arm runs, IFEval should use every prompt our verifiers can check, so that a 1-point flag means something.

**Done-means check:** tests pass (except the two Qwen-loading suites that can't find weights inside a worktree); the
25-day lived+RL run finished end to end with full logs; the panel shows it and the causal trace works on every decision
(checked on day 18 D2); this report.

**Model:** base Qwen3-VL-8B-Instruct, bf16, `models/Qwen3-VL-8B-Instruct`, plus this run's LoRA
(`out/exp1/runs/exp1_lived_s0_lr2e-5/checkpoint/adapters.safetensors`).

## Decisions for you

Production-ready for longer tests: yes for the machinery (resume, polite memory sharing, logs, panel, guardrails). For the
science, one run says the spec's settings mostly measure the prior. These decisions shape the next runs:

1. **Choice temperature.** Keep 1.0 (the spec; this run), or flatten π with `--choice-temperature`. τ doesn't change the
   model, only how far the sampled choice strays from its favourite and how big the gradient is.
2. **The lr sweep.** Planned for 3 values.
3. **Flipped and shuffled runs.** They're what separates learning from prior.
4. **IFEval size.** 30 prompts is too few for a 1-point flag.
5. **D2 gate.** With side_path the favourite, the gate never opens, so the front_gap pair is never tested. Either accept
   that as the model's own behaviour or make the gate easier to open.
