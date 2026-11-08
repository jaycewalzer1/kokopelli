# Conformance tests for the Mac SimWorld server

These tests check that a server behaves the way the **unchanged** simworld client
expects, as described in `../docs/SPEC.md`. They drive the server through the real client
classes (`UnrealCV`, `Communicator`, `WeatherManager`, `TrafficController`). For the
wire-protocol checks they use raw sockets instead.

| File | Purpose |
|---|---|
| `test_bodies.py` | Realistic bodies (`m6`): SetBody/GetBody, fallback chain, capsule/speed unchanged, eye camera height, hand-socket carry, one seg id, near/far tier switch + hysteresis + cap, crossfade, pose continuity. See `city/bodies/ANIMATION.md`. |
| `test_conformance.py` | Tests grouped by milestone with markers `m0`..`m5`. Tests marked `should` are recommended behavior, not strictly required. |
| `conftest.py` | Fixtures: one shared client, a raw socket helper, and per-test cleanup of `GEN_*`/`CT_*` objects. |
| `mock_server.py` | A pure-stdlib Python fake of the server. It covers M0/M1 and exists to check that the tests themselves are correct. |
| `pytest.ini` | Registers the markers. |

> Warning: the suite **destroys every object whose name starts with `GEN_`**, plus a few
> other test-owned prefixes, before and after each test. Do not point it at a server
> holding a world you care about.

## Running

The simworld venv uses uv and has no pip. pytest was installed into it with
`uv pip install --python ~/Desktop/kokopelli/simworld/.venv/bin/python pytest`.

Run from **outside** the simworld package dir. `-I` (isolated mode) stops Python from
adding your current directory and `PYTHONPATH` to the import path, so a stray local
file can't shadow `simworld`. The installed editable package is imported instead.

```bash
PY=~/Desktop/kokopelli/simworld/.venv/bin/python
T=~/Desktop/kokopelli/mac_server/tests

# Against the mock (it is started automatically on SIMCV_PORT):
SIMCV_PORT=9123 SIMCV_START_MOCK=1 $PY -I -m pytest $T -m "m0 or m1"

# Against the real UE server (port 9000 by default):
SIMCV_PORT=9000 $PY -I -m pytest $T -m m0          # one milestone
SIMCV_PORT=9000 $PY -I -m pytest $T -m "m0 or m1 or m2" -x
SIMCV_PORT=9000 $PY -I -m pytest $T -m "not should" # required behavior only

# Mock by hand (add -v to log every request and reply):
python3 $T/mock_server.py --port 9123 -v
```

Environment variables: `SIMCV_HOST` (default `127.0.0.1`), `SIMCV_PORT` (default
`9000`), `SIMCV_START_MOCK=1`.

If no server is listening, the session exits right away with a message. Without that
check, simworld's `UnrealCV()` would retry the connection forever.

Test counts per marker: m0 20, m1 183 (178 of them are the parametrized
"every prefab spawns" test), m2 11, m3 6, m4 5, m5 9, m6 14 (6 run on the mock, 8 need UE).

2026-11-07, editor-game on 9004 with bodies: `248 passed` (234 + 14 m6).

## Results against `mock_server.py` (2026-11-05)

```
$ SIMCV_PORT=9123 SIMCV_START_MOCK=1 $PY -I -m pytest $T -m "m0 or m1" -q
........................................................................ [ 35%]
........................................................................ [ 70%]
...........................................................              [100%]
203 passed, 31 deselected in 6.44s
```

M2–M5 against the mock: 26 failed, 5 passed (142 s). This is expected, because the mock
answers every `vbp` call with `error`. The 5 tests that pass only need object or
capture state, which the mock does implement: humanoid camera creation, teleport,
depth npy, bmp/file capture, and object_mask colors.

Found while validating the suite: `data/example_city/demo_city_1` uses
`BP_Building_64_C`, which is missing from `data/ue_assets.json`. The client skips that
node and logs "Can't find node". The M1 test excludes nodes the asset library cannot
resolve (SPEC 4.1).
