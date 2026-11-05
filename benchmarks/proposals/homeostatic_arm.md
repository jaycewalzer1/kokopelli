# Proposal: a `homeostatic` arm

**Not adopted.** Nothing reads this file. It isn't in `PREREG.md`, `configs/contrasts.yaml` or `configs/arms/`, and real runs refuse the arm until you decide. No training run has passed the export gate yet either.

## What it would be

`homeostatic.export` writes the settings to `out/homeostatic/handoff.json` as `benchmark_arm`. On this Mac, `llm_model` needs the `fused/` folder, so `adapter` becomes `weights`:

```yaml
name: homeostatic
model: Qwen/Qwen3-VL-8B-Instruct
weights: out/homeostatic/runs/homeostatic-{seed}/fused   # On vLLM, use the converted adapter instead.
api_model: homeostatic_seed{seed}
training_text:
  - out/adapters/homeostatic/seed{seed}/training_text/*
```

## Questions to settle first

1. **What's the prediction?** Lived, described and flipped each have a direction, from the rare-event hypothesis. Homeostatic training is about keeping four numbers in range, and I don't see a reason it should move risk preference one way or the other. Without a direction the only honest contrast is two-sided, or an equivalence test against `base`.
2. **Same Holm family?** Adding contrasts to the family makes the main hypotheses harder to pass. A separate family keeps them independent, but says less about the whole experiment. Treating it as exploratory, outside the pass rule, avoids that cost.
3. **Guardrails only?** A cheaper first step is to pre-register just the guardrail contrasts, asking "did this training damage the model?". That needs no directional claim.
4. **Seeds.** The pass rule needs at least 3. The first pilot is one run.

## What I'd check in the training text

The leakage check would read `training_text/states.jsonl`, which holds JSON states with numbers rather than prose, so overlap with lottery prompts is unlikely. It's still worth running. The check is lexical, so it can't say whether training taught anything related to risk.
