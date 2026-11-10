#!/usr/bin/env bash
# Entry-point smoke check: every script and module with a __main__ block, run the
# way it is launched, in the interpreter it belongs to. One ok/FAIL line each,
# exit 1 on any failure. Catches broken launch paths that the unit tests miss.
#
#   tools/smoke_entrypoints.sh                  # all three interpreters in turn
#   tools/smoke_entrypoints.sh .venv/bin/python # one interpreter
#   SMOKE_ALL=1 tools/smoke_entrypoints.sh X    # ignore tags, try every entry in X
#   VERBOSE=1 ...                               # print the output of failures
#
# Nothing here loads Qwen or Cosmos or touches the GPU queue: `--help` exits in
# argparse before any work, and the import checks only import (model loading
# lives inside functions). Heavy enough to run through the memory guard:
#   python3 kokopelli/ops/memguard.py run --name reorg-smoke --gb 2 -- tools/smoke_entrypoints.sh
#
# Adding an entry: one line in the ENTRIES table below.
#   tags    which interpreters it belongs to, comma separated:
#             main = .venv/bin/python (3.12)
#             sw   = simworld/.venv/bin/python (3.10)
#             cos  = ~/cosmos3/cosmos3-mlx/.venv/bin/python (3.12, MLX + Cosmos)
#             all  = every interpreter, including a system python3 (stdlib-only tools)
#   kind    help   run with --help, expect exit 0
#           import import only (scripts that ignore --help or would start work)
#           bash   `bash -n` syntax check of a shell launcher (tag it main; runs once)
#           cmd    run a console command with --help (phase 1 koko-* commands);
#                  looked up next to the interpreter, in its bin/ folder
#   skip    in the tags column: `skip  -  target  # reason`; never run, listed with its reason
#   target  a dotted module (run with -m, from the repo root), a path (run by
#           path, as it is launched), or a command name for `cmd`
#   # ...   anything after a # is a note (required for skip)

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

MAIN_PY="$ROOT/.venv/bin/python"
SW_PY="$ROOT/simworld/.venv/bin/python"
COS_PY="$HOME/cosmos3/cosmos3-mlx/.venv/bin/python"
COS_PATH="$HOME/cosmos3/cosmos3-mlx"   # the Cosmos runner's own package, as the paint-clip skill sets it
TIMEOUT="${SMOKE_TIMEOUT:-90}"

ENTRIES='
# --- core ---
all     help    kokopelli.ops.ram_share
main    help    kokopelli.wm.video_check
main,cos help   kokopelli.wm.world_stream                  # prints its docstring unless --worker
main,cos help   kokopelli.wm.world_stream_multi
cos     help    kokopelli.wm.world_transfer
cos     help    kokopelli.wm.world_transfer_multi
cos     help    kokopelli.wm.world_filter
cos     help    kokopelli.wm.world_multicontrol_base
# --- ops (system python3 runs gpu.py and memguard.py: keep them stdlib-only) ---
all     help    kokopelli/ops/gpu.py
all     help    kokopelli/ops/memguard.py
main    help    kokopelli/ops/out_report.py
main    help    kokopelli/ops/status.py
main    help    kokopelli/ops/summarize.py
# --- life ---
main    help    kokopelli.life.overnight
main    help    kokopelli.life.panel
main    help    kokopelli.life.report
main    help    kokopelli.life.scenario_night
# --- runtime ---
main,sw help    kokopelli.loop.check_video
main,sw help    kokopelli.loop.compare
main,sw help    kokopelli.loop.plan
main,sw help    kokopelli.loop.preflight
main,sw help    kokopelli.loop.probe_decisions
main,sw help    kokopelli.loop.run
main,sw help    kokopelli.loop.viewer
# --- mind launchers (in loop: they wire the mind into the loop) ---
main    help    kokopelli.loop.mind_change_check
main    help    kokopelli.loop.mind_check
main    help    kokopelli.loop.run_mind
# --- homeostatic ---
main    help    experiments.homeostatic.evaluate
main    help    experiments.homeostatic.experiment
main    help    experiments.homeostatic.export
main    import  experiments.homeostatic.report                 # no argparse: running it writes the report
main    help    experiments.homeostatic.train
# --- exp1 ---
main    help    experiments.exp1.balance
main    help    experiments.exp1.diagnose
main    help    experiments.exp1.run
main    import  experiments.exp1.smoke                         # takes a positional run folder, no --help; running it loads Qwen
main    help    experiments.exp1.tabular_check
# --- benchmarks (launch with -m: experiments/benchmarks/core.py shadows core by path) ---
main    help    experiments.benchmarks.before_after
main    help    experiments.benchmarks.freeze
main    help    experiments.benchmarks.leakage
main    help    experiments.benchmarks.mid_travel.generate
main    help    experiments.benchmarks.noise_check
main    help    experiments.benchmarks.prereg
main    help    experiments.benchmarks.report
main    help    experiments.benchmarks.report_screenshots
main    help    experiments.benchmarks.run
# --- city ---
main    help    kokopelli.agents.live
main    help    kokopelli.agents.live_wm
main    help    tools.fable.lunch_bench
main    help    kokopelli.agents.lunch_life
main    help    kokopelli.agents.lunch_wm
main    import  kokopelli/agents/navmap.py              # no argparse: running it builds the nav map
main    help    tools/bodies/demo_cut.py
main    import  tools.bodies.demo_lunch          # hand-parses argv and forwards the rest to lunch_wm; running it starts a demo
main    help    tools.bodies.demo_promptcheck
main    help    tools/bodies/metahuman/looks.py
sw      help    tools/bodies/wave1_renders.py
sw      help    tools.bodies.wave2_renders
main    help    tools/bodies/write_parts.py
sw      help    tools/realism/replay_bridge.py
main    help    tools/moodboard/source_arena.py
main    help    tools/moodboard/source_commons.py
main    help    tools/moodboard/source_tiktok.py
sw      help    tools/city_build/build_city.py
sw      import  tools.city_build.kinds.locked               # runs argv as a command under a lock; no --help
sw      help    tools.city_build.kinds.preview
sw      help    tools.city_build.kinds.watchdog
sw      help    tools.city_build.plan_varied.check
sw      import  tools.city_build.plan_varied.kitmap      # hand-parses argv; no --help
sw      help    tools.city_build.plan_varied.plan
sw      help    tools.city_build.plan_varied.run_build
sw      help    tools/city_build/plan_varied/views.py
sw      help    tools/city_build/render_views.py
main    help    kokopelli.wm.controls.blur_variants
main    help    kokopelli/wm/controls/controls.py
sw      import  kokopelli/wm/controls/plaza_clip.py              # no argparse: running it needs the city server on 9001
main    help    kokopelli/wm/controls/prompts/build.py
cos     import  kokopelli.wm.controls.run_bridge_final        # no argparse: running it paints with Cosmos
# --- experiments, filter_test ---
sw      import  experiments/commons/analyze.py     # no argparse: running it rewrites the report
sw      import  experiments/commons/audit.py       # no argparse: running it runs the audit
sw      help    experiments/commons/run.py
main    help    experiments.filter_test.scripts.capture
main    import  experiments/filter_test/scripts/controls.py    # no argparse: running it rewrites the control videos
main    import  experiments/filter_test/scripts/preview_videos.py  # no argparse: running it renders previews
main    help    experiments.filter_test.scripts.run_cosmos
skip    -       experiments/filter_test/scripts/run_sd.py      # runs in its own experiments/filter_test/.venv (torch, diffusers), not one of the three; by hand: experiments/filter_test/.venv/bin/python experiments/filter_test/scripts/run_sd.py --help
# --- scripts ---
main    import  tools.fable.p4_c_compare      # no argparse: running it runs the comparison
main    import  tools/fable/p4_paint_gap.py      # no argparse: running it runs the measurement
main    help    tools.fable.p4_profile
main    import  tools/fable/p4_profile_table.py  # treats every argument as a file to read
main    import  tools/fable/reach.py             # hand-parses argv and ignores --help; running it scans the repo
main    help    tools.fable.stillness
main    help    tools.fable.stillness_score
sw      help    tools.pace.wmloop_one_tick
sw      help    tools.pace.wmloop_wait_server
# --- shell launchers ---
main    bash    experiments/benchmarks/noise_check_turns.sh
main    bash    kokopelli/agents/run_wm_life.sh
main    bash    kokopelli/agents/run_wm_lunch.sh
main    bash    tools/bodies/apply_core_data.sh
main    bash    tools/bodies/metahuman/run_editor_gui.sh
main    bash    tools/bodies/metahuman/setup_scratch.sh
main    bash    tools/bodies/migrate_bodies.sh
main    bash    tools/bodies/package_bodies.sh
main    bash    tools/bodies/perf_maxnear.sh
main    bash    tools/bodies/run_demo_lunch.sh
main    bash    tools/bodies/serve_9004.sh
main    bash    experiments/commons/overnight.sh
main    bash    experiments/filter_test/scripts/queue_all.sh
main    bash    tools/fable/p4_c_bits.sh
main    bash    tools/fable/p4_queue_all.sh
main    bash    tools/fable/p4_queue_profile.sh
main    bash    tools/fable/stillness300.sh
main    bash    tools/fable/stillness_queue.sh
main    bash    tools/fable/test_all.sh
main    bash    tools/pace/download_simworld.sh
main    bash    tools/pace/env.sh
main    bash    tools/pace/evals/dry_run.sh
main    bash    tools/pace/evals/env.sh
main    bash    tools/pace/setup_client.sh
main    bash    tools/pace/simworld_server.sh
main    bash    experiments/wm_multicontrol/run_a.sh
# --- console commands (phase 1 adds koko-* here) ---
'

tag_of() {   # interpreter path -> its tag
    case "$1" in
        "$MAIN_PY"|.venv/bin/python|./.venv/bin/python) echo main ;;
        "$SW_PY"|simworld/.venv/bin/python|./simworld/.venv/bin/python) echo sw ;;
        "$COS_PY") echo cos ;;
        *) echo sys ;;
    esac
}

# run CMD... with a time limit (no coreutils timeout on macOS)
limited() { perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$TIMEOUT" "$@"; }

run_one() {   # py tag kind target -> prints one line, returns 0/1
    local py="$1" tag="$2" kind="$3" target="$4" out rc dir
    local -a env_extra=()
    [ "$tag" = cos ] && env_extra=(PYTHONPATH="$COS_PATH")
    case "$kind" in
        help)
            if [[ "$target" == */* || "$target" == *.py ]]; then
                out=$(limited env ${env_extra[@]+"${env_extra[@]}"} "$py" "$target" --help 2>&1); rc=$?
            else
                out=$(limited env ${env_extra[@]+"${env_extra[@]}"} "$py" -m "$target" --help 2>&1); rc=$?
            fi ;;
        import)
            if [[ "$target" == */* || "$target" == *.py ]]; then
                dir=$(dirname "$target")
                out=$(limited env ${env_extra[@]+"${env_extra[@]}"} "$py" -c \
                    "import runpy, sys; sys.path.insert(0, '$dir'); runpy.run_path('$target', run_name='smoke_import')" 2>&1); rc=$?
            else
                out=$(limited env ${env_extra[@]+"${env_extra[@]}"} "$py" -c \
                    "import importlib; importlib.import_module('$target')" 2>&1); rc=$?
            fi ;;
        bash)
            out=$(bash -n "$target" 2>&1); rc=$? ;;
        cmd)
            out=$(limited "$(dirname "$py")/$target" --help 2>&1); rc=$? ;;
        *)
            echo "FAIL  ?       $target (unknown kind $kind)"; return 1 ;;
    esac
    if [ "$rc" -eq 0 ]; then
        printf 'ok    %-7s %s\n' "$kind" "$target"
        return 0
    fi
    [ "$rc" -eq 142 ] && rc="timeout ${TIMEOUT}s"
    printf 'FAIL  %-7s %s (exit %s): %s\n' "$kind" "$target" "$rc" \
        "$(printf '%s\n' "$out" | grep -v '^\s*$' | tail -1 | cut -c1-160)"
    [ -n "${VERBOSE:-}" ] && printf '%s\n' "$out" | sed 's/^/      | /'
    return 1
}

smoke() {   # one interpreter
    local py="$1" tag n_ok=0 n_fail=0 n_skip=0 line note tags kind target
    tag=$(tag_of "$py")
    if [ ! -x "$py" ]; then
        echo "FAIL  interpreter $py not found"; return 1
    fi
    echo "== $py ($tag, $("$py" -c 'import sys; print(sys.version.split()[0])'))"
    while IFS= read -r line; do
        note=""
        [[ "$line" == *"#"* ]] && note="${line#*#}"
        line="${line%%#*}"
        tags=""; kind=""; target=""
        read -r tags kind target _ <<<"$line" || true
        [ -z "$tags" ] && continue
        if [ "$tags" = skip ]; then
            printf 'skip  %-7s %s:%s\n' - "$target" "$note"
            n_skip=$((n_skip + 1)); continue
        fi
        if [ -z "${SMOKE_ALL:-}" ]; then
            case ",$tags," in
                *",$tag,"*|*",all,"*) ;;
                *) continue ;;
            esac
        fi
        if run_one "$py" "$tag" "$kind" "$target"; then n_ok=$((n_ok + 1)); else n_fail=$((n_fail + 1)); fi
    done <<<"$ENTRIES"
    echo "== $tag: $n_ok ok, $n_fail failed, $n_skip skipped"
    [ "$n_fail" -eq 0 ]
}

status=0
if [ $# -eq 0 ]; then
    for py in "$MAIN_PY" "$SW_PY" "$COS_PY"; do smoke "$py" || status=1; done
else
    for py in "$@"; do smoke "$py" || status=1; done
fi
exit $status
