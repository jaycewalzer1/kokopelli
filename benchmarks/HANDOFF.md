# Benchmarks handoff

Measuring sticks for Kokopelli's first experiment. **Main result:** established human-psych instruments. **Guardrails:** standard ML benchmarks that must not move. We don't optimize for any of them.

```sh
.venv/bin/python -m unittest discover -s benchmarks/tests -t .
```

## What's where

| Path | What it holds |
|---|---|
| `holt_laury/`, `lotteries/` | Finished far-transfer instruments: items with sources, 3 templates, parser, scorer, human norms |
| `mid_travel/` | Instrument and generator. **No real items yet**, on purpose |
| `near_errand/` | Task interface and a **stub** world. Real runs refuse it |
| `guardrails/` | Wrapper around lm-evaluation-harness |
| `backends/` | `mock`, `llm_model` (this Mac), `api` (any OpenAI-style server), `vllm` (PACE, untested on real vLLM) |
| `run.py` | The runner: `results.jsonl`, `run_record.json`, `summary.parquet`. Resumes by key |
| `before_after.py` | One command comparing a base model with a trained one |
| `stats.py`, `report.py` | Means, intervals, contrasts, Holm, pass rule; markdown and HTML reports |
| `leakage.py` | Checks eval prompts against each arm's training text |
| `prereg.py`, `freeze.py` | The pre-registration guard and the item freeze. Neither has been used for real |
| `noise_check.py`, `noise_check_turns.sh` | Phase 5 analysis, and running it in short GPU turns |
| `configs/` | `arms/`, `instruments.yaml`, `contrasts.yaml`, `sampling.yaml` |
| `proposals/` | Notes for the owner to decide on. Nothing reads them |

## Adding an instrument with human norms

1. Make `benchmarks/<name>/__init__.py` with an `Instrument` subclass. `lotteries/__init__.py` is the shortest example.
2. Add `items.jsonl`, with a `_meta` line holding its sources and `verified`.
3. Optionally add `norms.yaml`. Reports then show the norms beside each arm.
4. Add an entry to `configs/instruments.yaml`, plus `contrasts.yaml` if it's pre-registered.

## Real models on this Mac

Every real model job goes through the shared GPU queue. The queue doesn't recognize `benchmarks.run` as a model job, so a run started directly would be invisible to it.

```sh
python3 /Users/jaycewalzer/Desktop/kokopelli/.claude/worktrees/ops/ops/gpu.py run --name evals_<job> --priority 40 \
  --max-hours 0.75 --cwd <worktree> -- nice -n 10 <venv python> -u -m benchmarks.run ... --minutes 30
```

`--minutes 30` ends a turn cleanly with exit code 75, so a long job gives the GPU back and higher priorities go first. Rerunning with the same `--out` continues. `noise_check_turns.sh` does this loop for you. In a worktree, weights come from a `models` symlink to the main checkout. Don't stage it.

### What's fixed and what isn't with `llm_model.ask`

| Setting | Status |
|---|---|
| `temperature`, `max_tokens` | Set per run through `ask()` and recorded |
| `top_p` 0.8, `top_k` 20, `repetition_penalty` 1.0 | `ask()` can't set these. They come from Qwen's `generation_config.json`, and each run records them. A run asking for other values is refused |
| Sampling seed | `ask()` has no argument. The backend calls `mx.random.seed()` first, after making sure the model is loaded. Tested as repeatable on a tiny model, not yet on real Qwen. It relies on how mlx-vlm works today |
| `temperature=0.0`, the default in `ask()` | Greedy, so sampling alone shows no spread at all. That's why the noise check uses 0.7 |

## Phase 5: the base-model noise check

**It ran, on real Qwen, with no adapter:** Holt-Laury and the lotteries, 50 samples per template, temperature 0.7, 1,050 results, 0 invalid, about 1.5 seconds per sample. Results are in `benchmarks/results/noise_t07/`, which git ignores. Rerun the analysis with `python -m benchmarks.noise_check benchmarks/results/noise_t07`.

**Holt-Laury as a full menu doesn't measure risk preference well in this model.** Of 150 ladders, only three scores occurred: 0 (93 times), 9 (28) and 10 (29). No answer switched mid-ladder. Humans average about 5.6, and switch in the middle.

| Template | Mean safe | Safe option listed first | Risky option listed first | Most common answer |
|---|---|---|---|---|
| `die` | 3.78 | 8.22 | 0.00 | `AAAAAAAAAB` or `AAAAAAAAAA` |
| `fractions` | 1.26 | 2.42 | 0.00 | All risky in both orders |
| `percent` | 5.80 | 10.00 | 1.25 | `AAAAAAAAAA` |

- **The score mostly follows position.** On `die` and `percent`, swapping the options moves the score by more than 8 of 10 points, because the model picks "A" on nearly every row. A mean near 5.6 here would be a coincidence of averaging the two orders.
- **It's nearly identical within a cell.** Inside one template and order, one or two answer patterns account for everything, so sampling at 0.7 adds little spread.
- **The answers aren't sensible preferences.** 58% of `percent` answers take $2.00 for sure over $3.85 for sure on row 10, and most `fractions` answers take the risky option on row 1.
- **`AAAAAAAAAB` shows some reading.** On `die`, the safe-first answer flips only on row 10, where B is plainly better.

**The lotteries are more usable, unevenly.** Overall underweighting rate 0.431, against 0.373 for humans who read the odds. The model chose the first-listed option 52% of the time overall, which hides differences by template.

| Template | Underweighting rate | What drives the choice |
|---|---|---|
| `plain` | 0.38 | Content: on 5 of 6 problems every answer was the same in both orders. Little spread, mostly 0 or 1 |
| `percent` | 0.59 | Mixed: several problems flip with position, and some don't |
| `tickets` | 0.33 | Position on 3 problems (3, 5 and 6), where it took the first-listed box every time |

44% of problem-and-template cells sit at exactly 0 or 1, where a small shift can't show under sampling.

**The verdict rules were adjusted after seeing this.** My first automatic verdict said "FLOOR", which misread position bias as risk taking. The position and floor rules were added after seeing the data, and `noise_check.py` says so.

**Proposed fixes, before anything downstream:**

1. **Ask Holt-Laury one row at a time.** Results below, once the pilot has run. This is decision 2.
2. **Score with log-probabilities instead of sampling.** Read P(A) from the model directly and average over both orders. That cancels position exactly and can show small shifts in cells stuck at 0 or 1. It needs logits, which `ask()` doesn't return, so it needs a small addition outside `llm_model.ask`.
3. **Analyze within order, or require order-balanced cells.** Option order must stay balanced across arms, which the design already does, or position differences would pass for effects.
4. **Drop or rewrite weak templates.** `tickets` is position-heavy on the lotteries. Don't choose by which one shows an effect later: decide before any adapter exists.

**Without a fix, a LoRA could change the letter habit, and the ladder score would read that as a change in risk preference.** I recommend not locking `PREREG.md` until this is settled.

## Before and after

The command the training pipeline calls:

```sh
python -m benchmarks.before_after --after-weights <run>/fused --name homeostatic \
  --instruments holt_laury lotteries mmlu --seeds 0 1 2 --samples 50 \
  --training-text "out/adapters/homeostatic/seed0/training_text/*" \
  --backend llm_model --real --out benchmarks/results/<id>
```

It runs a `base` arm and the trained arm through `run.py`, so prompts, option orders and sampling match by construction. It writes `<out>/before_after.json`, `results.jsonl` and the usual report. Pipelines should read these fields of the JSON:

| Field | Meaning |
|---|---|
| `comparable` | False means the two sides don't cover the same questions yet. Don't use the numbers |
| `instruments[]` | Before and after means, difference, 95% interval, Cohen's d, p and Holm p, difference per seed |
| `guardrails[]`, `guardrails_ok` | Delta in points, 95% interval, status against the 1-point margin. `guardrails_ok` is null if none ran |

Exit codes: 0 finished, 2 refused, 3 leakage found, 75 time budget used. On 75, rerun the same command.

**Real runs are gated on purpose.** Today `--real` exits 2, for two reasons: `PREREG.md` is a draft, and any trained arm must appear in `contrasts.yaml`. `--exploratory` refuses trained arms. So the mock path works now, and the real path opens only when the owner approves an arm. If a before-and-after outside the pre-registration is wanted as a training diagnostic, that's a decision below, not something to route around.

Tested on mock with fake adapters: it finds a planted change, doesn't report one under no effect, and resumes. The `weights` setting is tested through the real `llm_model.ask` on tiny random weights, including real `lm-eval` through the local endpoint. It has **not** run on real Qwen or real `fused/` weights, because no training run has passed the export gate.

### On this Mac: `fused/` weights

An arm with `weights` makes the backend point `llm_model.LLM_MODEL_WEIGHTS` at that folder, as `MlxQwenAgent` does, unloading first because two 18 GB models don't fit. `homeostatic.export` writes that folder and `out/homeostatic/handoff.json`. Hashing 18 GB takes a little while on each arm start. For guardrails, the backend runs a small local OpenAI-style server, one request at a time, and needs `EVALS_LM_EVAL` set to an `lm-eval` from a separate venv with `lm-eval[api,ifeval]`. IFEval's 541 prompts at up to 1280 tokens will be slow here. A guardrail only records when the whole task finishes, so `--minutes` can't split one, and `--max-hours` must cover it.

### The other route: vLLM on PACE

`backends/vllm.py` and `scripts/pace/evals/` do LoRA hot-swapping. `bash scripts/pace/evals/dry_run.sh` prints the exact commands. **Nothing has been submitted, and neither the scripts nor the backend have run against real vLLM.** Its tests use a fake library, so they only check that our calls have the intended shape. Before the first real job:

- **Convert the adapter.** `homeostatic.export` writes MLX's `adapters.safetensors`. vLLM wants PEFT's `adapter_model.safetensors` and `adapter_config.json`, with different layer names. No converter exists yet, and the backend refuses a folder without `adapter_config.json`. Check a converted adapter by comparing logits with the MLX one on the same prompt.
- **Check support.** Confirm vLLM's LoRA path supports Qwen3-VL. `limit_mm_per_prompt` and `max_loras` are from memory of its API.
- **Or serve `fused/` directly.** That skips conversion but costs a full model load per arm, and loses the same-process comparison.

## Near transfer: hooking up the real world

`runtime/` isn't on this branch and isn't imported here. Its mock grid is `runtime/mocks/sim.py` (`MockSim`) on `feat/wm-agent-loop`, with SimWorld work on `feat/wm-simworld`. To replace the stub:

1. Build a world from `ErrandTask` (`map_id`, `start`, `goal`, `deadline_minutes`, `routes`, `seed`). `map_id` must be a map no training run used. The current three ids are placeholders.
2. Replace `StubErrandWorld.walk` with the agent loop acting in that world. Outcomes draw from `p_blocked` with the task's seed. The agent must not be told the odds.
3. Record which route the agent took and score it with the same `shortcut_rate`. A run becomes several ticks, so `near_errand` will probably need `kind = "harness"`, like guardrails.
4. Set `stub = False`, add its contrasts to `PREREG.md`, and let real runs through.

## Sources

| Item | Status |
|---|---|
| Hertwig et al. (2004) six problems | `verified: true`. Read from Table 1 of the paper's PDF. Payoffs cross-checked against Fox & Hadar (2006) Table 1, and the paper's 36-point mean gap recomputed in tests |
| Holt-Laury ladder | `verified: true`, from a reproduction. The original AER PDF wouldn't open (401/403). All 10 rows come from Filippin & Crosetto (2016) Table 2, and row 1 matched search excerpts quoting the original |
| Holt-Laury human norms | Holt & Laury (2005) Table 1; Filippin & Crosetto (2016) Tables 7 and 8 |
| Lottery human norms | Worked out from Hertwig et al. Table 1, checked in tests |
| `mid_travel` | No items. The throwaway fixtures are `verified: false` |
| `near_errand` | Placeholder tasks. `verified: false`, and a stub |

## Decisions for the owner

Each is a simple, reversible choice made so work could continue.

1. **Which LLM writes the travel items?** Nothing is generated or frozen, as you asked.
   - Qwen itself: free and local, but the items would carry the habits of the model under test, which could make them easier or harder for it in ways that look like an effect.
   - A different model through `--backend api`: avoids that, but costs money and adds a dependency.
   - Numbers come from a fixed grid in code either way, so the writer only supplies the words. Then: `mid_travel.generate`, review, `freeze`, and add the hash to `PREREG.md`.
2. **Holt-Laury as one menu or row by row?** Built as one menu with all 10 rows, as humans saw it.
   - One menu: matches the norms, costs one call, but rows influence each other and there's one answer per sample.
   - Row by row: gives a smooth curve and allows log-probs, but it's a different task, and Filippin & Crosetto report that random row order greatly raises inconsistency in people.
3. **Does Holt-Laury test the hypothesis directly?** Its "risky" option isn't a rare-event gamble in most rows. The prediction needs a step: underweighting rare costs means more risk taking in general. It's a broad risk measure, while the lotteries are the direct test. Keep both as main results, or make one primary? That affects Holm.
4. **Three seeds can't carry significance on their own.** A sign test over 3 seeds can't get below p = .25. The permutation test shuffles samples within seeds, so it says "these adapters differ", not "training reliably produces this". The direction rule covers that gap informally. Options: keep it, or train 6 or more seeds and test at seed level, which is slower but a stronger claim.
5. **The pass rule when more than 3 seeds run.** The brief says the right direction in at least 3 seeds. I also required none going the wrong way (`max_seeds_wrong: 0`), since 3 right and 2 wrong would otherwise pass. Stricter, but a single noisy adapter can fail a real effect.
6. **Guardrail margin vs question count.** At 342 MMLU questions, a mock with no real effect moved 1 to 4 points by chance, and intervals ran about 8 points wide. The mock's noise is independent per arm, so a real model's paired answers should be tighter, but ±1 point is unlikely to be resolvable. Options: keep the point-estimate rule and accept false alarms (current), use more questions (all 14,000 MMLU questions cost hours), or widen the margin.
7. **Equivalence margins for `shuffled`.** I drafted 0.5 safe choices (about 0.25 SD of human choices) and 5 percentage points. These are judgment calls, and they should be set before seeing data.
8. **MMLU uses `mmlu_generative`, scored by exact match,** because chat endpoints have no log-likelihoods. A reply like "B. Paris" scores 0, so the score also reflects reply style, and a LoRA that changes style could fail the guardrail without losing knowledge. Option: `local-completions` with log-likelihoods on vLLM.
9. **Should a training diagnostic be allowed outside the pre-registration?** Currently no real trained-arm run is possible until you lock it. A separate, clearly labeled diagnostic mode would let training see benchmark scores earlier, but looking at them during training also breaks "we don't optimize for any benchmark". I'd keep it closed.
10. **A homeostatic arm.** Not added. See `proposals/homeostatic_arm.md`.

## Things to watch

- **Fox & Hadar (2006)** argue the human description-experience gap comes mostly from sampling error: people who sample a little often never see the rare event. So log how often each lived run actually met the rare cost. A lived run that never hit it isn't evidence about "underweighting", and shuffled and described arms need matching exposure.
- **The leakage check is lexical.** It catches copies and light edits (0.76 and up on a test sentence), but a true paraphrase scored 0.36 and gets through, and a test pins this. A meaning-based check needs an embedding model passed as `embed`. None was downloaded.
- **The parser never guesses.** Replies that mention both options without a clear answer become invalid. If real replies have a pattern it misses, invalid rates will show it. Report them per arm, because a gap between arms can bias results.
- **`AGENTS.md`:** the harness blocks this worktree's agent from editing that file at its shared path, so my entry there may be out of date.

## Code worth reading

You asked to read important code and predict what it does. Try these before moving on:

1. `benchmarks/core.py:30`: why is the arm deliberately not an input to `option_order`? What could look like a risk preference if it were?
2. `benchmarks/holt_laury/__init__.py:98`: if a model answers `BBBBAAAAAA` with the risky option shown first, what does `score` return, and is the answer consistent?
3. `benchmarks/stats.py:54`: this fixes a bug that gave guardrails intervals of zero width. Why does redrawing inside a stratum do nothing when it holds one sample?
4. `benchmarks/stats.py:109`: work out `holm([0.01, 0.04, 0.03])` by hand, then check it.
5. `benchmarks/backends/llm_model_backend.py:83`: a test failed until this line existed. What would have gone wrong with only the first sample after each load?
