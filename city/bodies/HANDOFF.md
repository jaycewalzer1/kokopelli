# Bodies handoff (wave 1 C, Python side, 2026-11-07)

The shared helper is `city/bodies/client.py`. It never raises on a server problem: an old server without
`SetBody`, a missing asset or a lost link come back as `BodyResult(ok=False, error=..., supported=...)`.
Tests: `tests/test_city_bodies.py`.

- `dress(wire, {actor: body_id})` sends `vbp <actor> SetBody <id>` for each one. It stops asking once the server
  shows it doesn't know the command.
- `get_body(wire, actor)` returns `.body` and `.tier`. The tier is `"near"`, `"far"`, `"fallback"` or None, and old
  replies have no tier.
- `tiers(wire, actors)` returns `{actor: tier}`.

## To the lunch session (`city/agents/lunch_wm.py`, owned by you, not edited here)

The suggested one-line change is in `SimWorldPair.reset` (lunch_wm.py:298). The two humanoids exist right after
`self.sim.reset`:

```python
    def reset(self):
        cap = self.sim.reset(seed=0)
        self.bodies = dress(self.sim.wire, {live.AGENT_ACTOR: "mara", FRIEND_ACTOR: "iris"})   # <- new line
        self._read(cap.state)
        return self._frames([cap])
```

You'd also need the import `from city.bodies.client import dress`. Then log
`{a: r.as_dict() for a, r in self.bodies.items()}` in `events.jsonl` and in `run.json` (`write_sidecar`), so the run
records which body each person got. If `dress` replies `ok: false`, the run should only warn, never stop. Without
this change, Mara and Iris still get bodies, because the server picks by actor name from `mac_server/Config/Bodies.json`
(`GEN_BP_Humanoid_0` -> mara, `_1` -> iris). The call only makes it explicit and recorded.

Near/far: the plan wants the tier for each person in every frame's sidecar, because a swap in view shows as a pop. After
each step, `tiers(self.sim.wire, [live.AGENT_ACTOR, FRIEND_ACTOR])` gives the tiers. `live.Life.log_tiers` (live.py)
does the same per step and warns once when someone drops to `"fallback"`.

## To the adapter owner (`runtime/adapters/simworld.py`, wm-agent-loop)

Nothing is needed. live.py sends `SetBody` through `sim.wire.request` after `sim.reset`, and it never changes the
adapter. One option for later: the adapter could put the per-frame tier in its own capture sidecars (one GetBody per
tracked person per capture). That would record exactly where a near/far pop happens, not only once per step.

## To the Sim-Transfer session (`city/agents/live_wm.py`)

`WorldModelLife` overrides `run` and `_live`, so it doesn't get the new calls and behaves as before. To pick them up,
call `self.dress(sim)` and `self.log_tiers(sim, step)` in your `_live`, and add `--body` to your args (`Life.agent_body`
reads it with `getattr`).

## Note on body ids

Each body is named after the person who wears it: npcs.json has ana, tomas, wen, priya and kai, and the agents are
mara and iris (`PLANNED_BODIES` in client.py). Kai stays `"kai"` on the client side even if no child body is made;
in that case B's Bodies.json maps `kai` to a fallback. `test_every_resident_body_is_in_bodies_json` starts running
once Bodies.json exists and will flag any id that's missing from it.
