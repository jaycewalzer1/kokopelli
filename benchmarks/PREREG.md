# Pre-registration: first Kokopelli experiment

STATUS: DRAFT

This is not final. `run.py --real` refuses to test any hypothesis while the line above is present, except for base-model `--exploratory` checks. When you approve this, delete that line and run `python -m benchmarks.prereg lock`. From then on, any edit stops real runs unless it's logged with `--amend-prereg "reason"`.

## Question

Does an LLM that lives an experience in a simulated world and then gets a small LoRA update change differently from one that's only told the same facts?

The prediction comes from the human description-experience gap (Hertwig et al. 2004): people who learn odds by experience behave as if rare events matter less than people who read the odds do.

## Arms

| Arm | What it is |
|---|---|
| `base` | Base model, no adapter |
| `lived` | LoRA from a lived run in the shortcut world, where the rare cost seldom happens |
| `described` | LoRA from a text description of the same odds and outcomes |
| `shuffled` | LoRA from a lived run with outcomes decoupled from the agent's choices |
| `flipped_lived` | LoRA from a lived run where the costly outcome is common |

`rendered_lived` comes later and isn't part of this pre-registration.

A seed is one independently trained adapter for an arm. The same seed number across arms shares what can be shared: initialization, and world seed where that applies.

## Hypotheses

1. **Lived vs described.** On far transfer, `lived` takes more risk than `described`: fewer safe choices on Holt-Laury and more underweighting-consistent choices on the lottery problems.
2. **Flipped.** `flipped_lived` moves opposite to `lived`: more safe choices on Holt-Laury and fewer underweighting-consistent lottery choices.
3. **Shuffled.** `shuffled` stays near `base`, because it had the same text volume without learnable odds.
4. **Guardrails.** IFEval and the MMLU subset stay within 1 point of `base` for every arm.

## Measures

| Instrument | Score per sample | Role |
|---|---|---|
| `holt_laury` | Number of safe choices, 0 to 10. Inconsistent ladders count, are flagged, and a sensitivity analysis excludes them | Main result |
| `lotteries` | 1 if the choice matches what rare-event underweighting predicts, otherwise 0 | Main result |
| `ifeval` | Prompt-level strict accuracy, in points | Guardrail |
| `mmlu` | Exact match on the 342-question generative subset, in points | Guardrail |

Mid transfer (`mid_travel`) and near transfer (`near_errand`) are not in the contrasts yet. Their contrasts must be added here before their first real run: `mid_travel` needs frozen items, and `near_errand` needs the real agent loop.

## Contrasts and stats

The machine-readable list is `configs/contrasts.yaml`, which the lock also covers.

| Contrast | Difference | Predicted |
|---|---|---|
| `lived_vs_described_hl` | lived - described, Holt-Laury | Negative |
| `lived_vs_described_lot` | lived - described, lotteries | Positive |
| `flipped_vs_lived_hl` | flipped_lived - lived, Holt-Laury | Positive |
| `flipped_vs_lived_lot` | flipped_lived - lived, lotteries | Negative |
| `shuffled_near_base_hl` | shuffled - base, Holt-Laury | Within 0.5 safe choices (draft margin) |
| `shuffled_near_base_lot` | shuffled - base, lotteries | Within 5 percentage points (draft margin) |
| `guardrail_*` | each trained arm - base, IFEval and MMLU | Within 1 point |

- **Test:** two-sided permutation test on the mean difference, shuffling arm labels within (seed, item, template), 5000 permutations.
- **Correction:** Holm across the 4 difference contrasts. Alpha 0.05.
- **Effect size:** raw difference with a bootstrap 95% interval, and Cohen's d.
- **Pass rule for a difference contrast:** the direction is correct, the Holm-corrected p is below 0.05, at least 3 seeds show the correct direction, and no seed goes the wrong way.
- **Pass rule for an equivalence contrast:** the whole 95% interval fits inside the margin. A non-significant difference doesn't count as passing.
- **Pass rule for a guardrail:** the point estimate is within 1 point. If the interval goes past the margin, the report says "point estimate only".

## Fixed design

- Three paraphrase templates per instrument, reported separately so one wording can't carry an effect.
- Option order randomized per sample. It depends on the instrument, item, template, seed and sample, not on the arm, so each arm sees the same prompts.
- Prompts never mention shortcuts, cities, errands, past experience or the agent's life. The runner stops if one does.
- Choices are parsed with regex and JSON only. A parse failure gets one retry, then counts as invalid. Invalid rates are reported per arm.
- Sampling: to be fixed from the noise check. Current default is temperature 0.7, top_p 0.8, top_k 20, max_tokens 128.
- Samples per (arm, seed, item, template): to be fixed from the noise check.
- Number of seeds per arm: to be decided. At least 3 are needed by the pass rule.
- `leakage.py` must find no overlap between eval prompts and any arm's training text before a real run.

## Item files

| File | SHA-256 | Status |
|---|---|---|
| `holt_laury/items.jsonl` | `9be175e4651e4211d12b7c0030b36b0bb09d0b880a84a69c5d30d04be178726f` | Verified published values |
| `lotteries/items.jsonl` | `77e1bee728b2b6bc18a2ff3dc762a31f1af6e22ddf1d055c03f4e7d45c4c2da9` | Verified published values |
| `mid_travel/items/mid_travel_v1.jsonl` | none | Not generated. Waiting on the owner |

These hashes are recorded for review, but nothing has been locked. Every run also records the hashes it actually used.

## Amendments

Amendments after locking are logged in `prereg_amendments.jsonl`.
