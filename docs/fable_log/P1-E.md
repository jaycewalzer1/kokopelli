## P1-E: split `runtime/adapters/simworld.py` (2026-11-09)

**What changed.** `runtime/adapters/simworld.py` went from 1344 to 795 lines. Code moved verbatim (a script cut it by line range, so no line inside a method was edited):
- `simworld_config.py` (154): blueprint asset and actor names, `VIEWMODES`, `SpawnSpec`, `NpcSpec`, `default_objects`, `SimWorldConfig`.
- `simworld_weather.py` (96): `WeatherMixin` with `_apply_weather_settings`, `set_weather`, `set_clock`, `_time_of_day`, `_apply_sun`, `_weather_json`, `read_weather`.
- `simworld_actions.py` (346): `ActionsMixin` with `_apply`, `_preempt`, `_on_foot`, `_out_of_range`, `_success`, `_send_checked`, every `_do_*` handler and its helpers, plus `_finish_outcome`, `_control` and the mover helpers (`_agent_io`, `_npc_io`, `_new_mover`, `_start_npc_routes`, `_next_waypoint`). These extra mover helpers moved because the three planned cuts alone left 848 lines, over the 800 target. `NON_PREEMPTING` moved with them.
- `simworld.py` keeps `SimWorldPhysics(WeatherMixin, ActionsMixin, PhysicsSim)`: lifecycle, state reading, renders, stepping, checkpoint and restore. It re-exports every config name and `NON_PREEMPTING`, so `from runtime.adapters.simworld import ...` works unchanged in all callers. Unused imports were dropped from it; none of them was imported from this module anywhere (checked with `git grep`).
- `runtime/SIMWORLD.md`: one "Files" paragraph listing the modules.

**Why it stays identical.** Nothing outside the module patches its globals (`git grep` for `mock.patch("runtime.adapters.simworld.`, assignments and `setattr` found none). The only outside patches are `mock.patch.object(real_unrealcv.time, "sleep")` and a `_render_lit` swap on the fake server instance, neither of which touches the moved code. The mixins come before `PhysicsSim` in the bases, and `TwoBodySim(SimWorldPhysics)` still comes first in its own MRO, so its overrides of `_apply`, `_control`, `_finish_outcome`, `render`, `_capture` and others still win. Under `simworld/.venv` (Python 3.10.22), a structural check against the old file (imported side by side) found the same attribute set on `SimWorldPhysics`, identical source for every method, identical source for the config classes, an equal default `SimWorldConfig().model_dump()`, and no abstract methods left.

**Numbers.**

| Check | Before | After |
|---|---|---|
| `simworld.py` lines | 1344 | 795 |
| simworld suite (`simworld/.venv`) | 197 OK, 48 s | see below |
| runtime suite (`.venv`) | 100 OK, 95 s | see below |
| `tests.test_city_lunch tests.test_bodies_demo_talk` | 24 OK | 24 OK |
| `ruff check --select F` on the four files | clean (old file) | clean |
