# World Model: Synthetic Life

A clock for one complete synthetic life, readable at any level from the life story down to a single minute.

```
life story > developmental segments > statements and plans > year > season > month > week > day > hour > minute
```

The first life is Nell Varga, 1941-2023, of the fictional harbor town of Port Averill on Lake Huron. Read it in [docs/WORLD_STORY.md](docs/WORLD_STORY.md). The storage design and its open questions are in [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Try it

Needs Python 3.12 or newer and nothing else.

```sh
python3 -m lifeclock validate                        # check the canon for contradictions
python3 -m lifeclock at 1996-07-23T13:18             # read the whole stack at one minute
python3 -m lifeclock run --db out/life.db            # tick every minute of the life
python3 -m lifeclock verify --db out/life.db         # check every invariant and replay the life
python3 -m lifeclock story --db out/life.db --out story.md
python3 -m unittest discover -s tests
```

## Layout

| Path | What it holds |
|---|---|
| `canon/world.json` | The authored world: people, segments, statements, plans, events, schedules |
| `lifeclock/clock.py` | Time as an integer, and the calendar levels as intervals on it |
| `lifeclock/world.py` | Top-down expansion to any minute; canon validation |
| `lifeclock/engine.py` | Ticks through the life with checkpoints, pacing, and audits |
| `lifeclock/store.py` | SQLite schema and digests |
| `lifeclock/verify.py` | Invariant checks on a finished life |

## The one-hour test

[`hour-test.yml`](.github/workflows/hour-test.yml) stretches the entire life across one real hour, about 12,000 simulated minutes per second:

1. Runs the life unpaced as a reference.
2. Starts the paced run and hard-kills it with `SIGKILL` at 25 minutes.
3. Resumes it from its last checkpoint and catches up to the original schedule.
4. Requires the run to take 3600s within 60s, and every invariant to hold.
5. Requires the paced and reference lives to be byte-identical across all digests.

Ticking the clock takes about 1% of that hour. The paced run spends the rest checking randomly chosen lived minutes against an independent random-access lookup, and any disagreement fails the test.

Start it from the Actions tab or with `gh workflow run hour-test.yml`. It only runs on demand, and each run uses about 65 Actions minutes.

## Canon rules

- Edit the story in `canon/world.json`, then run `validate`.
- A database refuses to resume on a different canon.
- Append new activities to the end of the list. Their codes are list positions.
