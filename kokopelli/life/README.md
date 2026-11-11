# kokopelli.life: the life generator and the dev panel

Two things live here: the life generator (a life from age 2 to 30 as a tree of time windows) and the dev panel that shows it,
plus the panel's other views (homeostatic training, system architecture, pipeline, GPU queue, agent view, model runs, moodboard).
All UI follows [`DESIGN.md`](../../DESIGN.md), with its tokens and components in `static/design.css` and the panel's layout in
`static/panel.css`.

## Life generator

A life from age 2 to 30, as a tree of time windows that opens lazily. Nothing is edited once written: a closing is a new row, and current state is a replay of the event log. This is the node infrastructure with placeholder content, and it makes no LLM calls.

```sh
make demo    # a separate database with a life already generated, replayed in 30 seconds
make panel   # your own runs, in out/life.db
make test    # the life tests, in about 15 seconds
```

The browser opens by itself. If the port is taken, the panel uses the next free one. Edit a file under `kokopelli/life/static/` and the page reloads; edit the Python or `kokopelli/settings.py` and the server restarts, which ends any run in progress. Your place is kept in the page's link.

The panel has a sidebar for switching between this, homeostatic training and the system architecture. For a life, it shows one selection two ways. The tree is the map: the years sweep 270 degrees, hovering previews a line, and clicking a node opens its branch. Under it are the time rulers, where each row is the row above zoomed into its highlighted cell, so reading down goes from a whole life to its seconds. Shaded cells with a colored underline are written, the color being their life stage; the outlined cell is the agent, and empty cells aren't written yet. Tree labels that would overlap are hidden, most important kept first, and come back as you zoom in. While nothing is chosen, the tree's view follows the agent during a run; Back to agent returns to that after you choose a node or move the view. The slider rebuilds the run at any earlier event. A run stops at the limit in `LIFE_BUDGET`; press Run to continue it.

### Running on the local model

```bash
make trial              # a short run: one year, then a few days of its first month
make overnight          # 8 hours, or HOURS=6 make overnight
make watch              # in a second terminal: follow the latest run, read-only
make report             # rewrite the latest run's report
```

Each run gets a folder in `out/overnight/`, with `latest` pointing to the newest. It holds `life.db`, every prompt and answer in `calls.jsonl`, `run.log`, and `report.md`. An overnight run skims one life down to months so that every stage gets written, forks to write one month per stage down to days, then skims a second life to compare. A crash restarts it from the last finished write; `python -m kokopelli.life.overnight --resume <folder>` does the same by hand. Keep the Mac plugged in with the lid open.

The agent is still the random one, so only the world is written by the model. The model is told about the past the way a person holds it (`memory.py`): where you are in your life, recent stretches with detail fading to gist as they get older, and older moments only if they mattered and you were old enough to keep them. Prompts are in `prompts.py`.

Tune the stages, the salience-to-depth table, the budget and the default seed in `kokopelli/settings.py`.

| File | What it holds |
|---|---|
| `seed.py`, `windows.py`, `engine.py`, `store.py` | The input to a life, its time windows, the loop that writes them, SQLite storage with no update or delete |
| `generator.py`, `llm_generator.py`, `prompts.py`, `memory.py` | What writes each stretch: the placeholder and the local-model generator, its prompts, and what it remembers |
| `agent.py`, `resolver.py`, `scoring.py` | Who lives the life, how an action becomes consequences, and the only code that reads the hidden target |
| `overnight.py`, `report.py` | Unattended runs and their morning report |
| `scenario.py`, `scenario_night.py`, `staged.py` | The wellness center scenario and its night run through the generator; jobs staged for the Start button on the queue page |
| `city.py` | Checks on the city plan in `data/city/world.json` |
| `panel.py`, `static/` | The dev panel server (`make panel`, or `koko-panel`) and its pages |
| `architecture.py`, `pipeline.py`, `gpu_queue.py`, `city_live.py`, `world_runs.py`, `moodboard.py`, `sensations.py`, `watch.py` | What each panel view reads |

## System architecture view

The panel's System architecture view is one chart of the whole system, marked built, partly built, not working yet or planned. Its statuses and links are plain data at the top of `architecture.py`, with the code or plan section behind each; `tests/test_life_architecture.py` checks that every named file exists. Lines move only while a process found in `ps` is using that path, and each new row in a run's log sends one token along it. A process that writes nothing for 15 minutes stops moving.

## Pipeline and GPU queue views

The panel's Pipeline view shows the whole system in one place, read from the files each part leaves behind: the GPU queue and its ledger, test results and how old they are, agent loop and feel-then-decide runs, training and benchmarks. Its top line says whether the real 30-minute run is possible yet, from gates read off those files, and a gate it can't read is unknown. Whether a run is mock or real comes from its config, never its name. It only reads, and it finds these folders through `PIPELINE_PATHS` in `kokopelli/settings.py`. A ticket whose process is gone is stale, and a process that has written nothing for 15 minutes isn't called moving.

The GPU queue view is that queue on its own page: who has the GPU, how long they've run, their time limit and last output, who goes next, and how past turns ended. It also reads the GPU's load and allocated memory from `ioreg`, which cover every program on the Mac. It flags a model job started outside the queue, and says when it's a kind `kokopelli/ops/gpu.py` can't see and so won't wait for. Each waiting job can be given a new priority, which goes through `gpu.py move`, or cancelled, which stops its `gpu.py` before it has a turn and notes `cancelled` in the ledger. A job that has its turn can't be stopped from the page. These two changes only work from the panel's own page, so another site open in the browser can't send them. The code is in `gpu_queue.py`.

Tests: `tests/test_life_*.py`, run with `make test-all`.
