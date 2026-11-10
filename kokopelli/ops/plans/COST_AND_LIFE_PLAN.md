# Kokopelli: cost and longer-life test plan

Written 2026-11-05 at about 00:30. Nothing here was run: no model jobs, no spending. Prices change, so recheck them before paying. PACE terms need you to confirm your allocation.

## The answer

**Price of the full system, one honest pass with retries:**

| Path | What it assumes | Cash | Machine time |
|---|---|---|---|
| **Low** | Mac for all text and training, PACE at its published rate for GPU work | **about $27** ($9 if PACE credits cover GPU work) | about 625 Mac-hours, or 26 days nonstop, one job at a time |
| **Likely** | Hosted API for the long text runs, rented H100 for GPU work, because PACE access is unconfirmed | **about $290** | about 450 Mac-hours plus about 70 rented GPU-hours |
| **High** | Everything rented, more retries, three extra lives | **about $1,400** | about 250 rented GPU-hours |

All three totals are ESTIMATE. The arithmetic is in [section 2](#2-price-map-for-the-full-system). They exclude Claude Code agent bills and paid human judges, because I have no data on either.

**Time is the real constraint, not money.** Text is very cheap: about $0.0003 per call on a hosted API. Video is the expensive part, and the first tests below check whether video matters to the agent's decisions at all.

**Test these first, all free:**

1. **T1, power mode, about 30 minutes.** Your Mac runs in Low Power Mode whenever it's plugged in. This may have inflated recent Mac timings by about 1.6 times.
2. **T2, token audit, about 2 hours of coding and no model.** This rules out input structures that can't fit a long life, before any model time goes on them.
3. **T3, one real skim life, about 3 hours.** The generator's only real run repeated itself heavily, and the prompts were changed afterward without being retested.

**Three things you should know now:**

- **"30 minutes" means three different things, priced from pennies to hundreds of dollars.** The 60-tick `demo` run lasts 30 *sim*-minutes but produces only about 27.5 seconds of video. See [section 2.2](#22-the-30-minute-test-three-different-things).
- **No loop run has finished with a real model yet.** The real demo was still waiting in the queue when I finished, so every loop timing here is a projection.
- **Longer lives alone won't test the bet.** A long context changes the prompt, not the weights. Tests T1 to T9 show that a life can be generated and held in mind. Only T10 and T11 test whether living changes the model.

## How to read the numbers

| Tag | Meaning |
|---|---|
| **[M: file]** | MEASURED on your machine, from that file |
| **[P: Sn]** | PUBLISHED, from a source in the [source list](#source-list). All were checked 2026-11-05 |
| **[E]** | ESTIMATE, with the arithmetic beside it |

Thresholds are draft proposals of mine. Change them before running, not after. Deciding the rule first stops you from moving the goalposts once you see a result.

## Terms

| Term | Meaning |
|---|---|
| Token | A chunk of text, about 4 characters, and the unit LLMs read and are billed in |
| Tick | One turn of the agent loop, 30 sim-seconds |
| Write | One LLM call that writes a node's opening or closing in the life tree |
| Decision | The agent choosing an action. Here it costs 2 calls: appraise, then decide |
| Skim | A life written only down to months |
| LoRA | A small add-on layer trained on top of the model, which changes behavior without editing all its weights |
| KV cache | Memory the model keeps for every token in its context, so RAM use grows with context length |
| GPU-hour | One GPU rented for one hour |

## Base numbers everything uses

| Number | Value | Evidence |
|---|---|---|
| Qwen text call | 11.8 s mean, 970 prompt tokens, 136 generated, 14.9 tokens/s, 18.2 GB peak | [M: `out/overnight/latest/calls.jsonl`, 55 calls] |
| Qwen timing formula | seconds = 0.00563 x prompt tokens + 0.0689 x generated tokens - 3.35 (R² 0.90) | [E: my fit on those 55 calls, leaving out the first call, which probably included loading the model]. Its context ranged only 553 to 1,266 tokens, so long-context predictions are extrapolation |
| Cosmos 16-frame clip, 448x256, 30 steps | Battery: 83.5 s mean. AC: 135.8 s evening, 144.7 s after 23:54 | [M: `out/world_data_20261104/manifest.jsonl`, 54 clips, 0 failed] |
| Cosmos 84-frame segment | 828 s (5,798.7 s over 7 segments) | [M: `out/continuous_video/run.log`, file times] |
| Homeostatic update | 73 s, including that run's share of validation. 20.1 GB peak | [M: `out/homeostatic/probe-*` file times, `train.jsonl`] |
| LoRA adapter size | 87 MB | [M: `out/homeostatic/pilot/adapters.safetensors`] |
| 30 s of finished 448x256 video | 1.29 MB | [M: `out/continuous_video/final.mp4`] |
| Writes in a whole life down to days | 24,930 | [M: counted from `kokopelli/life/windows.py`, default seed] |
| Hosted Qwen | $0.25 in, $0.75 out, per million tokens. Other listings show $0.117/$0.455 and $0.08/$0.50 | [P: S11, S12] |
| Hosted cost per text call | $0.000345 = 970 x $0.25/M + 136 x $0.75/M | [E] |
| Mac electricity | $0.015/hour = 0.10 kW x $0.15/kWh | [E, from P: S15, S16. Chip about 70-80 W, plus the rest of the machine as a guess] |

### Are the earlier estimates right?

| Claim | Verdict |
|---|---|
| `demo` preset, about 2 min per tick | **Only outside Low Power Mode.** Clip 83.5 s + about 15 s Qwen + a guessed 30 s reload = about 2.1 min. At recent speeds, 136-177 s + the same 45 s = 3-3.7 min [E] |
| Real 30-second tick, about 2 hours | **Confirmed.** 9 x 828 s = 2.07 h [E from M]. It ran on Nov 2, and I can't tell which power mode was active |
| 141-170 h for 30 minutes of video | **The arithmetic checks out, on low-power speeds.** 43,200 frames / 11 new frames per chunk = 3,927 chunks. x 130 s = 142 h, x 156 s = 170 h. At the battery speed, 3,927 x 83.5 s = 91 h [E]. It also assumes a conditioned chunk costs what a plain one does, which is unmeasured |
| Low power mode may inflate timings | **Likely true.** See below |

### Low power: the evidence

`pmset -g custom` shows `powermode 1` (Low Power) on AC and `powermode 0` (Automatic) on battery [M: `pmset`, read 2026-11-05]. So plugging in *slows the Mac down*.

The clip log recorded this happening. The last clip on battery took 93.5 s. `pmset -g log` shows AC connected at 20:31:19, and the very next clip took 126.5 s [M: `manifest.jsonl`, `pmset` log]. Clips later sat at 126.1-126.9 s for about 17 minutes, which looks like a fixed power cap [M]. Mean ratio: 135.8 / 83.5 = 1.63 [E].

It isn't proven: this is one transition, and the clips later rose to 177 s while other work was running, with 8.7 GB free and 2.4 GB of swap [M: `out/ops/MORNING.md`]. T1 settles it.

Homeostatic training and all queued jobs have run or will run in this mode. The Qwen speed from Nov 3 may be affected too, though I can't tell.

---

## 1. Longer-life tests

### 1.1 Candidate input structures

"Input structure" means what the model is shown of the past each time it decides.

**Shared assumptions [E]:** 600 fixed tokens per prompt (324 of system rules [M: 1,325 chars x 0.245 tokens/char], plus person and instructions). One past event is 110 tokens [M: mean closing length]. A logged decision is 170 tokens, adding about 60 for the action and feeling. 8 decisions per sim-day for the growth columns.

| Structure | Tokens per decision | How it grows with life length | Week (56 decisions) | Year (2,920) | Childhood (30,584) | Ages 2-30 (81,816) |
|---|---|---|---|---|---|---|
| **A. Full transcript** | 600 + 170n | Linear per decision, so total cost is quadratic | 10,120 | 497,000 | 5.2 M | 13.9 M |
| **B. Hierarchical summaries** (`kokopelli/life/memory.py`) | 1,000-1,700 | With tree depth, not time | 1,000-1,700 | same | same | same |
| **C. Memory retrieval** | 1,480 = 600 + 8 x 110. About 2,100 if the agent writes its own search query, across 2 calls | Prompt flat, index linear | 1,480 | same | same | same |
| **D. State vector + recent events** | 1,300 = 600 + 150 state + 5 x 110 | Flat | 1,300 | same | same | same |
| **E. Hybrid: state + short outline + 4 retrieved** | 1,490 = 600 + 150 + 300 + 440 | Flat | 1,490 | same | same | same |
| **F. Vault with tools** (proposal section 11) | About 3,750 = 1,500 x 2.5 calls | Flat, if notes really get deleted | 3,750 | same | same | same |

Structure B's range comes from measured prompts of 553-1,266 tokens [M: `calls.jsonl`]. Each tree level added about 90 tokens (day 1,146 vs month 965) [M], and scenes sit up to 5 levels below days: 1,146 + 450 = about 1,600, plus 90 for vivid memories, which the trial never triggered [E].

Add **672 tokens** to any row when the agent sees frames: 6 images x 112 tokens, where 112 = (448/32) x (256/32) [E from M: Qwen `config.json`, patch 16 x merge 2].

**Why the transcript is out, except as a short control:**

- **Context limit:** 262,144 tokens [M: Qwen `config.json`; matches P: S11]. It's reached at n = 1,538 decisions, about 192 sim-days at 8 a day [E].
- **Mac RAM limit, which comes sooner:** the KV cache is 36 layers x 2 x 8 heads x 128 x 2 bytes = 147 KB per token. About 12 GB is free after the model and macOS, so about 81,000 tokens, or 475 decisions, or **59 sim-days** [E, assumes 16-bit cache values].
- **Speed:** at 81,000 tokens each call takes about 7.6 minutes at 178 tokens/s [E, extrapolated]. Reusing the cached part of the prompt could cut that, but I haven't confirmed the runner can.
- **Money:** 1,536 decisions read 600n + 170n²/2 = 201 M input tokens, or $50 for just 192 sim-days [E].

**What each one risks:**

| Structure | How it probably fails | Evidence |
|---|---|---|
| A | Runs out of room. Also copies itself | Measured below: the small model copies what it can see |
| B | Summaries lose what mattered. Depends on salience working, and the trial's did not | [M: section T3] |
| C | Can't retrieve what it doesn't know to look for. Long-range time and cause links are the known weak spot | LoCoMo: retrieval and long context help but stay well short of humans [P: S19] |
| D | The most likely to lose its sense of a life story | None; this is my reasoning |
| E | More parts to build and tune | None here. Generative Agents combines a full record, reflections and retrieval, but its run was short [P: S20] |
| F | Most calls per decision. The proposal's deleting of notes means recall depends on weights, which T1-T9 don't change | Proposal section 11 |

**Now read this:** `kokopelli/life/memory.py:31-36`. Before T2, explain why `_recent` costs the same tokens in year 25 as in year 2, and predict which line would change if you wanted more detail. Then `kokopelli/life/memory.py:39-53`: what does `vivid_floor` do when every salience is 0.2 or less, as it was in the trial?

### 1.2 What a span costs

Each decision is 2 calls at 12 s, plus the tree's writes. Text only, one life, no weight updates [E, from M call time and write counts].

| Span | Decisions per sim-day | Decisions | Calls | Mac time | Hosted Qwen |
|---|---|---|---|---|---|
| Week | 1 / 8 / every 30 s | 7 / 56 / 13,440 | 30 / 128 / 26,896 | 6 min / 26 min / 3.7 days | $0.01 / $0.04 / $9 |
| Year | 1 / 8 / every 30 s | 365 / 2,920 / 700,800 | 1,620 / 6,730 / 1.4 M | 5.4 h / 22 h / 195 days | $0.56 / $2.32 / $483 |
| Ages 2-12 | 1 / 8 / every 30 s | 3,823 / 30,584 / 7.3 M | 16,970 / 70,492 / 14.7 M | 2.4 days / 9.8 days / 5.6 years | $5.85 / $24 / $5,061 |
| Ages 2-30 | 1 / 8 / every 30 s | 10,227 / 81,816 / 19.6 M | 45,384 / 188,562 / 39.3 M | 6.3 days / 26 days / 15 years | $16 / $65 / $13,538 |

"Every 30 s" assumes 1,920 ticks in a 16-hour waking day. Hosted prices ignore rate limits and image fees, which I couldn't find.

**Rendering all of that is out of reach.** One waking day at the GPU preset is 1,920 ticks x 4.5 GPU-minutes = 144 GPU-hours, or $416 on a $2.89 H100. A whole life: 10,227 x $416 = **$4.3 million** [E]. This is why the proposal has an imprint gate (a cheap call that picks which scenes get rendered). A gate of one 30-second scene per week over 28 years is 1,461 x 4.5 min = 110 GPU-hours, or $317 on RunPod and $74 at PACE's rate [E]. The same on the Mac: 1,461 x 2.07 h = 126 days [E].

### 1.3 The tests, in order

```
T1 power mode ──> every Mac timing below
T2 token audit ──> T6
T3 skim life ──> T5 ──> T6 ──> T7 ──> T8 ──> T9
T4 frames vs text ──> decides whether G3, G4 and rendering in T9+ are worth paying for
                                    T8 ──> T10 ──> T11
Noise check (queued) ──────────────────────^
G1 Cosmos speed ──┐
G2 SimWorld gate ─┴─> G3 10 ticks ──> G4 60 ticks
```

T1-T9 are independent of the G track. T10 needs the noise check, and also a locked pre-registration, which is `experiments/benchmarks/PREREG.md`, still marked DRAFT.

Each test also has a line for you: **predict the result before it runs.** Write it down, and we'll compare after.

#### T1: Does Low Power Mode explain the slowdown?

| | |
|---|---|
| **Question** | How fast is this Mac really? |
| **Setup** | Everything else stopped. You change the mode, since it needs `sudo`: `sudo pmset -c powermode 0`, or `2` for High Power. On AC, alternate modes across 9 clips (same prompt and seed, 3 each of Low, Automatic, High) and 20 replayed Qwen calls per mode |
| **Measures** | Median seconds per clip and tokens/s per mode, and temperature if you run `sudo powermetrics` |
| **Pass** | Automatic or High is 100 s or less per clip, against about 126 s on Low |
| **Price, time** | $0.01. About 30 min = 9 x about 130 s + 60 x 10 s [E] |
| **If pass** | Keep AC out of Low Power before the queue runs. Rescale every Mac estimate in this file by the measured ratio |
| **If fail** | Look at memory pressure and other jobs instead. Keep current numbers |
| **Predict** | What ratio do you expect, and will Qwen slow down as much as Cosmos does? |

#### T2: Token audit of the input structures

| | |
|---|---|
| **Question** | Which structures fit a long life, in tokens? |
| **Setup** | No model. Build each structure's prompt over a synthetic life with real text lengths, and count with Qwen's tokenizer. Needs about 2 hours of code, and `kokopelli/mind/` or a new file, not `kokopelli/life/` |
| **Measures** | Tokens per decision after 56, 2,920, 30,584 and 81,816 decisions. Predicted seconds and dollars |
| **Pass** | 2,500 tokens or fewer at ages 2-30, and growing 1.5 times or less from year 1 to year 28 |
| **Price, time** | $0. Under a minute to run |
| **If pass** | Goes on to T6 |
| **If fail** | Drop it, or cap it. Expect A to fail, and keep it only as a capped control |
| **Predict** | Which structure grows most that the table above calls flat? (Hint: think about the people list in `_known`, `kokopelli/life/prompts.py:76`) |

#### T3: One real skim life

| | |
|---|---|
| **Question** | Does the generator write a life that changes, using the prompts changed after the trial? |
| **Setup** | One life to months: 972 writes = 2 x (1 + 29 + 116 + 340) [M: `kokopelli/life/windows.py`]. `make overnight` covers a bit more, so restrict it, or use `make trial` settings |
| **Why now** | In the trial's first 20 openings, "pigeon" appears in 20 and "wallpaper" in 13. Neighboring openings shared 49% of their words on average, and two pairs shared 98-100% [E: my calculation from M: `out/overnight/latest/life.db`]. Every node below the life root had salience 0.2 or less, against the prompt's own target of about 2 in 10 above 0.3 [M]. The report still says "0 of 12 near-repeats", because that check only looks at closings. Note `kokopelli/life/prompts.py` was edited at 17:25, after that run |
| **Measures** | Word overlap of neighboring openings, salience distribution, share mentioning each life stage's features, contradictions you find by reading one thread |
| **Pass** | Mean overlap under 0.3, no pair above 0.7, at least 10% of nodes over salience 0.3, at least one over 0.7, and a clear change between ages 3, 10 and 25 |
| **Price, time** | $0.05 on the Mac, 3.2 h = 972 x 11.8 s. Or $0.33 hosted [E] |
| **If pass** | Go to T5 |
| **If fail** | Fix prompts and focus rules, then rerun. **Don't go deeper:** a repeating month just becomes a repeating day |
| **Predict** | What share of nodes will clear salience 0.3? |

#### T4: Do frames change decisions at all?

| | |
|---|---|
| **Question** | Does seeing video change what the agent does, compared with reading a description? |
| **Setup** | Reuse the 54 existing clips. Same decision prompt in 3 arms: 6 frames, a text caption of the clip, or no scene information. 5 samples each. Qwen writes the captions first |
| **Measures** | How often the decision distribution differs between arms, compared with the difference between repeated samples in one arm |
| **Pass (video matters)** | Frames beat captions by more than sample noise on at least 30% of clips |
| **Price, time** | $0.05. 3.4 h = (54 x 3 x 5 + 54) x about 14 s [E, frames add 672 tokens, about 3.8 s]. The text-plus-image cost is unmeasured |
| **If video matters** | Keep rendering in the training budget |
| **If it doesn't** | Rendering becomes a demo cost only, and lives can be text with occasional renders. **This could remove most of the bill** |
| **How it can mislead** | These clips are 0.67 s long, and many don't match their prompts [note from earlier session]. Short noisy clips could understate video's effect, so a negative result needs one more check on clips of 2 s or longer |
| **Predict** | On what share of clips do frames matter? |

#### T5: One year, down to days

| | |
|---|---|
| **Question** | Does the memory stay coherent when the tree goes deep? |
| **Depends on** | T3 |
| **Setup** | One whole school year: about 890 writes = 24,930 / 28 [E]. Then 30 fact questions on what happened early, answered from memory only |
| **Measures** | Prompt tokens over time, repetition across days, contradiction rate, fact recall, pressures being resolved or forgotten |
| **Pass** | Prompt tokens stay within 20%, under 5% contradictions, repetition stays under T3's limits |
| **Price, time** | $0.04, 2.9 h on the Mac. Or $0.31 hosted [E]. Under $0.10 for an LLM judge |
| **If fail** | Tune `LIFE_MEMORY` and try T5 again before moving on |

#### T6: Input-structure bake-off

| | |
|---|---|
| **Question** | Which structure lets the agent remember and stay itself, at the lowest cost? |
| **Depends on** | T2 (which arms survive), T5 (a life to replay) |
| **Setup** | No weight updates. Freeze one generated life and replay it to each structure at 200 decision moments, 3 samples each, 5 arms (A capped, B, C, D, E). Plant 30 facts and ask about them later. Fork one core moment and rerun, to test the proposal's "Traceable" criterion |
| **Measures** | Recall of planted facts after 1 week, 6 months and 1 year. Contradictions. Whether the forked moment changes later decisions beyond sample noise. Tokens and seconds per decision |
| **Pass** | Recall of 70% or more at 6 months (25% is chance on 4 choices), under 5% contradictions, a detectable effect from the fork, and 2,500 tokens or fewer |
| **Price, time** | Mac: about 24 h, $0.36. 2,400 calls x 11.4 s + 600 transcript-arm calls x about 100 s. Hosted: $3.62 = 13.9 M in x $0.25 + 0.18 M out x $0.75. Sonnet batch judge: $6 = 4.5 M x $1 + 0.3 M x $5 [E, P: S14] |
| **If a clear winner** | Use the cheapest arm within 5 points of the best |
| **If all fail recall** | Try consolidation at sleep (writing lessons) instead of more retrieval |
| **Predict** | Which arm wins, and which loses first? My prediction is at the end of this section |

#### T7: The agent lives a week

| | |
|---|---|
| **Question** | Does a real agent replacing the random one behave like an agent? |
| **Depends on** | T6 |
| **Setup** | Closed loop, winning structure, 8 decisions a day, 3 seeds and 1 random control. Actions feed the tree's closings. Text only |
| **Measures** | Invalid replies, spread of actions, whether actions follow from events |
| **Pass** | Under 2% invalid. Uses at least 4 actions, none above 60%. Differs from the random control. Decisions reference actual events when you read them |
| **Price, time** | $0.02, 1.7 h = 4 x 128 calls x 12 s, or $0.18 hosted [E] |
| **If fail** | Watch for collapse. Homeostatic training settled on one action (`rest`, 293 of 293) [M: `probe-0.0001/validation.jsonl`], and the same habit may appear here |

#### T8: The agent lives a year

| | |
|---|---|
| **Question** | Does it hold together over a year with a realistic decision budget? |
| **Depends on** | T7 |
| **Setup** | 3 decisions a day, 2 seeds, zooming into high-salience days |
| **Measures** | T5's and T6's measures, repeated at month 1, 6 and 12. Does the character stay recognizable? |
| **Pass** | Tokens within 20%. Under 5% contradictions. Recall at month 12 within 10 points of month 1. Salience still varies |
| **Price, time** | 20.5 h = 2 x 3,080 calls x 12 s, $0.31 on the Mac, or $2.12 hosted [E] |
| **If fail** | Don't start T9. Fix what degraded |

#### T9: A childhood with one fork

| | |
|---|---|
| **Question** | Does one core early moment carry forward in a predictable way, without weight changes? |
| **Depends on** | T8 |
| **Setup** | 1 decision a day, ages 2-12. At age 6, fork with and without a core moment, then run both to 12. 2 seeds. Also test whether stage settings change behavior |
| **Measures** | Decision differences on unrelated questions at 12, against seed noise. Pre-register the predicted direction before starting |
| **Pass** | Predicted direction in both seeds, beyond seed noise |
| **Price, time** | About 170 h = 2 seeds x 1.5 x 16,970 calls x 12 s, $2.55 on the Mac. $17.55 hosted [E]. **Use the hosted route or the Mac gets blocked for a week** |
| **If pass** | Prompt context alone carries the moment. Good, but also the bar T10 must beat: proposal criterion 2 says if a prompt gets the same instinct, there is no product |
| **If fail** | Revisit structure and salience before training on these lives |

#### T10: First weights test: does living beat being told?

| | |
|---|---|
| **Question** | The core bet: does a LoRA from lived experience move behavior differently from one trained on a description of the same facts? |
| **Depends on** | T8, the benchmark noise check, your approval of `experiments/benchmarks/PREREG.md` |
| **Setup** | As in the pre-registration: base, lived, described, shuffled and flipped arms, at least 3 seeds. Sleep training has never run; only GRPO has, on homeostatic. SFT per-step time is unknown |
| **Measures** | The pre-registered contrasts on Holt-Laury and lotteries, plus guardrails |
| **Pass** | As `PREREG.md` states: correct direction, Holm-corrected p under 0.05, at least 3 seeds correct, none opposite |
| **Price, time** | Adapters: 12 x 500 steps x 24 s = 40 h, $0.60. Evaluation: 78 h, $1.17 (below) [E, assumes SFT is as slow as a GRPO step, likely pessimistic] |
| **If pass** | First real evidence for the bet. Go to T11 |
| **If fail** | Check adapter strength first, using `shuffled` and a much larger dose. If a strong, well-trained adapter still doesn't separate, **stop before paying for T11** |

#### T11: Decades with yearly sleep

| | |
|---|---|
| **Question** | Do many stacked sleeps build a stable perspective? |
| **Depends on** | T10 |
| **Setup** | Ages 2-30, 1 decision a day, one LoRA update per sim-year: 45,384 calls + 28 sleeps. Add the proposal's 10-year recurring-deadline test and Interpreter arm if you want them |
| **Measures** | Benchmarks after each sleep, general ability guardrails, forked-life differences, then criterion 4's human judges |
| **Pass** | The T10 contrasts grow or hold, ability stays within 1 point, and forked lives differ in explainable ways |
| **Price, time** | One life: 244 h = 151 h + 28 x 3.33 h, $3.66 on the Mac. Hosted plus rented: $70 = $15.63 + 28 x 0.67 h x $2.89. The 0.67 h assumes a rented GPU trains 5 times faster, a guess. 4 lives: $279 [E] |
| **If fail** | Report what T10 showed, and don't repeat this at larger scale |

#### The GPU track

| Test | Question | Setup | Pass | Price, time |
|---|---|---|---|---|
| **G1: Cosmos speed** | How fast is Nano really at `gpu_full`? | One H100 or H200: 5 chunks at 832x480, 181 frames, 35 steps, with `vllm-omni` | Chunk under 120 s, without memory errors | 1 h: $0.67 PACE, $2.89 RunPod [E, P: S1, S4]. This replaces the plan's biggest unknown |
| **G2: SimWorld gate** | Does Unreal run headless and step in sim time? | `tools/pace/wmloop_gate.sbatch`, already written [M: `SIMWORLD.md`] | Checks 2 and 6, the "biggest risk", pass | 2 h: $1.35 PACE, $5.78 RunPod [E]. If `MoveForward` doesn't play across paused ticks, the sim design changes |
| **G3: 10 ticks** | Does the full loop run? | `WMLOOP_TICKS=10 sbatch tools/pace/wmloop_run.sbatch` | Finishes, with drift measured against real renders | 1.3 h of the 8 h run below: $0.90 PACE, $3.85 RunPod [E] |
| **G4: 60 ticks** | The full 30-minute test | Same, 60 ticks | Finishes, video continuous, drift bounded | See section 2.2 |

G2 is not guaranteed to work on an H100 or H200. I couldn't confirm Unreal's offscreen Vulkan renders on those GPUs, and older reports show GPU selection and offscreen Vulkan problems [P: S21]. If PACE's L40S nodes are available, try the gate there too [P: S4].

### My prediction for T6, after you've written yours

B or E wins. I'd guess pure retrieval (C) misses things no one asks about, and state plus recent events (D) forgets its story. Reasoning only, with no data on Qwen here.

---

## 2. Price map for the full system

### 2.1 One table

| Component | Low | Likely | High | Assumptions |
|---|---|---|---|---|
| **Life generation and tests T1-T9** | **$3.39** | **$34.46** | **$138** | Low: Mac, 226 h x $0.015. Likely: hosted for T6, T8, T9 ($9.62 + $2.12 + $17.55), T1-T5, T7 on Mac ($0.17), $5 for judges. High: likely x 4, for reruns [E] |
| **Full life with sleeps, T11** | **$3.66** | **$69.80** | **$279** | Low: Mac, 244 h. Likely: hosted plus rented training. High: 4 lives [E] |
| **30-minute test: G2-G4** (Cosmos, Qwen, SimWorld) | **$4.37** | **$52** | **$264.50** | Low: 6.5 h x $0.673. Likely: (2 attempts x 8 h + 2 h gate) x $2.89. High: (3 x 16 h + 2 h) x $5.29 [E, P: S1, S4]. Section 2.2 |
| **Homeostatic and sleep training** | **$1.10** | **$3.08** | **$163.60** | Low: 33.5 h + 40 h on Mac. Likely: 5 rounds, 165 h + 40 h on Mac. High: ported to rented GPU, 205 h / 5 x $3.99 [E]. Section 2.3 |
| **Benchmarks** | **$1.17** | **$3.51** | **$67.60** | Low: 78 h on Mac. Likely: 3 rounds. High: rented, 10 times faster: 7.8 h x 3 x $2.89 [E]. Section 2.4 |
| **GPU pipeline setup and storage** | **$13.46** | **$128.70** | **$422.40** | Low: 20 h bring-up x $0.673, with 1 TB free storage if your allocation includes it. Likely: 30 h x $2.89 + 300 GB x $0.07 x 2 months. High: 60 h x $5.29 + 500 GB x $0.07 x 3 months [E, P: S1, S4, S5] |
| **Dev panel** | **$0** | **$0** | **$60** | Already built and running locally [M: `out/ops/MORNING.md`]. High: a small server at about $10 a month for 6 months, if you want to share it, which is a guess [E] |
| **Total** | **$27.15** | **$291.55** | **$1,395.10** | Sums of the rows above |

**Check the totals:**
- Low: 3.39 + 3.66 + 4.37 + 1.10 + 1.17 + 13.46 + 0 = **27.15**
- Likely: 34.46 + 69.80 + 52 + 3.08 + 3.51 + 128.70 + 0 = **291.55**
- High: 138 + 279 + 264.50 + 163.60 + 67.60 + 422.40 + 60 = **1,395.10**

**Low is $9.32 in cash** if PACE credits cover the $17.83 of GPU work [E]: 27.15 - 4.37 - 13.46. That needs your allocation confirmed.

**Add-on, not in your list but in the proposal:** the frontier "sleep interpreter" (section 13b). One night is 20,000 tokens in and 2,000 out on Opus 5.5 batch: $0.06 = 20K x $2/M + 2K x $10/M [E, P: S14]. Yearly review for 28 years, with 200,000 tokens in and 4,000 out: $0.44 each, $12 total. Nightly across a childhood: 3,823 x $0.06 = $229 [E]. The proposal also warns you to check a provider's terms before its text becomes training data, which is another reason to keep the interpreter to scoring.

**Not priced:**
- **Claude Code and coding agents.** Four terminal sessions were running tonight [M: `MORNING.md`]. I don't know your plan, and if it's billed by the API this could beat everything above.
- **Human judges** for criterion 4.
- **Your time,** and a Mac blocked for weeks.
- **Replacing the agent's model on Tinker,** covered below.

**Your earlier rule:** notes from a previous session say a rented GPU conflicts with your no-spending rule. If that still holds, **Low is the plan**, and PACE access is the blocking step. Nothing above spends money without your decision.

### 2.2 The 30-minute test: three different things

| Version | What you get | Hardware | Time | Cash |
|---|---|---|---|---|
| **a. Demo** | 60 ticks, 30 sim-minutes, mock sim. 16 frames a tick, so 60 x 11 / 24 = **27.5 s of video** | Mac | 2.1-3.7 h [E] | $0.03-$0.06 |
| **b. Real video on the Mac** | 30 minutes continuous at 448x256, mock sim, no SimWorld | Mac | 91-170 h, with 124 h using the measured long segment rate: 60 x 2.07 h [E] | $1.37-$2.55. Blocks the machine for 4-7 days |
| **c. Full system** | 30 minutes at 832x480, SimWorld physics, real Qwen | Rented or PACE GPU | 4.5-16 h, likely 8 h | See below |

**Version c's hours [E]:**
- Cosmos: 60 ticks x 4 chunks x 57 s = 3.8 h. The 57 s = 59.83 s x 181/189, from a table a third party attributes to NVIDIA [P: S8]. I couldn't open NVIDIA's own file, so check it, or better, run G1.
- A hosted deployment reported about 4 minutes against that table's 208 s at 720p, so about 1.15 times slower in practice [P: S8b].
- Low 4.5 h: Cosmos plus 20 min of Qwen, plus light sim. Likely 8 h: 1.5 times for loads, conditioning and retries, plus 1 h of sim, plus Qwen. High 16 h: 3 times overhead, plus slow sim. **SimWorld's speed is entirely unmeasured.**

**Options for one 8-hour run of version c:**

| Option | $ per GPU-hour | Cost of 8 h | Notes |
|---|---|---|---|
| **PACE H200** | $0.673 [P: S4, a 2024 post, confirm current rate] | **$5.38** | Needs access. Credits may cover it. See below |
| **RunPod H100 PCIe, community** | $1.99 [P: S1] | $15.92 | Less reliable hosts, and Vulkan support for Unreal isn't confirmed |
| **RunPod H100 PCIe, secure** | $2.89 [P: S1] | $23.12 | The assumption in Likely |
| **RunPod H100 SXM, secure** | $3.99 [P: S1] | $31.92 | |
| **RunPod H200** | $5.29 [P: S1] | $42.32 | The most memory headroom, and the card the README recommends |
| **Lambda H100 PCIe** | $3.29 [P: S2, from Nov 16, 2026] | $26.32 | |
| **Vast.ai H100** | $2.00-$3.50 [P: S3, as of March 2026; vast.ai's own page loads prices dynamically] | $16-$28 | Marketplace, varies by host |
| **RunPod L40S** | $1.09 [P: S1] | $17.44 for 16 h | Doubled time is a guess. Should render Unreal well, but Ada isn't in the README's supported list (Ampere, Hopper, Blackwell) [M: `models/Cosmos3-Nano/README.md`] |
| **RunPod A100** | $1.79 [P: S1] | $24.34 for 13.6 h | 1.7 times slower is a guess |
| **Hosted video API** | $0.112 per video second for Seedance [P: S17] | $201.60 for 1,800 s | A different model, with no frame conditioning, so a scale check only. I found no working Cosmos3-Nano hosted price; the DeepInfra listing returned 404 |

Memory: Nano's weights take about 32 GB [P: S9], and one calculator estimates 34 GB peak [P: S10]. Qwen peaks at 18 GB on the Mac [M], and Unreal needs 6 GB or more [M: `simworld/README.md`]. That's about 58 GB, which fits 80 GB with not much to spare. Disk: 150 GiB for Cosmos [P: S9], 50-200 GB for SimWorld [M: `simworld/README.md`].

**Georgia Tech PACE, for you to confirm:**

| Question | What I found | Status |
|---|---|---|
| Can you get on Phoenix? | Faculty accounts, students through an advisor, undergraduates without an advisor through EVPR-PACESHIP [P: S7]. Notes from October say your PACESHIP wasn't approved yet | **You confirm** |
| Free credits | 10,000 CPU-hours-equivalent a month, rolling over to 4 months, GPUs allowed, for faculty free-tier accounts [P: S5]. Other pages say "$68" or 68 credits a month [P: S6] | **Unit and eligibility unclear** |
| GPU rate | H100 and H200, $0.673 per GPU-hour, from Oct 2024 [P: S4] | **May be old** |
| GPU-hours per month, if it's $68 | 68 / 0.673 = about 101 [E] | Would cover the Low path's 26.5 hours |
| ICE | Instructional cluster. I found no terms | Ask if a class can use it |
| The `embers` queue | L40S nodes exist under this QoS [P: S4]. My memory says it's a free queue where jobs can be interrupted, but **I could not verify that**. The loop can resume, so it could suit this | **Ask PACE** |

### 2.3 Homeostatic training, in detail

| Number | Value |
|---|---|
| One training run, 150 updates | 3.05 h = 6 x 30.5 min per 25 updates with validation [E from M] |
| Held-out evaluation per run | About 33 min: 100 lives x 10 turns x 1 s x 2 splits [E] |
| Full comparison: 3 rewards x 3 seeds | 9 x 3.6 h + 1.1 h for base models = 33.5 h [E] |
| 5 rounds, if you tune | About 165 h [E] |

All of these were measured in Low Power Mode, so T1 may shrink them.

**Tinker option:** it lists Qwen3-8B at $0.44 per million training tokens, but **doesn't list Qwen3-VL-8B** [P: S13, prices as of Oct 19]. 150 updates x 3 states x 9 actions x about 250 tokens = 1 M tokens, about $0.45 a run [E]. It would be a different, text-only model, and your training method would need porting, so results wouldn't carry over directly. A GPU port (MLX doesn't run on NVIDIA) is also unbuilt; I didn't price that coding work.

### 2.4 Benchmarks, in detail

| Item | Arithmetic [E] | Result |
|---|---|---|
| Noise check, queued now | (1 Holt-Laury menu + 6 lotteries) x 3 templates x 50 samples = 1,050 x 3-6 s | 1-1.75 h, $0.03 |
| Main instruments, full | (4 trained arms x 3 seeds + base) = 13 x 1,050 x 6 s | 22.75 h |
| Guardrails, full | 13 x (342 MMLU x 6 s + about 541 IFEval x 24 s). The IFEval size is from memory | About 55 h |
| Total | | About 78 h, $1.17 |

[M for counts: `experiments/benchmarks/` in the `feat/evals` worktree; no results exist yet.] Rented GPU batching should make this much faster: 10 times is a guess. Guardrails need `lm-eval` and an OpenAI-style server, which `llm_model` isn't, so this assumes a little setup.

### 2.5 Storage

Small, unless you keep everything:

| Item | Size |
|---|---|
| Models on the Mac | 49 GB = 33 + 16 [M: `du models/*`]. 320 GB free [M: `df`] |
| A clip | 28 KB mean [M: `manifest.jsonl`] |
| 30 minutes at 448x256 | 77 MB = 60 x 1.29 MB [E from M] |
| A mock 60-tick run with its logs | 29 MB [M: `du`] |
| Adapters: 28 yearly / nightly for a whole life | 2.4 GB / 893 GB = 10,227 x 87.3 MB [E from M]. **Don't save nightly adapters** |
| Rented volume | $0.07 per GB-month [P: S1] |

---

## 3. Expected effect of each spend

Ranked by value per dollar. Confidence means how sure I am of the *stated effect*.

| Rank | Spend | Price | What we expect to learn or change | Confidence | How it could show nothing | Result that makes it not worth repeating |
|---|---|---|---|---|---|---|
| 1 | **T1 power mode** | $0.01 | About 1.6 times speedup on all Mac work | Medium: strong natural experiment, n of one | Thermal limits or memory pressure may set the speed instead | Done once, unless the machine changes |
| 2 | **T2 token audit** | $0 | Removes dead structures. Near certain for the transcript | High on tokens. Says nothing about quality | Synthetic text may have different lengths than real writing | Rerun only if a structure changes |
| 3 | **T4 frames vs text** | $0.05 | Whether video belongs in training at all, the plan's biggest money decision | Low on the direction | 0.67 s clips and noisy prompts may hide a real effect | If frames don't beat captions on longer clips either |
| 4 | **Noise check** (queued) | $0.03 | Whether the instruments can detect a shift at all | Medium. **No Qwen data exists yet** | It only tests base model behavior | If answers are frozen (95%+ one answer) or coin flips, stop using that instrument |
| 5 | **T3 skim life** | $0.05 | Whether new prompts fixed repetition | Medium | Reading a life and counting words don't always agree | Passes once, or fails twice with no new prompt idea |
| 6 | **G2 SimWorld gate** | $1.35-$5.78 | Whether real physics works. Biggest technical risk | High that you'll learn something. **Unknown whether it passes** | Fails on site setup rather than on SimWorld itself | Passes, or fails on a design assumption. Then rethink instead of retrying |
| 7 | **G1 Cosmos speed** | $0.67-$2.89 | Replaces the largest price guess | High | Numbers vary across GPU type | After one run per GPU type |
| 8 | **T6 bake-off** | $0.36-$10 | Picks the input structure | Medium. The ranking may be close | Differences within noise, or the planted facts don't reflect what matters | Clear winner, or every arm within 5 points |
| 9 | **T5, T7, T8** | $0.40-$2.50 | Whether coherence survives, and whether a real agent replaces the random one | Medium | Coherent text can still be flat. Metrics can pass while the life is dull, so read samples | Passes once. Repeat after large changes |
| 10 | **T10 first weights test** | $2-$170 | **The only test of the bet.** Does lived beat described? | **Low. Evidence is thin.** Narrow fine-tuning can shift broad behavior, as in emergent misalignment [P: S18], but that used a very different task. The description-experience gap is human evidence (Hertwig 2004, as cited in `PREREG.md`). I found nothing showing it in LoRA-trained LLMs | Adapter too weak, or a small dataset. Far-transfer instruments may be insensitive even if an effect exists, which is why `flipped` and `shuffled` exist | A well-powered, correct-dose null. Stop before T11 |
| 11 | **T9 childhood fork** | $2.55-$18 | Whether an early moment carries forward via context | Medium for prompt effects, which are likely large. **It doesn't test weights** | Salience fails and memory drops the moment | Once it passes. A prompt effect doesn't get better with scale |
| 12 | **Homeostatic rounds** | $1-$164 | Whether the reward can teach | **Low.** Best validation is 25.2, the same as idling. `probe-0.0005` was 100% invalid replies and got idle's score by default. `probe-2e-5` picked only `confide` and `rest`. Base model 29.4, greedy 9.3, planner 6.3 [M: `out/homeostatic/`]. **Nothing has learned yet** | The simulator can't test reward hacking, and comfort seeking is a flagged design problem | Stop buying seeds now. Don't run the full 9-run grid until one run beats idle with varied actions. If two more design changes fail, stop |
| 13 | **G4 full 30-minute test** | $5-$265 | Proves the system runs end to end, and gives real drift numbers and a demo | High that it's an integration result. **Low that it shifts any weights**: 60 decisions don't train anything, and `kokopelli/mind/` runs had about 18 decision points in 60 ticks on mocks [M: `out/mind/mock_60/mind_summary.json`] | Drift only means something against real SimWorld renders | Once for proof. Repeat only for a demo, or after G3 finds a real issue |
| 14 | **T11 decades** | $4-$279 | Whether perspectives stack over time, or wash out | **Very low until T10 passes** | Catastrophic forgetting, or stacked LoRAs drift. Credit over years is unsolved, as the proposal says | T10 failed, or contrasts don't grow after 10 sleeps |
| 15 | **Pipeline setup and storage** | $13-$422 | Nothing by itself; it's what G3 and G4 need | High that it costs this. The largest single rented line | Debugging on a paid GPU is where budgets go. Use dry runs and the fake server first | Don't rent a volume for longer than a run. Delete it after |
| 16 | **Sleep interpreter** | $0-$229 | Whether a coach beats fixed sleep | Low. Only the proposal's reasoning | T10 hasn't shown sleep matters at all | Skip until T10 passes |
| 17 | **Dev panel** | $0 | Faster debugging. No effect on results | High | | Don't spend on hosting unless someone else needs it |

**Blunt summary:** the first $10 buys most of the information. The next $10-$50 gets real answers on SimWorld and GPU speed. Everything above that buys scale, and scale should wait until T10 says the idea works. If T4 says video doesn't matter and T10 says lived beats described, **a long text-only life with a few rendered scenes becomes the plan**, and that's likely under $100.

**Evidence weakest of all:**
- Whether frames influence decisions: no data at all yet.
- SimWorld's speed: never run on a real server.
- Whether a LoRA from lived text differs from one from described text: no data.
- Whether salience will work: the only real data says no.

---

## What I need from you

These are yours to decide. I've kept my recommendation out of the first two, as you asked, so tell me yours and your reasoning first.

1. **Spending.** Does your no-spending rule still hold? Options: Low only, a capped amount like $50 for G1 and G2 only, or Likely. What would you choose, and what result would change your mind?
2. **What does "30 minutes" have to mean for you?** Version a is a demo now, b is 4-7 days of the Mac, and c needs a GPU. Which one are you actually asking for, and why?
3. **PACE:** what's your actual account status, and which rate and credits apply? This single answer moves the Low and Likely totals the most.
4. **Before T1:** do you want the AC power setting changed before tonight's queue starts? Only you can do it, because it needs `sudo`, and it may make the Mac hotter and louder.

## Check your understanding

Before T2, try these two. They'll tell you whether the cost logic has landed.

1. Doubling life length doubles the transcript's tokens per decision. What happens to its *total* cost, and why?
2. If T9 passes and T10 fails, what have you learned about the bet, in one sentence?

---

## Status when this was written

- `pmset` still showed `powermode 1` at 00:26 [M].
- The clip job was still running, so `wmloop_demo_real`, the 4-bit conversion, `evals_noise_t07`, `mind_qwen` and `homeostatic_pilot` were all still waiting. `out/ops/gpu_ledger.jsonl` had 5 "queued" rows and no finished jobs. **No real demo numbers exist yet, under `runs/wmloop_demo_real` or elsewhere.** When it finishes, replace the [E] per-tick figures in section 2.2a with its `run_end` line.
- Test suite status from `out/ops/MORNING.md` at 00:15: the agent loop suite had 4 errors, and the demo uses that branch.

## Source list

All checked 2026-11-05. Several pages are third-party summaries, and search-derived details are marked. Prices change; verify before paying.

| ID | Source | What it gave |
|---|---|---|
| S1 | https://www.runpod.io/pricing ("Updated November 4, 2026") | H100 PCIe $2.89 / community $1.99, H100 SXM $3.99 / $2.69, A100 $1.79, L40S $1.09, H200 $5.29, storage $0.07 per GB-month |
| S2 | https://lambda.com/pricing (takes effect Nov 16, 2026) | H100 PCIe $3.29 |
| S3 | https://deploybase.ai/articles/vast-ai-gpu-cloud-pricing-complete-guide-vs-hr-for-every-gpu (as of March 22, 2026). https://vast.ai/pricing shows no static prices | Vast H100 $2.00-$3.50 |
| S4 | https://pace.gatech.edu/2024/10/31/new-gpus-for-phoenix-v100s-being-replaced/ | H200 and H100 $0.673 per GPU-hour, L40S under embers |
| S5 | https://cse.gatech.edu/cse-computing-resources | Free tier: 1 TB, 10,000 CPU-hours-equivalent a month, 4-month rollover, faculty |
| S6 | https://sites.gatech.edu/ewanparktest/phoenix-cluster/ and https://pace.gatech.edu/2021/04/23/faq-after-the-end-of-the-grace-period-on-the-phoenix-cluster/ (via search summary) | "$68" a month, "68" credits. Student-run page and a 2021 FAQ, so weak |
| S7 | https://pace.gatech.edu/participation/ | Who can access Phoenix, EVPR-PACESHIP |
| S8 | https://cnaps.ai/blog/cosmos3-nano | Table attributed to NVIDIA: 480p, 189 frames, 59.83 s; 720p, 207.78 s. Second-hand: NVIDIA's `inference_benchmarks.md` returned 404 for me |
| S8b | https://www.baseten.co/blog/nvidia-cosmos-3-robots-finally-take-over/ (via search summary) | About 4 min for 720p on H100, hosted |
| S9 | https://nvidia.github.io/cosmos-framework/get_started/quickstart/ | 32 GB weights, 150 GiB disk |
| S10 | https://www.spheron.network/tools/gpu-recommender/nvidia/Cosmos3-Nano/ | Estimated 34 GB peak |
| S11 | https://openrouter.ai/compare/qwen/qwen3-vl-8b-instruct | Qwen3-VL-8B $0.25 / $0.75, 262,144 context |
| S12 | https://pricepertoken.com/pricing-page/model/qwen-qwen3-vl-8b-instruct and https://anotherwrapper.com/llm-pricing/qwen3-vl-8b-instruct (via search summary) | $0.117 / $0.455; $0.08 / $0.50. Conflicts with S11, so S11's higher price is used |
| S13 | https://thinkingmachines.ai/tinker/pricing/ (as of Oct 19, 2026) | Qwen3-8B train $0.44. No Qwen3-VL listed |
| S14 | https://platform.claude.com/docs/en/about-claude/pricing | Opus 5.5 batch $2 / $10, Sonnet 5.5 batch $1 / $5, per million tokens |
| S15 | https://www.notebookcheck.net/M4-Max-14-cores-vs-M4-Pro-14-cores_18558_18019.247596.0.html (via search summary) | M4 Max chip about 70-80 W under load |
| S16 | https://www.electricchoice.com/electricity-prices-by-state/georgia/atlanta/ (via search summary) | 14.8 cents per kWh, June 2026 |
| S17 | https://ask.atlascloud.ai/seedance-2-cost-per-second (via search summary) | Seedance about $0.112 per video second. Different model |
| S18 | https://arxiv.org/abs/2502.17424 | Emergent misalignment: narrow fine-tuning shifted broad behavior |
| S19 | https://arxiv.org/abs/2402.17753 | LoCoMo: retrieval and long context help, but stay well short of humans |
| S20 | https://arxiv.org/abs/2304.03442 | Generative Agents: full record, reflections and retrieval |
| S21 | https://forums.unrealengine.com/t/rendering-in-headless-mode-possible/475619 and https://carla.readthedocs.io/en/0.9.8/adv_rendering_options/ (via search summary, partly old) | Unreal offscreen Vulkan problems |
