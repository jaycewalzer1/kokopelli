## W0 baseline (orchestrator, 2026-11-09)

Branch `integration/fable` at ff6700d: main's HEAD plus the uncommitted varied city, AGENTS.md and bodies log.

| Suite | Command | Result |
|---|---|---|
| tests | `.venv/bin/python -m unittest discover -s tests` | 550 ran, OK (4 skipped, 2 expected failures), 199 s |
| runtime | `discover -s runtime/tests -t . -p 'test_[!s]*.py'` | 100 OK, 98 s |
| simworld | `simworld/.venv ... -p 'test_simworld*.py'` | 197 OK, 45 s |
| ops | `discover -s ops/tests -t .` | 13 OK, 13 s |
| benchmarks | `discover -s benchmarks/tests -t .` | 198 OK (1 skipped), 26 s |
| mac_server | `cd mac_server && SIMCV_START_MOCK=1 pytest tests` (simworld venv) | 212 passed, 29 failed, 16 skipped, 148 s. The 29 failures already exist on the baseline. |

The Makefile's `test-all` runs only `tests/`. Each package writes its own `docs/fable_log/<ID>.md`, so merges don't conflict; the orchestrator assembles `docs/FABLE_LOG.md` at the end.
