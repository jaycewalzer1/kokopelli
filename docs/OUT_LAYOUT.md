# out/: layout and retention rule

`out/` holds every run's output. It's ignored by git, so this file and `ops/out_report.py` are the only record of how it's organised. On 2026-11-09 it held 45.0 GB in 39,492 files. The disk was 82% full (734 of 926 GiB used).

See what's there and what the rule would remove:

    .venv/bin/python ops/out_report.py              # areas, runs over 50 MB, deletion candidates (under a second)
    .venv/bin/python ops/out_report.py --min-mb 0   # every run

The report only reads. It deletes nothing. Deleting is always the owner's call, made by hand from the candidate list.

## Standard layout for new runs

    out/<area>/<run-id>/
        run.json        sidecar: what made this run (see below)
        README.md       optional: one paragraph on what the run showed
        ...             outputs; intermediate frames in frames/ or *.npy

- `<area>` is one top-level directory per area in `AGENTS.md`, named like the area's prefix without the underscore: `city_wm`, `bodies`, `wm_multicontrol`, and so on. Don't add a new top-level directory for a single run.
- `<run-id>` is `YYYYMMDD-HHMMSS` or `YYYYMMDD-HHMMSS-<short-name>`, so runs sort by time. Put `smoke` in the name of smoke runs and `golden` in the name of golden runs. The retention rule reads those words (see below).
- Logs go in the run directory, not loose in the area. The queue's own logs stay in `out/ops/job_logs/`.
- `run.json` holds at least: `{"commit", "dirty", "command", "started", "finished", "model", "weights", "seed", "prompt", "cited_by": []}`. `model` and `weights` already have to be named for every world-model output (AGENTS.md). `cited_by` lists the reports that use this run, so the retention rule can see them even when a report only names a file inside the run.
- Older runs don't follow this layout and won't be moved. Only 4 of the 286 run entries have any sidecar (`run.json`, `manifest.json` or `meta.json`) today.

## What each top-level directory is (2026-11-09)

| Dir | Size | What it holds | Area |
|---|---|---|---|
| `bodies/` | 31.7 G | MetaHuman body work. `demo/` (24.4 G: `runs/` 20.2 G, `failed_tries/` 3.9 G), `scratch_project/` 4.0 G, `clothing/` 2.5 G, `renders/` 0.7 G | Realistic bodies |
| `filter_test/` | 5.2 G | Sim-to-real filter test: three 1.5 to 1.6 G test clips with controls, SD1.5 depth runs | Sim-to-real filter test |
| `city_wm/` | 2.0 G | World-model paints of the city: `demo_flyover` (1.7 G), `varied_aerial`, `bridge` (controls for the bridge clip), `plaza` | Control videos, Sim-Transfer |
| `city_kinds/` | 1.6 G | Building-kind previews, one dir per kind, plus `planner/` (0.5 G) | Varied city |
| `city_realism/` | 1.5 G | Realism pilot `before` captures (1.0 G of `.npy`) | Unreal realism pilot |
| `homeostatic/` | 1.0 G | Homeostatic training pilots and learning-rate probes, ~167 M each | Homeostatic training |
| `city_renders/` | 0.5 G | Iterations of city renders (`vibe`, `final`, `iter4`, `live`, ...) | City |
| `demo_30s/` | 0.4 G | The 30-second demo video, its frames and build script | Demo |
| `exp1/` | 0.4 G | Experiment 1 runs | Experiment 1 |
| `city_agents/` | 0.3 G | Agent-view runs, one timestamped dir each (read by `/city-live`) | Agent view, lunch |
| `world_stream/` | 0.1 G | Streaming paint tests (`still_test`, `rope_test`, `smoke`) | Sim-Transfer |
| `mind/` | 0.1 G | Feel-then-decide checks on real frames | Mind |
| `wm_multicontrol/` | 0.1 G | Variant A/B multi-control runs and blind tests | Multi-control transfer |
| `edge_filter/`, `scenario/`, `sim_transfer/`, `continuous_video/`, `world_data_20261104/`, `test_outputs/` | < 20 M each | Smaller experiments | Various |
| `ops/` | 4 M | Queue state: ledger, job logs, `MORNING.md`, `NEXT.md`, test history. **Live, never prune.** | Queue, ops |
| `ram/` | < 1 M | `ram_share.py` and `memguard.py` claims. **Live, never touch.** | `ram_share` |
| `overnight/`, `staged/`, `simworld_mac_server/` | < 1 M | Overnight life runs (`latest` is a symlink), staged-job markers, server grant | Life, scenario |
| `life.db`, `demo.db*`, `panel.log` | 15 M | Panel databases and log. **Live, never prune.** | Dev panel |
| `panel-radial-backup/`, `panel-rulers-only/`, `moodboard/` | < 1 M | Old panel design copies | Dev panel |

## Retention rule

Each run (`out/<area>/<entry>`) gets one class. The first match wins:

| Class | How it's recognised | Keep for |
|---|---|---|
| keep: cited | `out/<area>/<entry>` appears in a git-tracked text file (Markdown, Python, shell, JSON; `simworld/` and `wm_multicontrol/upstream/` are skipped) or in a Markdown file elsewhere in `out/`. A run's own notes don't count. | forever |
| keep: golden | `golden` in the name | forever |
| smoke | `smoke`, `scratch`, `tmp`, `debug`, `dry run` or `memtest` in the name | 7 days |
| intermediate | holds `.npy` files or a `frames*` / `*_frames` directory | 30 days |
| keep: unclassified | everything else | until the owner sorts it |

Age is days since the newest file in the run changed, so a run someone is still adding to never ages out. A run past its limit becomes a **deletion candidate**. The report lists candidates. It doesn't delete them.

Never candidates, whatever the rule says: `out/ops/`, `out/ram/`, `*.db` and their `-shm`/`-wal` files, `panel.log`, and anything a job in `gpu.py status` is writing.

Why these choices:

- **Report-cited means keep.** A result a report depends on is the evidence for a claim. Deleting it makes the claim impossible to check. The scan is broad (any tracked text file) because a false keep only costs disk, while a false delete loses evidence.
- **"test" and "probe" don't mark smoke runs.** `filter_test/test_clip_garden` is a 1.6 G input clip and `homeostatic/probe-*` are learning-rate sweeps. Both are real work. The smoke words are kept narrow, and anything doubtful falls through to `intermediate` (30 days) or `unclassified` (keep).
- **Intermediate frames get 30 days.** `.npy` controls and frame dirs can be rebuilt from the sim clip and `city/wm/controls.py`, and they're the bulk of most runs (`city_wm/demo_flyover` 1.0 of 1.7 G). 30 days covers a phase of work plus its review.
- **Unclassified means keep.** Most of the 45 G is old-style runs with no sidecar. Guessing would delete things nobody checked.

### Where the rule stands today (2026-11-09)

- Candidates: 1 entry, 0 KB (`wm_multicontrol/memtest`, an empty dir). Almost everything in `out/` is under 7 days old, so the rule frees nothing yet.
- Due to become candidates (all intermediate, about 3 days old, so they cross 30 days around 2026-12-06 unless cited first): `filter_test/test_clip_garden` 1.6 G, `filter_test/test_clip_still` 1.6 G, `city_wm/demo_flyover` 1.7 G, `city_realism/before` 1.5 G, `city_wm/varied_aerial` 0.2 G, `world_stream/rope_test` 0.1 G, and 12 `city_agents/2026*` runs totalling 0.3 G. That's about 7 G.
- **The rule can't reach most of the bulk.** `bodies/demo` (24.4 G) is cited as a whole by `.claude/skills/closed-loop-run/SKILL.md`, so it counts as one kept run. Inside it are `runs/` (20.2 G) and `failed_tries/` (3.9 G). `bodies/scratch_project` (4.0 G) is cited by `city/bodies/LOG.md`, and `bodies/clothing` (2.5 G) is unclassified. These need an owner decision (see below). They're the space that matters.

## Owner decisions

1. **`bodies/demo/failed_tries` (3.9 G) and `bodies/scratch_project` (4.0 G).** Both names say "not the result". Delete them, or back them up and then delete? The rule keeps both because they're cited or sit inside a cited run.
2. **Treat `bodies/demo/runs/<id>` as runs.** The rule works two levels down. One extra level for `bodies/demo/runs` would let old demo runs age out on their own. This changes `ops/out_report.py`, a small follow-up.
3. **Old panel copies** (`panel-radial-backup`, `panel-rulers-only`, `moodboard`, under 1 M together). Keep or drop? They cost nothing in disk but add clutter.
4. **Who writes `run.json`?** The layout only helps if the queue (`ops/gpu.py`) or each runner writes the sidecar. A phase 3 item (full run manifests) already covers this. That item should write the file described above.
