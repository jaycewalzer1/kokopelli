# SimWorld adapter

SimWorld holds physical truth in the world-model loop. The loop sends it an action, it advances exactly 30 sim-seconds, and it returns the state and ground-truth renders.

**Status: this has never touched a real Unreal server.** Everything passes against a fake server I wrote, which only proves our client sends what we believe is right. One PACE job will show which beliefs hold: see [Run it on PACE](#run-it-on-pace).

**Files.** `runtime/adapters/simworld.py` holds `SimWorldPhysics`: lifecycle, reading state, renders, stepping, checkpoint and restore. It re-exports everything from `simworld_config.py` (blueprint names, `SpawnSpec`, `NpcSpec`, `SimWorldConfig`). Two mixins hold the rest: `simworld_weather.py` (weather, clock, sun) and `simworld_actions.py` (the `_do_*` handlers and the movers that carry them out). Below them: `simworld_wire.py` (the socket), `simworld_commands.py` (every command string), `simworld_control.py` (the `move_to` controller), `simworld_math.py` and `simworld_bridge.py`.

## Terms

| Term | Meaning |
|---|---|
| Step | One turn of the loop: 30 sim-seconds. 60 steps make a 30-minute life. |
| Engine tick | One Unreal frame in sync mode, lasting `tick_interval_s`. At the default 0.1 s, a step is 300 engine ticks. |
| Sync mode | Unreal stays paused and only advances when told to. Sim time then depends on how many ticks we send, not on how fast the machine is. |
| Sim time | Engine ticks × `tick_interval_s`. Never the wall clock. |
| Capture | The state and renders at one moment. Each step has two, at +15 s and +30 s. |
| Blueprint call (`vbp`) | A command that runs a function on an Unreal actor, like `vbp NAME MoveForward`. |
| Intrinsics | How the camera turns directions into pixels: focal length and image centre. |
| Extrinsics | Where the camera is and which way it points. |
| Finite difference | Estimating velocity as (position now − position earlier) / time between them. |
| Segmentation / object mask | An image where each object is painted one flat colour. |
| Null agent | An agent that only sends `wait`, used as a counterfactual: what would have happened with no action. |

## Use it

```python
from runtime.adapters.simworld import SimWorldConfig, SimWorldPhysics

with SimWorldPhysics(SimWorldConfig(port=9000, start_time="08:00")) as sim:
    first = sim.reset(seed=0)                     # Capture at time zero
    start = sim.get_state()                       # SimCheckpoint
    result = sim.step({"type": "move_to", "target_id": "npc_0"})
    result.outcome.status                         # completed, in_progress, failed or unverified
    result.captures[0].renders["rgb"].path        # the +15 s frame on disk
    result.final_state.to_prompt_text()           # compact text for a prompt
    result.timing.stepping_s                      # seconds per stage
    report = sim.restore_state(start)             # measured errors, in report.position_errors_cm
```

`runtime/physics.py` holds the types and needs only pydantic. The adapter needs `unrealcv==1.3.2`, numpy and pillow, and does not import the `simworld` package.

## Capabilities

"Tested on fake" means the client logic is tested. "Needs real-server check" lists what only Unreal can answer, and each item matches a line in the gate script's output.

| # | Capability | State | Tested on fake | Needs real-server check |
|---|---|---|---|---|
| 1 | Lifecycle, errors, bounded reconnect | Done | Spawn order, down and not-ready errors, one-client refusal, reconnect limits, paused-server recovery | Asset paths exist in the package. `vset /action/game/level`. How a real server treats a second client and a dropped client |
| 2 | Deterministic 30 s stepping | Done | 300 and 120 ticks by count, captures between the right ticks, tick log, invalid action changes nothing | **The central assumption:** does one tick advance exactly `tick_interval_s`, and does it block until done? Does paused mean paused? |
| 3 | PhysicalState | Done | JSON round trip, prompt text, stable ids, velocity, intrinsics formula | Camera rotation order. Reply formats. That the agent's camera id is what we find |
| 4 | Renders | Done | Hashes, raw depth, sizes, errors raise, mask map | Depth units. Renders while paused show the current frame. `vget /object/X/color` exists. Colours we set reach the mask but not the lit image |
| 5 | Action schema | Done | Every rejection case, catalog matches the union | That each blueprint function exists on `Base_User_Agent` |
| 6 | `move_to`, `look_at`, `speak`, `interact` | Done | Arrival, 30 s overrun, blocked, chasing a target, gaze tracking, hearing radius, every interact kind | `MoveForward` and `TurnAround` play out across paused ticks. Whether a camera rotation sticks. Scooter camera. Sit with no seat argument |
| 7 | Time of day and weather | Done, if the weather asset exists | Formula by hand, updates per capture, set and read back | **The weather manager may not be in the package** (`unrealcv.py:1180` says not in production use). Sun pitch sign. Sensible `max_sun_intensity` |
| 8 | Checkpoint and restore | Partial by nature | Round trip, rewinds, undoes rides and pick-ups, crash resume on a restarted server, measured errors | How much replays really diverge. See [What restore does not bring back](#checkpoint-and-restore) |
| 9 | Determinism | Partial by nature | Same seed sends identical commands and gets identical frames | Real drift between runs, reported in cm. **Unreal itself cannot be seeded from the client** |
| 10 | Per-stage timing | Done | All fields present and consistent | The real numbers, for Phase 7 |
| 11 | PACE preparation | Written, never run on PACE | Valid bash, dry run, full job against a stub server including cleanup | Everything site-specific: modules, Vulkan, `--cvport`, Apptainer image |
| 12 | Gate script | Done | Passes on the fake, labelled FAKE everywhere | That is its job |

### What is impossible with this client

- **Seeding Unreal.** No seed command exists in `unrealcv.py`. `simworld.seed` only seeds Python generators (`traffic_controller.py:63`, `city_generator.py:37`). We report measured drift instead.
- **A true save-state.** No such command exists, so restore teleports actors. See below.
- **Reading velocity.** No such command exists in `unrealcv.py` or in the pip client's command list, so it is always a finite difference, and it is labelled that way in the state.
- **NPCs reacting to speech.** `speak` has no physics effect. It records who was in range, and they do nothing.
- **Interacting with an NPC.** No such function exists, so `interact` rejects NPC targets. Use `speak` or `gesture`.
- **Choosing a specific scooter or seat.** `GetOnScooter` and `SitDown` take no target (`unrealcv.py:707`, `:677`). We check range, then the blueprint presumably uses the nearest. Unverified.

## Why the adapter bypasses `unrealcv.py`

The audit's list of methods was right, but several of them are unsafe here. The adapter sends the same command strings through the pip `unrealcv.Client`, and `test_simworld_contract.py` runs the real class against the fake to prove the strings match. `WhyWeBypassUnrealcvPyTest` pins the first four traps below, so this section stays true.

| Where | Problem | Consequence if we had called it |
|---|---|---|
| `unrealcv.py:1083-1085` | `get_image` catches every error and returns a black 640×480 array | A failed render looks like a dark scene, silently poisoning drift checks |
| `unrealcv.py:1096-1110` | `_decode_npy` log-scales depth and paints it with a colormap | No metric depth, just a coloured picture. We save the raw `npy` |
| `unrealcv.py:658`, `:635` | `humanoid_step_forward` and `humanoid_rotate` call `time.sleep` | Up to 30 s of wall-clock waiting per action, during which a paused game does nothing |
| `unrealcv.py:680-684` | `str(json.loads(res)['Success'])` is compared with `'true'` | A JSON boolean becomes `'True'`, matching neither branch, and the method returns None |
| `unrealcv.py:71-74` | `check_connection` loops forever | A down server hangs the process with no error |
| `unrealcv/__init__.py:330` | `connect` waits for the hello with no timeout | A half-started server hangs the process |
| `unrealcv/__init__.py:544` | `request_batch` has no timeout | One hung command hangs forever, which rules out the batch helpers at `unrealcv.py:307` and `:338` |
| `local_planner.py:146` | `navigate_rule_based` loops until arrival, sleeping | See below |

### Does NAVIGATE work without its LLM?

Partly, and it still cannot be used. `rule_based=True` makes no LLM calls in `navigate_to` (only `parse` and vision mode do), but it blocks in a loop until arrival (`local_planner.py:146`). In sync mode nothing is ticking during that loop, so the agent never arrives and it never returns. It also needs a `Map` from a roads file, a separate thread updating positions, and an import of `simworld.llm`, which needs `openai`. So `move_to` uses my own controller, `simworld_control.py`, which copies its rules (5 degree alignment, `:270`) but is driven by the tick loop.

Separately, `local_planner.py:223` unpacks 3 values from a function that returns 4, so vision-based navigation would crash. There's a proposed fix in `HANDOFF.md`.

## What the audit got right and missed

- **Confirmed:** no `speak`, `look_at` or general `interact`. `dog_look_up` is robots only. Sync stepping at `unrealcv.py:206-233`. No time-of-day API. Python versions.
- **Actions it missed:** `humanoid_move_forward`, `humanoid_drop_object`, `humanoid_enter_vehicle`, `humanoid_exit_vehicle`, `s_set_state`, `v_set_state`, gestures (`discuss`, `argue`, `listen`, `wave_to_dog`, `directing_path`, `stop_current_action`), and `humanoid_set_path` / `humanoid_follow_path`.
- **Depth:** it does arrive as npy, but `get_image` destroys the values. See above.
- **Docs that don't match the client:** `agent_system.rst` lists humanoid "Look Up/Down" and "Focus", and no client method exists for them. Its call `humanoid_stop(agent.id, 2)` has one argument too many.
- **Commands not in `unrealcv.py`:** three come from the pip client only, and may not exist on SimWorld's server: `vget /object/X/color` (`api.py:744`), `vset /action/game/level` (`api.py:1338`), `vget /unrealcv/commands` (`__init__.py:232`). Conversely, `vset /action/tick` and `/action/tick_intervel` (misspelling is real) appear only in `unrealcv.py:225,231`, not in the pip client. Every string is listed with its source in `runtime/adapters/simworld_commands.py`.

## Actions

The source of truth is `ACTION_CATALOG` in `runtime/physics.py`, which also gives each action's primitives, source line and across-step behaviour. A test keeps these lists matching it.

**Native** (one blueprint call): `move_forward`, `step_forward`, `rotate`, `stop`, `set_speed`, `sit_down`, `stand_up`, `pick_up`, `drop_object`, `get_on_scooter`, `enter_vehicle`, `exit_vehicle`, `drive`, `gesture`, `stop_gesture`.

**Composed** (several primitives plus adapter logic): `move_to`, `look_at`, `interact`, `get_off_scooter`.

**No physics effect:** `speak`, `wait`, `continue`.

### What happens across steps

- A new action replaces whatever was running. The exceptions are `speak` and `set_speed`, which leave it alone, and `continue`, which exists to keep it going.
- `move_to` that hasn't arrived at +30 s returns `in_progress` and `active_task` is set. Send `continue` or the same `move_to` again. Sending anything else cancels it and stops the agent. At 200 cm/s a step covers at most 60 m.
- `move_to` fails as `blocked` if it moves under 20 cm in 8 sim-seconds, then stops the agent. It walks a straight line with no pathfinding, so it will hit walls: see the decisions below.
- `move_forward` and `gesture` run until replaced.
- `step_forward` and `rotate` end within the step. Duration over 30 s is rejected by the schema.
- `look_at` turns the body once, then re-aims the camera before every capture until another action clears it.
- `interact` never walks there for you. An out-of-range target fails with a reason.

## Formulas

**Intrinsics**, in `simworld_math.py:intrinsics_from_fov`. Half the image width subtends half the field of view, so `tan(fov/2) = (width/2) / fx`:

```
fx = (width / 2) / tan(fov_horizontal / 2)
fy = fx                       # Unreal renders square pixels
cx, cy = width / 2, height / 2
```

**Extrinsics.** Location plus Unreal's rotation matrix. Axes are x forward, y right, z up, and **Unreal is left-handed**, so don't pass the matrix to OpenCV without converting. `project_point` shows the correct maths: `u = cx + fx·right/forward`, `v = cy − fy·up/forward`.

**Time of day**, in `simworld_math.py:time_of_day`. With `f = (hour − sunrise) / (sunset − sunrise)`:

```
elevation = max_elevation · sin(π·f)         # 70° at noon, −70° at midnight
azimuth   = sunrise_azimuth + 180·f          # sweeps 90° to 270° by day
intensity = max_intensity · max(0, sin(π·f)) # zero all night
```

It ignores latitude, season and twilight. It only has to be consistent. The clock is `start_time + sim time`, and the sun is updated one tick before each capture, so the frame and the state agree.

## Checkpoint and restore

`get_state()` returns a JSON-serializable `SimCheckpoint`. `restore_state()` works by teleporting, in this order: get off any scooter or vehicle, respawn anything missing (agent first, to keep its camera id), pause, stop everyone, run 2 s of uncounted ticks so turns in flight finish, teleport, re-apply speed, held object, posture, weather and sun. It then reads every position back and returns the error in cm.

**Restored:** tick count and sim clock, agent pose, speed, posture, held object, riding state, running task and gesture, gaze, NPC poses, speeds and route progress, object poses, weather, clock, camera size and aim, mask colours.

**Not restored**, also listed in every checkpoint's `not_restored`:

- Velocity and momentum. Actors restart at rest, so the first moments differ.
- Animation pose and blend state.
- NPC controller internals. Routes resume toward the saved waypoint, from rest.
- Character movement state, such as being mid-air.
- Physics solver state: sleep state, contacts, angular velocity.
- Anything the adapter didn't spawn: level actors, or traffic if you start it yourself.
- Traffic signal timers and vehicles. The adapter doesn't run them.
- Collision counters, which are cumulative with no reset command.
- Renderer history: temporal anti-aliasing, auto-exposure, Lumen caches. Pixels may differ after a restore even if every pose matches.
- Unreal's own frame counter and world time.

So a **null-agent counterfactual is an approximation**. Its accuracy is unknown until gate check "9 replay from a checkpoint repeats" reports a number in cm. A crash resume is similar. I recommend deciding how much drift is acceptable once you see that number.

A replay never overwrites earlier renders, since each restore writes to a new `branch_N` folder.

## Determinism

**Seeded by us:** one `random.Random(seed)`, used only at reset for the default NPC layout. Control decisions depend on tick counts and server poses, never on the wall clock. The seed is in every checkpoint. On the fake, the same seed gives identical commands and identical frame hashes, which is tested.

**Known sources of non-determinism in Unreal that we can't control** (from general Unreal knowledge, none measured here):

- Physics solver: substeps, contact resolution order, and floating-point differences across machines.
- Blueprint timers and timelines, and whether each one honours the pause and tick mechanism.
- Spawn collision handling, which can nudge an actor sideways.
- Async asset and shader loading: a first render can differ, and `unrealcv.py:66` hints at this.
- Renderer: temporal accumulation, auto-exposure, Lumen, and streaming of textures and meshes.
- Different GPU or driver between jobs, so **pin a node type for comparable runs**.
- Any level actor with its own ticking logic.

Sync mode removes the largest source, which is timing between client and server, but only if the assumption in capability 2 holds.

## What remains unverified

The gate script tests each of these on a real server.

| Assumption | Why I believe it | Gate check |
|---|---|---|
| One tick advances exactly `tick_interval_s`, and blocks | `ue_detail.rst:84,95` says so | 2 tick interval really scales sim time |
| Game stays frozen with no ticks | `ue_detail.rst:84` | 2 paused means paused |
| `MoveForward`, `TurnAround`, `StepForward` play out in sim time when paused | Nothing. All SimWorld examples run async. **Biggest risk** | 2 tick interval, 6 move_to |
| Depth units are cm | Unreal convention. Not in any SimWorld file | 4 depth values |
| Rotation order is pitch yaw roll | `:969`, `ue_detail.rst:69`, `api.py:638`. Contradicted by `:921` | 3 camera rotation order |
| Agent has the nearest camera, rides with it | `agent_system.rst:71` | 3 camera is the agent's |
| Render while paused shows the current frame | Nothing | 4 renders, 6 look_at (look at the image) |
| Camera survives scooter swap | Nothing. The humanoid is replaced (`communicator.py:110-125`) | 6 interact rides the scooter |
| `vset` object colour changes only the mask | Upstream comment at `api.py:750`, and `communicator.py:864`. `unrealcv.py:141` only says "set object color" | 4 mask colours, look at the RGB image |
| Weather manager exists in the package | `:1180` says not in production | 7 time of day |
| Daytime sun has negative pitch | `communicator.py:967` shows `P=-26`, while commented-out presets at `weather_manager.py:272,304` imply the opposite | 7 daytime sign |
| Reply formats from the fake match reality | Copied from how the client parses them. **Not recorded from a real server** | All of them |
| `--cvport` works on Linux | `minimal_example.rst:10` | Job prints a message if the server answers on 9000 instead |
| `-RenderOffScreen` works with this package | `unrealcv/launcher.py:189` for UnrealCV in general | Job log |

## Run it on PACE

You fill in the placeholders. I did not invent any PACE values, and none of this has run there.

**What you must fill in:**

- `scripts/pace/env.sh`: `WMLOOP_MODULES`, `WMLOOP_SIMWORLD_DIR`, `WMLOOP_VENV`, `WMLOOP_OUT`, and `WMLOOP_APPTAINER_IMAGE` if you need a container.
- `scripts/pace/wmloop_gate.sbatch`: `--account`, `--partition`, `--gres`.

**Steps**, from the repo root on PACE, with this branch checked out:

```sh
# 1. Client environment, on a login node. Ends by running the fake checklist, no GPU needed.
bash scripts/pace/setup_client.sh

# 2. See the package size and free disk. Downloads nothing.
bash scripts/pace/download_simworld.sh

# 3. Download it, once the size looks right. README says at least 50 GB of disk.
bash scripts/pace/download_simworld.sh --yes

# 4. Check the plumbing without a cluster job.
WMLOOP_DRY_RUN=1 bash scripts/pace/wmloop_gate.sbatch

# 5. Submit. Client and server run on the same node.
mkdir -p logs
sbatch scripts/pace/wmloop_gate.sbatch
```

The job picks a free port, starts UE with `-RenderOffScreen`, waits for the UnrealCV hello, runs one tick, runs the checklist, and stops only the process group it started.

**Send back:** `send_back_<job>.tar.gz` (the job prints its path) and `logs/wmloop_gate_<job>.out`. The bundle has the two reports, `environment.txt`, `server_commands.txt`, UE logs, noon and midnight test images, and one set of renders. Look at the renders yourself too, since several checks print `LOOK` where only a person can judge.

**If it goes wrong:**

| Symptom | Try |
|---|---|
| UE dies at startup with Vulkan errors | Check `vulkaninfo` in `environment.txt`, then try `WMLOOP_RUNTIME=apptainer` |
| "It IS answering on 9000" | `--cvport` was ignored. Set `WMLOOP_PORT_VIA_INI=1`, which edits `unrealcv.ini`. Use with one job at a time, since the package folder is shared |
| Never ready | Raise `WMLOOP_READY_TIMEOUT_S`. First shader compile may take a long time |
| Wrong GPU | Set `WMLOOP_GPU_INDEX`. UE uses `-graphicsadapter`, and may ignore `CUDA_VISIBLE_DEVICES` |
| Download URL has gone | Set `WMLOOP_SIMWORLD_URL`. `installation.rst:63` lists an older path |

## Test it here

```sh
simworld/.venv/bin/python -W ignore -m unittest discover -s runtime/tests -t . -p 'test_simworld*.py'
simworld/.venv/bin/python -W ignore scripts/pace/wmloop_one_tick.py --fake --checklist
```

Run from the repo root. In a worktree, use the absolute path to the main checkout's `simworld/.venv`, since venvs aren't copied.

Latest results on the Mac, 2026-11-05:

| Environment | Result |
|---|---|
| `simworld/.venv`, Python 3.10 | 193 tests, all passed |
| Scratch venv with only the packages in `setup_client.sh` | 193 tests, passed, 9 skipped (real client contract tests need the full `simworld` dependencies) |
| Root `.venv`, Python 3.12, pure tests only | 35 tests, all passed |
| Gate checklist on the fake | 31 pass, 0 fail, 3 to look at |

**The fake server** (`runtime/tests/fake_unrealcv.py`) speaks the real framing and binds only to 127.0.0.1. The commands it accepts are its `routes()` table, each citing the client line that sends it. Reply formats are inferred from how the client parses them, and its physics is invented. It deliberately models the worst plausible cases: a stop doesn't cancel a turn, and a camera rotation sticks.

## Decisions for the owner

I picked the simplest reversible default for each of these so work could continue. They're yours to change.

| Decision | Default | Options and tradeoffs | Change it with |
|---|---|---|---|
| Engine tick length | 0.1 s, 300 per step (`simworld.dt` in `example.yaml:3`) | 0.05 s is the docs' example: smoother physics but twice the cost per step. Longer is cheaper, but fast movers can pass through walls. Decide after seeing real ms per tick | `tick_interval_s` |
| How `move_to` is built | Own controller on turn, walk, stop | `SetPath` + `FollowPath` (`unrealcv.py:867,877`) might be native and smoother, but it's undocumented and unverified under pause. The pip client also lists `/agent/X/nav/goto`, likely absent here. NAVIGATE can't work (above) | `simworld_control.py` |
| Pathfinding | None: straight line, fails as `blocked` | `Map.get_shortest_path` gives roads-based routes but needs a roads file and imports more of `simworld`. Or let the agent route around things itself | Add waypoints to `MoveTo` |
| A new action during a running task | It replaces the task, except `speak`, `set_speed`, `continue` | Queueing feels friendlier, but makes "what is the agent doing" harder to read | `NON_PREEMPTING` |
| `interact` out of range | Fails with a reason | Auto-walking is convenient, but hides travel time inside one action | `_do_interact` |
| Hearing | 10 m sphere, walls ignored | Line-of-sight would need ray queries, which aren't available | `hearing_radius_cm` |
| NPCs | 2, seeded, walk loops driven from Python | SimWorld's traffic system gives crowds and signals, but its Python loop runs on the wall clock, so it needs a rewrite for sync mode. Python-driven walkers cost round trips per NPC | `npc_count`, `npcs` |
| Scene | Agent at origin, a mug, a box, a scooter, from SimWorld's notebook. No seat, since I know of no seat asset | Your life slice will want its own. Pass `objects=[...]`, with `existing=True` for level actors | `objects` |
| Control rate | Every 0.5 sim-seconds | Faster gives tighter arrival, more round trips | `control_interval_s` |
| Sun | 08:00 start, 06:00–18:00, peak 70°, max intensity 10, sign −1 | Intensity 10 is a guess: the gate reports what the level started with. Flip the sign if midnight comes out brighter | `start_time`, `sunrise_h`, `sunset_h`, `max_sun_elevation_deg`, `max_sun_intensity`, `sun_pitch_sign` |
| Restore | Teleport after a 2 s flush, tolerance 5 cm | A warm-up after restore would let physics settle, at the price of more divergence | `restore_flush_s`, `restore_tolerance_cm` |
| A lost tick | Stepping refuses until `restore_state` | Resending might double-tick and silently break exact sim time. Reads do retry automatically | `Wire.request` |
| Render format | 320×240, PNG, raw npy depth | `bmp` is faster and larger (`unrealcv.py:1067`). Compare once real times are known | `resolution`, `VIEWMODES` |
| Mask colours | Set our own for tracked actors, then read back | Reading only avoids any risk to the lit image, but spawned actors may have no colour. If the RGB image shows odd colours, turn this off | `assign_mask_colors` |
| UE manager | Spawned, `unrealcv+.rst:64` calls it required | We read poses directly and don't use it, so it may be removable | `spawn_ue_manager` |
| Client library | Pip `unrealcv.Client` plus our own command strings | Calling `unrealcv.py` directly is less code but has the traps above. The contract test guards against drift | `HANDOFF.md` has fixes that would let you switch |

## When you're back: read these

Your `CLAUDE.md` asks for this, and tonight was unattended, so I saved it. Try to answer each before running anything.

1. `runtime/adapters/simworld_wire.py`, the `except` block in `Wire.request`. Why does a **timeout** drop the whole connection, instead of just retrying? What would the next request receive otherwise?
2. `runtime/adapters/simworld_wire.py`, the `resend` logic. Why may a `vget` be resent after a lost link but not `vset /action/tick`? What would a resend do to `sim_time_s`?
3. `runtime/adapters/simworld_control.py`, `Mover.update`. Predict what happens to an agent walking straight at a wall, tick by tick. Which line ends it?
4. `runtime/adapters/simworld_math.py`, `intrinsics_from_fov`. Without running it: what is `fx` for a 640-wide image at 60 degrees? What happens to `fx` if you widen the field of view, and why?
5. `runtime/adapters/simworld.py`, `_before_capture`, which runs one tick **before** the capture. What could go wrong in the rendered frame if it ran after the last tick instead?
6. Predict before the first PACE run: will gate check "2 tick interval really scales sim time" pass? If the ratio comes back near 0, what does that tell you, and what would you do next?
