# Benchmarks

**What it asks:** does post-training move the model on established human-psych decision instruments (Holt-Laury, lottery
problems), while standard ML benchmarks (the guardrails) stay put? Nothing is optimized for any of them.

- [`HANDOFF.md`](HANDOFF.md) is the map: what each folder holds, how to add an instrument, the phase 5 base-model noise check and
  its results, the before-and-after comparison, and the decisions still open for the owner.
- [`PREREG.md`](PREREG.md) is the pre-registration of the first experiment. It is a **draft**: `run.py --real` refuses to test a
  hypothesis until it is locked (`python -m experiments.benchmarks.prereg lock`).
- [`noticing/PREREG.md`](noticing/PREREG.md) is the draft pre-registration of the noticing test. Nothing has run.
- [`proposals/homeostatic_arm.md`](proposals/homeostatic_arm.md) proposes a `homeostatic` arm. Not adopted; nothing reads it.

## Rerun

A mock run needs no model: `python -m experiments.benchmarks.run --arms ... --instruments ...` (default `--backend mock`).
A real run loads Qwen and must go through the GPU queue, since the queue doesn't recognize this module as a model job
(command in `HANDOFF.md`, "Real models on this Mac"; queue priority 40, turns of 30 minutes or less with `--minutes 30`).
`noise_check_turns.sh` reruns the noise check that way. On PACE: `tools/pace/evals/`.

## Results

A run writes `experiments/benchmarks/results/<run_id>/` (`results.jsonl`, `run_record.json`, `summary.parquet`), ignored by
git. The noise-check results (`noise_t07/` and its siblings) were written in the `feat/evals` worktree
(`.claude/worktrees/agent-a2d4c0a770bb9b339/benchmarks/results/`) and are not in the main checkout; the panel's Pipeline view
reads them there through `PIPELINE_PATHS["evals"]`, and also reads `out/benchmarks/`.
Tests: the `benchmarks` suite of `make test-all`.
