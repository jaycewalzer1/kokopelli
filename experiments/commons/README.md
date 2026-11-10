# Commons: lived upbringings and a shared lake

**What it asks:** do agents with different lived upbringings govern a shared resource (a lake with logistic regrowth, 60
seasons, 7 Qwen-played founders and a scripted defector from season 31) better than clones, or than agents merely described as
having those upbringings? No central planner. A pilot: few seeds, one local model (`Qwen3-VL-8B-Instruct-4bit`), reward R3.

- [`PREREG.md`](PREREG.md): the design, frozen before any full run, and the pass rules.
- [`DECISIONS.md`](DECISIONS.md): judgment calls and deviations, dated.
- [`results/REPORT.md`](results/REPORT.md): the verdict. 2 of 10 targeted seeds completed; the lived-experience claim is not
  supported, and all 6 games collapsed before the newcomer arrived (a floor effect).
- [`results/reward_audit.md`](results/reward_audit.md): the reward checked with scripted policies, no LLM.
- [`results/lint_report.md`](results/lint_report.md): the leakage lint of the prompts.

## Rerun

The game is in `sim.py`, `rewards.py` and `config.yaml`; `run.py` plays it, `audit.py` checks the reward, `analyze.py` writes
the report. The tests are pytest-style and run in the SimWorld venv, in the `commons` suite of `make test-all`. Model runs go
through the GPU queue. `overnight.sh` is the queue wrapper the pilot used, but it still names the old `.claude/worktrees/commons`
worktree and the old `ops/gpu.py` path, as does the "Rerun" block that `analyze.py` writes into the report; both need their paths
updated before the next run.

## Results

`results/` holds the tracked summaries (`REPORT.md`, `metrics.json`, `spend.json`, `plots/`, the audit and lint reports). The
raw game logs (`R1/`, `R3/`, `R3_before_speech_fix/`, `smoke/`, `upbringings/`, `overnight.log`) are untracked and exist only
in the commons worktree, under `.claude/worktrees/commons/runs/commons/`.
