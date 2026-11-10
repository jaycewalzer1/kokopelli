#!/usr/bin/env bash
# Run every test suite, one summary line each; a failing suite also prints its failing tests.
# Usage: scripts/fable/test_all.sh [suite ...]   (default: tests runtime simworld ops benchmarks)
#   MAC=1      also run mac_server (starts a mock server on port 9000, so one checkout at a time).
#              Its 29 known baseline failures are reported but don't fail the run.
#   VERBOSE=1  print each suite's full output with -v.
# Interpreters resolve from the repo this script lives in, so it works from any checkout or worktree.
cd "$(dirname "$0")/../.." || exit 2
# The tests suite peaked near 18 GB while it loaded real models, and five copies at once crashed the Mac on 2026-11-09. So the whole run takes one
# memory claim and waits its turn: python3 ops/memguard.py status shows who holds it.
[ -n "$MEMGUARD" ] || exec python3 ops/memguard.py run --name test_all --gb "${TEST_GB:-2}" -- bash "$0" "$@"
want=${*:-tests runtime simworld ops benchmarks}
[ "${MAC:-0}" = 1 ] && case " $want " in *" mac_server "*) ;; *) want="$want mac_server" ;; esac
MAC_KNOWN_FAILURES=29
v=; [ "${VERBOSE:-0}" = 1 ] && v=-v
failed=0

one() {
  local name=$1; shift
  case " $want " in *" $name "*) ;; *) return ;; esac
  local start=$SECONDS log rc summary
  log=$("$@" 2>&1); rc=$?
  [ -n "$v" ] && printf '%s\n' "$log"
  summary=$(printf '%s\n' "$log" | grep -E '^Ran [0-9]+ test|^(FAILED|OK)|[0-9]+ (passed|failed)' | tail -3 | tr '\n' ' ' | cut -c1-160)
  if [ "$name" = mac_server ] && [ "$rc" -ne 0 ]; then
    local n
    n=$(printf '%s\n' "$log" | grep -oE '[0-9]+ failed' | tail -1 | cut -d' ' -f1)
    if [ -n "$n" ] && [ "$n" -le "$MAC_KNOWN_FAILURES" ] && ! printf '%s\n' "$log" | grep -qE '[0-9]+ errors?'; then
      echo "$name ok $((SECONDS - start))s $summary(baseline has $MAC_KNOWN_FAILURES known failures)"
      return
    fi
  fi
  if [ "$rc" -eq 0 ]; then
    echo "$name ok $((SECONDS - start))s $summary"
  else
    failed=1
    echo "$name FAILED rc=$rc $((SECONDS - start))s $summary"
    [ -z "$v" ] && printf '%s\n' "$log" | grep -E '^(FAIL|ERROR):|^FAILED |^ERROR ' | head -40
  fi
}

one tests .venv/bin/python -W ignore -m unittest discover $v -s tests
one runtime .venv/bin/python -W ignore -m unittest discover $v -s runtime/tests -t . -p 'test_[!s]*.py'
one simworld simworld/.venv/bin/python -W ignore -m unittest discover $v -s runtime/tests -t . -p 'test_simworld*.py'
one ops .venv/bin/python -W ignore -m unittest discover $v -s ops/tests -t .
one benchmarks .venv/bin/python -W ignore -m unittest discover $v -s benchmarks/tests -t .
one mac_server sh -c "cd mac_server && SIMCV_START_MOCK=1 ../simworld/.venv/bin/python -m pytest ${v:--q} -p no:cacheprovider tests"
exit $failed
