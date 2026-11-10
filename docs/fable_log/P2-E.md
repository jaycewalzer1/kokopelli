# P2-E: out/ layout, retention rule, backup proposal

2026-11-09. Documents plus one read-only tool. Nothing in `out/` was deleted, moved or written.

## What changed
- `docs/OUT_LAYOUT.md`: the standard layout `out/<area>/<run-id>/` with a `run.json` sidecar, a table of the 32 top-level entries with their sizes, the retention rule (cited or golden = keep, smoke = 7 d, intermediate = 30 d, unclassified = keep), where the rule stands today, and the owner's decisions.
- `docs/OUT_BACKUP.md`: options A (SSD plus `rsync --link-dest`, recommended), B (rclone to B2), and C (both), with the exclude list, cost and time estimates, and decisions. Cost and time figures are my estimates, not measured or price-checked.
- `ops/out_report.py`: one `du -k -d 2` call plus a stat walk. It prints size, file count, age, newest file and sidecar/README per area and per run, then the deletion candidates. Standard library only. It has no write, unlink or rename calls.

## Acceptance (numbers)
- Runtime 0.86-0.89 s on main's out/ (limit 60 s). It covers 39,492 files and 286 runs.
- Totals: report 47,156,404 KB = `du -sk out/` 47,156,404 KB. The sum of the top-level entries is also 47,156,404 KB.
- `find out -newer marker` after the run: 0 entries on the final run. One earlier run showed 2 (`out/ram/claims/memguard_p1m_test_life_architecture_22107.json` and its dir). That file belongs to another worker's memguard claim, not this tool.
- `ruff check ops/out_report.py`: clean.

## Decisions made alone (conservative)
- The smoke pattern is narrow (`smoke|scratch|tmp|debug|dry.?run|memtest`). My first version also matched `test` and `probe`, which would have put `filter_test/test_clip_garden`/`_still` (1.6 G input clips) and `homeostatic/probe-*` sweeps on a 7-day clock.
- A run's own Markdown doesn't count as a citation. `city_agents/*/transcript.md` was citing its own run.
- "Cited" means a match in any tracked text file, not only Markdown, plus Markdown inside `out/`. A false keep only costs disk.
- No unit test was added: `ops/tests/` isn't in this package's Owns list. Worth adding later.
- Today the rule finds 1 candidate (an empty dir, 0 KB). About 7 G of intermediate runs cross 30 days around 2026-12-06.

## Owner must decide
- `bodies/demo/failed_tries` (3.9 G) and `bodies/scratch_project` (4.0 G): the rule keeps both because they're cited or sit inside a cited run.
- Whether the report should treat `bodies/demo/runs/<id>` as runs (20.2 G sits under one cited entry).
- Backup option A, B or C, buying the hardware or creating the account, and the schedule. `ops/out_backup_exclude.txt` and the script are a follow-up.
- Who writes `run.json`. This belongs with the phase 3 run-manifest item.
