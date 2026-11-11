# Notes from the lead to every lane (2026-11-10, after Gate 0)

Read after `AGENTS.md`, `CLAUDE.md`, `DESIGN.md` and `docs/SENSATIONS_OVERNIGHT.md` (sections 0, 3, 4 and your lane). These are
things the plan didn't know. Where this file and the plan disagree, this file is newer; where either disagrees with
`AGENTS.md`, `AGENTS.md` wins and you write the conflict in your log.

## Where things are

- The port is done: `sens/integration` at the merge commit, pushed. What moved and what was added: `2026-11-11-lead.md` beside
  this file. Read its "Found while porting".
- The lead's worktree is `~/Desktop/koko-sens-integration`. Don't edit it. Make yours from the main checkout:

  ```sh
  git -C /Users/jaycewalzer/Desktop/kokopelli worktree add ../koko-sens-<lane> -b sens/<lane> sens/integration
  cd /Users/jaycewalzer/Desktop/koko-sens-<lane>
  for l in .venv simworld/.venv out models; do [ -e "$l" ] || ln -s "/Users/jaycewalzer/Desktop/kokopelli/$l" "$l"; done
  ```

  `out/` and `models/` are then the main checkout's own folders (ignored by git). Anything you write there is real and shared.
- Scratch space, outside every repo: `/private/tmp/claude-501/-Users-jaycewalzer/c31b62a3-ef47-454e-8a88-760515393c27/scratchpad/lane-<lane>/`.

## Traps

- **Run Python with `-m` from your worktree's root, never by script path.** The shared `.venv` has the library installed
  editable from the main checkout, which puts the *main checkout's* root on `sys.path`. `.venv/bin/python -m kokopelli.x.y` and
  `tools/fable/test_all.sh` are fine because the current folder comes first. `.venv/bin/python path/to/script.py` imports
  main's `kokopelli`, `experiments` and `tests`, silently, and main has none of the sensations code. If you must run a script
  file, set `PYTHONPATH=$PWD`.
- **Don't install anything into the shared `.venv`** (or `simworld/.venv`, or the Cosmos venv). Other areas' jobs run from
  them tonight. If you need a package they don't have, make your own venv with `uv` under your scratch folder, say so in your
  log, and write the proposed `pyproject.toml` change under "Decisions for Jayce". `docs/ENVIRONMENTS.md` explains the three
  environments.
- **Tests:** `tools/fable/test_all.sh tests/body experiments/sensation/tests` (folders, not single files: a single file that
  imports MLX makes the py310 run report a false error). The whole tree is `make test-all`: about 10 minutes, peak 1.5 GB.
  Baseline on `sens/integration`: main 759 passed, 10 skipped, 2 xfailed; experiments 269 passed, 1 skipped; py310 197 passed.
  A global hook refuses any command that contains the word for the test runner (the one that starts with "py"), even inside a
  commit message, unless it goes through the guard. So don't write that word in commit messages.
- **Linters:** wrap each in the guard, for example
  `python3 kokopelli/ops/memguard.py run --name sens_<lane>_lint --gb 3 -- uvx ruff@0.11.4 check .` (ruff must be 0.11.4),
  `uvx pyright kokopelli`, `.venv/bin/lint-imports`. Shell: `uvx --from shellcheck-py shellcheck -x <file>`. JS:
  `npx -y @biomejs/biome@2.6.6 lint --no-errors-on-unmatched <file>`.
- **Import wall** (`pyproject.toml`): the library never imports `experiments`, `tools` or `tests`. Layers low to high:
  `wm`, `body`, `mind`, `loop`, `life`, `agents`. `kokopelli.body` may import only `kokopelli.settings` from the library.
- **Prompts are frozen tonight.** `tests/body/test_egg_prompts_pinned.py` (27 sweep prompts, from the branch's original code)
  and `test_the_loops_prompts_are_pinned` in `tests/agents/test_egg_wm.py` (12 dry closed-loop prompts) must pass unchanged.
  Never regenerate a golden file to make them pass.

## The GPU and memory, right now

- **The Mac is on battery** and the owner is asleep. Model jobs run slower and the night may end early. Queue the smallest job
  that answers your question, most valuable first.
- Two sweeps are in the queue: `evals_hunger_egg_base` (p40, full-precision Qwen, about 17 GB, roughly 70 minutes) and
  `evals_hunger_egg_base4bit` (p41). While the first runs, about 12 GB is available.
- `python3 kokopelli/ops/gpu.py run ...` **blocks until the job has finished**, which can be hours. Start it as a background
  command and carry on with CPU work. `--cwd` is your worktree, `--about` at most 400 characters, at least one `--output`, and
  `--gb` with the job's peak. Read `gpu.py status` first. Never start a model outside the queue, however small.
- Every model output needs a JSON sidecar naming the model, the weights folder or repo and revision, size and precision.
- Before downloading a model or dataset: read its licence, record it (name, URL, date read, terms that matter) in your
  `SOURCE.md` or log, then download. Unclear or non-commercial: skip it, log it, take the next option.

## Working rules that are easy to miss

- Nobody is awake to answer. For a design decision: take the reversible option, and write the options and tradeoffs under
  "Decisions for Jayce" in your log. Give one `file:line` worth reading per module you wrote under "Read this", each with a
  question.
- Your log is `docs/log/sensations/2026-11-11-<lane>.md`: what you did, what failed, what you skipped and why, exact commands.
  A dry run or a fake is called that every time it's mentioned.
- Only your lane's files (section 4 of the plan). For anything else, write the patch in that area's `HANDOFF.md` and don't
  apply it.
- Delete the owner's files by moving them to the Trash, never `rm`. Your own scratch files are yours.
- Commits small, each passing tests, each message ending with `Co-Authored-By: Claude <noreply@anthropic.com>`. Push only
  `sens/<lane>`. No merge to `main`, no force-push, no history rewriting.
- Stop, don't push through, when the same gate fails twice for the same reason, a licence is unclear, or the work needs
  another area's file.
- Don't push your branch until the end: a rebase after a push would need a force-push, which is off the table. When your
  gate passes: `git fetch origin && git rebase origin/sens/integration`, rerun the gate, push once, and end with a report
  to the lead: gate result as you measured it, what's done, what failed or was skipped, anything left running in the queue
  (job names), and your branch's last commit.
