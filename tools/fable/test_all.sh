#!/usr/bin/env bash
# Run the test tree with pytest, one summary line per run; a failing run also prints its failing tests.
# Usage: tools/fable/test_all.sh [pytest args or paths ...]   (default: everything, in the runs below)
#   main         .venv (Python 3.12), -m "not py310": tests/, experiments/exp1/tests, experiments/homeostatic/tests
#   experiments  .venv, -m "not py310": experiments/benchmarks/tests, experiments/commons/tests
#   py310        simworld/.venv (Python 3.10), -m py310: the SimWorld tests (tests/loop/test_simworld*.py)
#   MAC=1        also run mac_server (starts a mock server on port 9000, so one checkout at a time).
#                Its 29 known baseline failures are reported but don't fail the run.
#   VERBOSE=1    print each run's full output with -v.
# Markers (conftest.py): model and slow are skipped unless RUN_MODEL_TESTS / RUN_LONG_TESTS is set; never set them here.
# Interpreters resolve from the repo this script lives in, so it works from any checkout or worktree.
cd "$(dirname "$0")/../.." || exit 2
# The tests peaked near 18 GB while they loaded real models, and five copies at once crashed the Mac on 2026-11-09. So the whole run takes one
# memory claim and waits its turn: python3 kokopelli/ops/memguard.py status shows who holds it.
[ -n "$MEMGUARD" ] || exec python3 kokopelli/ops/memguard.py run --name test_all --gb "${TEST_GB:-2}" -- bash "$0" "$@"
MAC_KNOWN_FAILURES=29
v=-q; [ "${VERBOSE:-0}" = 1 ] && v="-v -rA"
failed=0

one() {
  local name=$1; shift
  local start=$SECONDS log rc summary
  log=$("$@" 2>&1); rc=$?
  [ "${VERBOSE:-0}" = 1 ] && printf '%s\n' "$log"
  summary=$(printf '%s\n' "$log" | grep -E '[0-9]+ (passed|failed|skipped|deselected|errors?)|no tests ran' | tail -1 | tr -d '=' | sed 's/^ *//' | cut -c1-160)
  if [ "$rc" -eq 5 ]; then  # nothing collected for this interpreter (a path given for the other one)
    echo "$name none $((SECONDS - start))s"
    return
  fi
  if [ "$name" = mac_server ] && [ "$rc" -ne 0 ]; then
    local n
    n=$(printf '%s\n' "$log" | grep -oE '[0-9]+ failed' | tail -1 | cut -d' ' -f1)
    if [ -n "$n" ] && [ "$n" -le "$MAC_KNOWN_FAILURES" ] && ! printf '%s\n' "$log" | grep -qE '[0-9]+ errors?'; then
      echo "$name ok $((SECONDS - start))s $summary (baseline has $MAC_KNOWN_FAILURES known failures)"
      return
    fi
  fi
  if [ "$rc" -eq 0 ]; then
    echo "$name ok $((SECONDS - start))s $summary"
  else
    failed=1
    echo "$name FAILED rc=$rc $((SECONDS - start))s $summary"
    [ "${VERBOSE:-0}" = 1 ] || printf '%s\n' "$log" | grep -E '^(FAILED|ERROR) ' | head -40
  fi
}

# -W ignore as before: the libraries' deprecation warnings drown the summary.
# With no arguments, benchmarks and commons get a process of their own, as they had before: benchmarks' resume test fakes
# time.time, and a daemon thread the life tests leave reading macmon (kokopelli/life/gpu_queue.py) eats the fake clock.
# shellcheck disable=SC2086  # $v is empty or a flag, left unquoted so an empty value adds no argument
if [ $# -gt 0 ]; then
  one main .venv/bin/python -W ignore -m pytest $v -rfE -m "not py310" "$@"
else
  one main .venv/bin/python -W ignore -m pytest $v -rfE -m "not py310" tests experiments/exp1/tests experiments/homeostatic/tests
  one experiments .venv/bin/python -W ignore -m pytest $v -rfE -m "not py310" experiments/benchmarks/tests experiments/commons/tests
fi
# shellcheck disable=SC2086  # as above
one py310 simworld/.venv/bin/python -W ignore -m pytest $v -rfE -m py310 "$@"
[ "${MAC:-0}" = 1 ] && one mac_server sh -c "cd mac_server && SIMCV_START_MOCK=1 ../simworld/.venv/bin/python -m pytest $v -p no:cacheprovider tests"
exit $failed
