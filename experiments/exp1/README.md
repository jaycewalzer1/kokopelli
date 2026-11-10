# Experiment 1: homeostatic RL in the wellness-center scenario

**What it asks:** does a Qwen agent that lives through mornings of the wellness-center scenario (`kokopelli/life/scenario.py`),
rewarded only by homeostatic drive reduction and updated with a LoRA each night while it sleeps, learn from its own experience?
In particular, does experience alone push it toward rare-bad and away from rare-good options (Hertwig)? The agent sees words,
never numbers.

The write-ups are in `docs/`, not in this folder:

- [`docs/exp1_phase1.md`](../../docs/exp1_phase1.md): phase 1, the balance check and the tabular reference (CPU only).
- [`docs/exp1_report.md`](../../docs/exp1_report.md): the first long run (`exp1_lived_s0_lr2e-5`, Qwen3-VL-8B-Instruct bf16, LoRA
  r16), its results and the decisions left for the owner.
- [`docs/homeostatic_rl_map.md`](../../docs/homeostatic_rl_map.md): a map of the code; section 6 is this experiment as built.

| File | What it holds |
|---|---|
| `world.py`, `homeostasis.py`, `observe.py` | One life: the scenario wired to the reward math, and what the agent is shown |
| `policy.py`, `learn.py` | Qwen and tabular policies, and the learning rule (running baseline, sleep update) |
| `run.py` | One life lived by a learning policy; the model run |
| `balance.py`, `tabular_check.py`, `baselines.py` | CPU checks: option balance, the tabular reference, random and always-safe baselines |
| `smoke.py`, `guardrails.py`, `diagnose*.py` | Before a long run, after a life (did training hurt general ability), and diagnostics on a finished run |
| `panel.py` | What the panel's `/exp1` page reads |

## Rerun

```sh
python -m experiments.exp1.balance            # CPU, no model
python -m experiments.exp1.tabular_check      # CPU, no model
python -m experiments.exp1.run out/exp1/runs/exp1_lived_s0 --arm lived --seed 0 --policy qwen --lr 2e-5 --guardrails mmlu ifeval
```

The Qwen run goes through the GPU queue (`AGENTS.md`). It resumes with the same command.

## Results

Runs are in `out/exp1/runs/<run>/` (not tracked) and on the panel's `/exp1` page. Tests: `tests/test_exp1.py`,
`tests/test_exp1_learn.py`, through `make test-all`.
