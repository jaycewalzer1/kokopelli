## P1-A Repo hygiene, AGENTS.md index, skills (2026-11-09)

### What changed and why

- **`.gitignore`:** added `.claude/*` with a `!.claude/skills/` exception (worktrees and session state stay out of git, shared skills are tracked), `/mac_server/Packaged` and `/mac_server/Packaged_*` (packaged Unreal builds; `git ls-files mac_server | grep -c Packaged` = 0, so nothing tracked is hidden), and the four worktree symlinks `/.venv`, `/out`, `/models`, `/simworld/.venv` without a trailing slash, so they match a symlink as well as a directory. Until now the worktree symlinks were hidden only by the shared `.git/info/exclude`.
- **`AGENTS.md`:** 151 lines of per-area dated status cut to a rules section plus a one-line-per-area table (owns, prefix, port). Dated status, run results and queue snapshots are gone; they live in each area's notes, `out/ops/MORNING.md` and the ledger. Standing rules kept in short form: queue usage (`ops/gpu.py run` with `--about`, `--output`, `--gb`, priorities), stop via `gpu.py stop` and never `pkill` model processes, keeper ownership, the 8 GB outside-job rule, `ram_share.py hold`/`claim`, the four-control 8-bit Variant A default, closed-loop quality tests and fake-WM labelling, ports (9001 packaged, 9003/9004 editors, 8765 panel), the mouse-turns-camera-0 warning, the `city/world.json` re-planning caveat (restore `4cc0311` first; the planner lives in `city/ue/plan_varied/`), and the benchmarks-only-through-the-queue rule. Added: one task per session, own worktree, pointer to skills. The `.claude/worktrees/ops/ops/gpu.py` command became `ops/gpu.py`. Every file the rules name was checked with `test -e` (all present; `mac_server/Packaged*` exist in the main checkout, untracked).
- **Skills** (`.claude/skills/<name>/SKILL.md`, frontmatter `name` + `description`), each stating its exact model and weights:
  - `sim-capture`: `filter_test/scripts/capture.py` + `city/wm/controls.py`; no model. Warns that capture rewrites `out/filter_test/test_clip/`.
  - `paint-clip`: the `wmmc_a4_full_8bit` command from the ledger (`world_transfer_multi.py`, `models/Cosmos3-Nano-Sim-Transfer`, `--quantize 8`, four controls at 0.25, 832x480), wrapped in `ops/gpu.py run` + `ram_share.py hold`; `run_a.sh` variants noted as bf16.
  - `closed-loop-run`: `city/agents/run_wm_lunch.sh` + `lunch_wm.py` flags (Qwen3-VL-8B-Instruct-4bit, Cosmos3-Nano-Sim-Transfer via `world_stream_multi.py`). It notes that `lunch_wm.py` defaults to 448x256 and no quantization, so the owner's default needs `--quantize 8 --size 832x480` passed explicitly.
- **`docs/NEXT_proposed.md`:** trimmed replacement for gitignored `out/ops/NEXT.md` (Nov 5 interim note, 50 lines of stale run results). It keeps only the still-open owner decisions and caveats, with pointers. The orchestrator copies it into main.

### Acceptance (numbers)

| Check | Before | After |
|---|---|---|
| `wc -l AGENTS.md` | 151 | 44 (target 60 or fewer) |
| `grep -c worktrees/ops AGENTS.md` | 2 | 0 |
| `git check-ignore .claude/worktrees mac_server/Packaged_bodies` | no match | both match |
| `git check-ignore .claude/skills/x` | no match | no match (exit 1) |
| `git status --short` shows `.venv`, `out`, `models`, `simworld/.venv` | no (via info/exclude only) | no (via `.gitignore` lines 9-12, `git check-ignore -v`) |
| SKILL.md files | 0 | 3 |

### Suites

SUITES_PLACEHOLDER

No `.py`, `.sh` or Makefile was touched, so no behavior can change.

### Left undone / for the orchestrator

- Copy `docs/NEXT_proposed.md` over main's `out/ops/NEXT.md` (gitignored, so not done here).
- Other tracked files still name `.claude/worktrees/ops/ops/gpu.py` (P2-A's list); the skills avoid them.
- `docs/FABLE_LOG.md` not created, per the orchestrator's change.
