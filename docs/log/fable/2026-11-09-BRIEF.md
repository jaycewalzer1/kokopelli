# Fable brief: optimize and refine Kokopelli

Written 2026-11-09. The owner runs one phase at a time and checks `/usage` between phases.

## Goal

Make the existing system cheaper for Claude Code to work on, faster, harder to break, and more lifelike. **Don't add features.** New pages, experiments, game mechanics and product surfaces are out of scope. Tooling that protects the existing system (linters, tests, checks, checkpoints) is in scope. The one allowed integration is connecting the existing life generator to the city agents (phase 5).

## Rules

- This brief replaces the teaching rules in `CLAUDE.md` for this work. Keep a decision log in `docs/FABLE_LOG.md` instead: what changed, why, and the before-and-after numbers.
- Every speed, stability or realism change needs a before-and-after measurement. Report failures as failures.
- GPU work goes through the queue with `--about` and `--output`, named for the exact model and weights. Sim-driven world-model runs use the four-control Sim-Transfer setup (0.25 each) with 8-bit weights unless the owner says otherwise. If a run lowers size or precision, say so in its report and sidecar.
- Quality tests are real closed-loop runs. Never present the fake world model as the real one.
- Work on branches, in small reviewable commits. Commit only on those branches and don't push. Don't delete outputs, weights or builds; list deletion candidates for the owner.
- Moving the mouse during a packaged-server run turns camera 0, until phase 3 fixes it. Ask the owner to step away first.
- Stop and ask before any change to what the agents are, what the project claims, or the four-control default.
- Stop at the end of each phase and report results, spend and what's next.

## Phase 1: Claude Code efficiency (target 5-10% of a week)

- Add `.claude` and `mac_server/Packaged_*` to `.gitignore`.
- Cut `AGENTS.md` to a short, current index and remove stale status. Check `out/ops/NEXT.md` the same way.
- Split the largest hand-written files along natural seams (`city/agents/lunch_wm.py`, `city/ue/build_city.py`, `runtime/adapters/simworld.py`) with behavior unchanged.
- Make test and status commands terse by default: failures only, and an explicit "idle" from `gpu.py status`.
- Save repeated workflows as skills: sim capture, closed-loop run, paint a clip.
- Keep sessions short with one task each. Cache reads were 96% of recent token use.

## Phase 2: Organization and linters (target 10-20%)

- **First:** switch every reference from `.claude/worktrees/ops/ops/gpu.py` to `ops/gpu.py`. Only then merge or retire worktrees.
- Move the loose root modules into a package, one small change at a time, checking imports after each.
- Give `out/` a standard layout and a written retention rule.
- Configure `ruff`, `pyright` on core code, `shellcheck`, a linter for `life/static`, and `pre-commit`. Exclude `simworld/` and `wm_multicontrol/upstream/`.
- Replace the two-line `requirements.txt` with `uv` and a lockfile. Document each virtual environment and why it exists.
- Add one test command that runs every suite.
- Remove code that isn't used and Markdown files that are no longer relevant (the owner asked for this on 2026-11-09). Git-tracked files only, on a branch. Delete code only with evidence that nothing reaches it: no imports, no references from shell scripts, the Makefile, queue jobs, `out/` run scripts or the panel. Delete a Markdown file only if it's superseded or describes something that no longer exists; move any fact still worth keeping first. Keep reports that hold experimental results, and leave `simworld/` and `wm_multicontrol/upstream/` alone. List everything removed, with the reason, in `docs/FABLE_LOG.md`.

## Phase 3: Stability (target 15-30%)

- Find why 15 of 93 finished GPU jobs failed (21 of 91 hours) and fix the common causes. Add a one-frame dry run.
- Stop the mouse from moving camera 0.
- Settle the mosaic cause. The time-position test stayed clean (65 frames, moving camera), a still camera shatters, and the Mara and Iris films break just after they stop walking. Test stillness against elapsed time.
- Add an automatic check that fails a run on mosaic or drift. An older drift metric read about 0.99 on unrecognizable video.
- Add closed-loop checkpoints, a golden-run regression check, and full run manifests (commit, uncommitted changes, weight hash, seed, prompt).
- Propose a backup plan for `out/` (45 GB, ignored by git). The disk is 84% full.

## Phase 4: Speed (target 15-35%)

- Profile a paint step. A closed-loop step took about 475 s, while the per-latent figure explains about 310 s.
- Explain why two near-identical 150-frame paints took 935 s and 1,782 s. Check power mode, heat and what else was running.
- Test 4-bit weights, batching both agents in one pass, and passing frames in memory instead of `.npy` files.
- Have the agent model decide only when something changes.
- Reduce heat and swap: 4 of 22 measured jobs reached 100°C or more, and 7 used over 8 GB of swap.
- Painting is the bottleneck (the sim took 103 s of a 1,141 s step), so leave Unreal for later.

## Phase 5: Realism (hard cap, about 60-100% of a week; set with the owner)

Looks:
- Closed-loop agents at 832x480 with a prompt per view and per person, for the new city (`WM_PROMPT` in `city/agents/lunch_wm.py` is generic and stale).
- Ease head turns, keep head sway, and replace the grey tank tops.
- Keep each person's appearance the same in both agents' views.

Behavior:
- Fix repeated lines, stuck loops, the feeling system that doesn't follow events, and how agents use memory. Tune daily routines.
- Connect the existing life generator to the city agents, so they act from a generated past. This is the riskiest item, so build it behind a switch and compare with written personas.

Measure with `benchmarks/`, the golden clip, and blind viewing by the owner.
