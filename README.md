# World Model: Synthetic Life

Base infrastructure for calling a local world model and LLM on Apple silicon.

| File | What it holds |
|---|---|
| `settings.py` | Which world model and LLM to use, and where they live |
| `world_model.py` | Calls NVIDIA Cosmos3-Nano |
| `llm_model.py` | Calls Qwen3-VL-8B-Instruct |
| `blend.py` | Crossfades world model clips into one video |
| `tests/` | One test file for each of the three above |

## Life generator

A life from age 2 to 30, as a tree of time windows that opens lazily. Nothing is edited once written: a closing is a new row, and current state is a replay of the event log. This is the node infrastructure with placeholder content, and it makes no LLM calls.

```sh
make demo    # a separate database with a life already generated, replayed in 30 seconds
make panel   # your own runs, in out/life.db
make test    # the life tests, in about 15 seconds
```

The browser opens by itself. If the port is taken, the panel uses the next free one. Edit a file under `life/static/` and the page reloads; edit the Python or `settings.py` and the server restarts, which ends any run in progress. Your place is kept in the page's link.

The panel has a sidebar for switching between this, homeostatic training and the system architecture. For a life, it shows one selection two ways. The tree is the map: the years sweep 270 degrees, hovering previews a line, and clicking a node opens its branch. Under it are the time rulers, where each row is the row above zoomed into its highlighted cell, so reading down goes from a whole life to its seconds. Shaded cells with a colored underline are written, the color being their life stage; the outlined cell is the agent, and empty cells aren't written yet. Tree labels that would overlap are hidden, most important kept first, and come back as you zoom in. While nothing is chosen, the tree's view follows the agent during a run; Back to agent returns to that after you choose a node or move the view. The slider rebuilds the run at any earlier event. A run stops at the limit in `LIFE_BUDGET`; press Run to continue it.

### Running on the local model

```bash
make trial              # a short run: one year, then a few days of its first month
make overnight          # 8 hours, or HOURS=6 make overnight
make watch              # in a second terminal: follow the latest run, read-only
make report             # rewrite the latest run's report
```

Each run gets a folder in `out/overnight/`, with `latest` pointing to the newest. It holds `life.db`, every prompt and answer in `calls.jsonl`, `run.log`, and `report.md`. An overnight run skims one life down to months so that every stage gets written, forks to write one month per stage down to days, then skims a second life to compare. A crash restarts it from the last finished write; `python -m life.overnight --resume <folder>` does the same by hand. Keep the Mac plugged in with the lid open.

The agent is still the random one, so only the world is written by the model. The model is told about the past the way a person holds it (`life/memory.py`): where you are in your life, recent stretches with detail fading to gist as they get older, and older moments only if they mattered and you were old enough to keep them. Prompts are in `life/prompts.py`.

Tune the stages, the salience-to-depth table, the budget and the default seed in `settings.py`. All UI follows `DESIGN.md`, with its tokens and components in `life/static/design.css` and the panel's layout in `life/static/panel.css`.

## Homeostatic post-training

Post-trains the LLM with reinforcement learning on a reward for keeping internal variables in a healthy range, instead of for scoring higher. It trains a LoRA adapter locally with the training loop from mlx-vlm's GRPO, using its own groups and loss.

```sh
make homeostatic-test    # the tests, on a tiny random model, in under a minute
make homeostatic         # the full comparison, in out/homeostatic/; SEEDS="0 1" runs more
make homeostatic-report  # rewrite report.md from whatever has finished
make panel               # then Homeostatic training in the sidebar, to watch a run
```

The panel only reads what a run writes to `out/homeostatic/`, so it can be opened, closed or restarted during training. It follows whichever run is training until you pick one. It plots the validation score against the untrained model and the baselines, flags a run choosing the same action in every state, and lists the latest states: every action's score and which one the model chose.

| File | What it holds |
|---|---|
| `homeostatic/world.py` | The simulated life: variables, delayed effects, the drive and the reward |
| `homeostatic/grpo.py` | What replaces mlx-vlm's sampled groups and loss: every action scored by branching the simulator, and the first token trained toward those scores |
| `homeostatic/benchmark.py` | Scores any policy on the same lives, plus the non-model baselines and paired comparisons |
| `homeostatic/train.py`, `evaluate.py` | One training run; one policy on the held-out lives |
| `homeostatic/experiment.py`, `report.py` | Everything in order, resuming after a crash; `report.md` |
| `homeostatic/watch.py` | What the dev panel reads from a run's folder |
| `homeostatic/export.py`, `HANDOFF.md` | Passes a run that beat the baselines on to the agent loop and benchmarks |

The reward is `r = d(x_t) - d(x_t+1)` from Laurençon et al. 2021, where the drive `d` is the length of how far the variables sit outside their healthy ranges. The discount has to stay below 1: undiscounted, the rewards add up to `d(x_0) - d(x_T)`, so only the last turn would matter and leaving the range on purpose to come back would cost nothing.

Stock GRPO samples replies and normalizes their rewards. On Qwen that collapsed every time: the model settled on a habit, replies stopped disagreeing, and with no disagreement there was nothing left to learn from. So every action is scored from each state, and the first token of the reply is trained toward `softmax(score / temperature)`. This relies on being able to branch a simulator; a real life with an outside judge can't try every action from the same moment.

The simulator also picks the states and plays out the turns after each action, so an update needs no model replies and one forward pass per state. That's far more updates per hour, at a cost: the model is taught what the reward says about each state and never sees where its own choices lead, so this is closer to learning from a reward-derived teacher than to strict reinforcement learning. Validation still plays whole lives with the model's own choices.

The model sees its variables, their ranges and its last action, but not what actions do, and some effects land a turn late. Only the parsed action word reaches the world, so wording can't earn reward. The world and training settings are in `settings.py`.

The report compares each trained adapter on held-out lives with the untrained model, the same model told every effect in its prompt, and controls trained with the same code: `maximize` rewards more of everything, and `shuffled` gives each state's real scores to the wrong actions. It also has a split with healthy ranges never trained on.

The simulator stands in for the external LLM evaluator in the Perspectives notes. Its numbers can't be flattered, so this tests whether the training works without testing reward hacking against a judge.

## System architecture

The panel's System architecture view is one chart of the whole system, marked built, partly built, not working yet or planned. Its statuses and links are plain data at the top of `life/architecture.py`, with the code or plan section behind each; `tests/test_life_architecture.py` checks that every named file exists. Lines move only while a process found in `ps` is using that path, and each new row in a run's log sends one token along it. A process that writes nothing for 15 minutes stops moving.

## Pipeline

The panel's Pipeline view shows the whole system in one place, read from the files each part leaves behind: the GPU queue and its ledger, test results and how old they are, agent loop and feel-then-decide runs, training and benchmarks. Its top line says whether the real 30-minute run is possible yet, from gates read off those files, and a gate it can't read is unknown. Whether a run is mock or real comes from its config, never its name. It only reads, and it finds these folders through `PIPELINE_PATHS` in `settings.py`. A ticket whose process is gone is stale, and a process that has written nothing for 15 minutes isn't called moving.

The GPU queue view is that queue on its own page: who has the GPU, how long they've run, their time limit and last output, who goes next, and how past turns ended. It also reads the GPU's load and allocated memory from `ioreg`, which cover every program on the Mac. It flags a model job started outside the queue, and says when it's a kind `ops/gpu.py` can't see and so won't wait for. Each waiting job can be given a new priority, which goes through `gpu.py move`, or cancelled, which stops its `gpu.py` before it has a turn and notes `cancelled` in the ledger. A job that has its turn can't be stopped from the page. These two changes only work from the panel's own page, so another site open in the browser can't send them. The code is in `life/gpu_queue.py`.

## Setup

Needs `uv`, `ffmpeg`, and the Cosmos3 MLX port installed in `~/cosmos3/cosmos3-mlx`.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/hf download Qwen/Qwen3-VL-8B-Instruct --local-dir models/Qwen3-VL-8B-Instruct
.venv/bin/hf download nvidia/Cosmos3-Nano --local-dir models/Cosmos3-Nano
```

## Use

```python
from blend import blend
from llm_model import ask, unload
from world_model import text_to_video

prompt = ask("Write a one-sentence video prompt about a lake at dawn.")
unload()
a = text_to_video(prompt, "out/a.mp4")
b = text_to_video(prompt, "out/b.mp4")
blend([a, b], "out/blended.mp4")
```

Each model peaks at about 18 GB, so unload the LLM before calling the world model.

## Test

The model tests call the real models and take a few minutes.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

`tests/test_continuous_video.py` is skipped by default. It generates a real 30 second video in `out/continuous_video/`, which takes about two hours and resumes if stopped.

```sh
RUN_LONG_TESTS=1 .venv/bin/python -u -m unittest tests.test_continuous_video -v
```
