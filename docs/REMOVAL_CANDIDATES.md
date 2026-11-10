# Removal candidates (P2-F1, 2026-11-09)

Evidence for the owner before any code is deleted (P2-F2). Nothing in this table has been deleted. Counts come from `python3 scripts/fable/reach.py` (code) and `python3 scripts/fable/reach.py --md` (Markdown), which search 1,219 files: every tracked text file (`.py .sh .md .json .js .html .toml .yaml .txt` and the Makefile, under 2 MB), `out/ops/gpu_ledger.jsonl`, and every `out/**/*.sh`, `out/**/*.json`, `out/**/run*.py` under 2 MB. A file's own text and its own `test_<stem>*.py` don't count. `simworld/`, `wm_multicontrol/upstream/` and `mac_server/` are not scanned as targets.

"Hits" = number of other files that name the target (repo path, dotted module path, or basename as a whole word). Basename matching over-counts, so a non-zero number means "maybe used"; zero is the strong signal.

## Markdown: the known list from the plan (all kept)

| File | Path hits / name hits | Decision | Evidence |
|---|---|---|---|
| `runtime/HANDOFF.md` | 5 / 26 | keep | `AGENTS.md` names it as the place asks go for the agent-loop area; also linked from `filter_test/scripts/capture.py`, `mind/OPEN_DECISIONS.md`. |
| `wm_multicontrol/HANDOFF.md` | 2 / 26 | keep | Its two proposals for `world_transfer.py` are still open: `core/world_transfer.py:189` `text_cache` still takes one id list, and l.202/266/278 still hardcode `32, 128` and `4096`. Linked from `wm_multicontrol/BRIEF.md:25`. |
| `benchmarks/HANDOFF.md` | 2 / 26 | keep | Holds experimental results (phase 5 base-model noise check, before/after section) and the open owner decisions. |
| `homeostatic/HANDOFF.md` | 5 / 26 | keep | Read by `homeostatic/export.py` and `mind/check.py` (by path); states the export gate no run has passed yet. |
| `city/bodies/PLAN.md` | 12 / 17 | keep | Named by `city/bodies/apply_core_data.sh`, `client.py`, `migrate_bodies.sh` and others; the bodies area is live. |
| `city/bodies/HANDOFF.md` (extra) | 0 / 26 | keep | 0 path hits, but its asks are still open: `city/agents/lunch_wm.py` and `live_wm.py` don't call `dress`/`log_tiers` (only `city/agents/live.py:271-294,510-537` does). |
| `mind/OPEN_DECISIONS.md` | 8 / 8 | keep | Listed in `AGENTS.md` and `life/architecture.py:96` (node files, checked by the architecture test); open decisions. |
| `docs/exp1_phase1.md` | 4 / 4 | keep | Holds results (balance and tabular tables); cited by `tests/test_exp1.py:129`, `docs/exp1_report.md:10`, `docs/homeostatic_rl_map.md:219`. |
| `docs/exp1_report.md` | 0 / 1 | keep | Results. |

## Markdown: other files looked at (all kept)

| File | Path hits / name hits | Why kept |
|---|---|---|
| `docs/NEXT_proposed.md` | 2 / 2 | P1-A's proposed replacement for `out/ops/NEXT.md`; waiting on the owner. |
| `benchmarks/proposals/homeostatic_arm.md` | 0 / 1 | An unadopted proposal the owner still has to decide on (says so in its first line). |
| `benchmarks/noticing/PREREG.md` | 0 / 16 | Pre-registration; never delete. |
| `wm_multicontrol/BRIEF.md` | 4 / 6 | The task is done (results in `REPORT.md`), but `core/world_multicontrol_base.py` and `core/world_transfer_multi.py` cite it; P2-F1 can't edit `core/`. Candidate once those comments point at `REPORT.md`/`NOTES.md`. |
| `mac_server/docs/LOOK_PATCH.md` | 1 (`city/realism/BRIEF.md`) | Patch is applied with changes: `SWEnvironment.cpp` has its `PostProcessVolume.h` include (l.11) and `SetSkyLuminanceFactor` (l.84), but the sun is `FRotator(-40, -45)` (l.56), not the patch's `-18`. Can't call it superseded. |
| `city/realism/BRIEF.md` | 1 / 6 | Live area brief per `AGENTS.md`. Names `docs/LOOK_PATCH.md`/`docs/PACKAGING.md` (they live under `mac_server/docs/`) and a `city/realism/REPORT.md` that doesn't exist yet. |
| `ops/plans/COST_AND_LIFE_PLAN.md` | 1 | Read by `ops/status.py:425`. |
| `runtime/THIRTY_MIN.md`, `mind/MEASUREMENTS.md`, `wm_multicontrol/REPORT.md`, `wm_multicontrol/NOTES.md`, `wm_multicontrol/RESEARCH.md` | 2-3 each | Results or research notes. |

No Markdown file met the bar (superseded, or describing something that no longer exists, with every surviving fact already elsewhere). So none was deleted this round.

## Code with zero hits (P2-F2 candidates; owner approves first)

| File | Hits | Notes |
|---|---|---|
| `benchmarks/report_screenshots.py` | 0 | Not named anywhere but itself; may be run by hand. |
| `benchmarks/tests/fake_openai_server.py` | 0 | Not imported by any test; check before deleting whether a test starts it by a computed path. |
| `city/bodies/metahuman/fade_test.py` | 0 | Unreal editor script (`import unreal`); run by hand in the editor. |
| `city/bodies/metahuman/inspect_materials.py` | 0 | Unreal editor script, run by hand. |
| `city/bodies/standins/make_groom_usda.py` | 0 | One-off asset generator. |
| `city/bodies/standins/make_helmet.py` | 0 | One-off asset generator. |
| `city/realism/replay_bridge.py` | 0 | Realism area tool. |
| `city/source_commons.py` | 0 | Asset sourcing script. |
| `city/source_tiktok.py` | 0 | Asset sourcing script. |
| `city/ue/plan_varied/kitmap.py` | 0 | Varied-city tool; reads `world_varied.json`. |
| `city/wm/blur_variants.py` | 0 | Control-video experiment. |
| `city/wm/plaza_clip.py` | 0 | Clip tool. |
| `filter_test/scripts/preview_videos.py` | 0 | Filter-test tool. |

Zero hits means no import, shell script, Makefile, queue job or `out/` run script names it. Most of these are hand-run tools, so "unreached" isn't "useless"; the owner should mark which are finished one-offs.

## Code from the plan's known list (keep)

| Item | Hits | Decision |
|---|---|---|
| Root shims (`settings.py` ... `ram_share.py`, 12 files) | 14-121 | Keep. P2-B/P2-C: `ram_share.py`, `world_transfer*.py`, `world_stream*.py`, `world_filter.py` are run by path (`core/world_transfer.py:48`, `core/world_transfer_multi.py:64,80`, `filter_test/scripts/run_cosmos.py:36`, 8+ shell scripts, the paint-clip skill). `runtime/preflight.py:109` checks `blend.py` exists. |
| `core/world_multicontrol_base.py` (Variant B) | 14 | Keep: reference implementation, owner-kept (`AGENTS.md`). |
| `filter_test/scripts/` | 2-150 per file except `preview_videos.py` (0) | Keep, apart from `preview_videos.py` above. `run_sd.py` appears in the ledger. |
| `scripts/pace/` | `wmloop_one_tick.py` 3, `wmloop_wait_server.py` 2 | Keep: used by `runtime/tests/test_simworld_gate.py` and the PACE shell scripts. |
| `city/world_varied.json` | 9 files | Keep: byte-identical to `city/world.json` (`cmp` exit 0), but `city/ue/plan_varied/{plan,check,kitmap,run_build}.py` and `city/ue/kinds/locked.py` read it by name. |
| `cloud/` | — | Keep: `ops/gpu.py` imports it. |

## Stale entries in `life/architecture.py` (reported by P2-A, not changed here)

These `branch_files` point into worktrees that no longer hold the code, and their `why` text says "not merged", though `runtime/` and `benchmarks/` are in this checkout now. Fixing them is the architecture owner's job; P2-F1 only owns entries for Markdown it deletes (none).

| Line | Node text | Stale reference |
|---|---|---|
| 74-75 | agent loop: "Only on the feat/wm-agent-loop worktree, not merged" | `.claude/worktrees/wm-agent-loop/runtime/{loop,run}.py`, `adapters/life_db.py`, `mocks/world_model.py` |
| 82-83 | world model: "adapters ... on the feat/wm-agent-loop worktree only" | `.../wm-agent-loop/runtime/adapters/cosmos{,_server}.py` |
| 86-87 | agent: "A Qwen agent exists on the feat/wm-agent-loop worktree only" | `.../wm-agent-loop/runtime/adapters/qwen.py`, `prompt_builder.py`, `mocks/agent.py` |
| 90-92 | SimWorld: "adapter on feat/wm-simworld and feat/wm-agent-loop worktrees" | `.../wm-agent-loop/runtime/adapters/simworld{,_bridge}.py`, `runtime/SIMWORLD.md`, `scripts/pace/wmloop_gate.sbatch` |
| 95 | mind: "needs runtime/ from the agent loop worktree" | (text only) |
| 175 | benchmarks: old worktree `agent-a2d4c0a770bb9b339` | `.../benchmarks/run.py`, `PREREG.md`, `holt_laury/items.jsonl` |

## Decision, 2026-11-10 (owner delegated the call)

**No code deleted.** All 13 zero-hit files are hand-run tools between 24 and 92 lines, last changed between 5 and 8 November, in areas that are still live:

- Moodboard sourcing (`city/source_commons.py`, `city/source_tiktok.py`): the moodboard is in use and these are how images get onto it.
- Bodies checks and asset generators (`metahuman/fade_test.py`, `inspect_materials.py`, `standins/make_groom_usda.py`, `make_helmet.py`): the only record of how the stand-in assets were made and how the body fade is checked.
- Capture and control tools (`city/realism/replay_bridge.py`, `city/wm/plaza_clip.py`, `city/wm/blur_variants.py`, `filter_test/scripts/preview_videos.py`, `city/ue/plan_varied/kitmap.py`): each is run by hand from its docstring, which is why no file names them.
- Benchmark helpers (`benchmarks/report_screenshots.py`, `benchmarks/tests/fake_openai_server.py`): the first runs DESIGN.md's section 8 check, the second tests the eval harness without a model.

"Nothing imports it" is not evidence that nothing uses it when the user is a person at a terminal. Together they are about 730 lines, so removing them would save nothing measurable. Revisit one only when its area is retired.

**Removed instead** (fully merged into main, clean, referenced by nothing): worktrees `.claude/worktrees/ops` and `.claude/worktrees/integrate`, and branches `feat/ops`, `integrate/all-sessions`, `wip/main-overnight`, `add-simworld`, `worktree-agent-a2d4c0a770bb9b339`, `worktree-agent-aa5f839d86d587545`. Kept: the `agent-a2d4…` and `agent-aa5f…` worktrees, because `core/settings.py`, `life/architecture.py` and `ops/status.py` still point at them, and the three worktrees with unmerged commits (`commons`, `exp1`, `wm-agent-loop`).
