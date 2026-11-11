# Handoff

From the SimWorld overnight session to the main session and the owner. Nothing here is applied. These are all in files I was told not to edit.

## For the main session: how to use this

Import from `kokopelli/loop/physics.py`, which only needs pydantic, so it works from the root `.venv`:

```python
from runtime.physics import PhysicsSim, PhysicalState, Capture, StepResult, SimCheckpoint, parse_action, action_json_schema
```

The interface:

```python
class PhysicsSim(abc.ABC):
    def reset(self, seed=None) -> Capture
    def step(self, action) -> StepResult              # one action, then exactly 30 sim-seconds
    def get_state(self) -> SimCheckpoint
    def restore_state(self, checkpoint) -> RestoreReport
    def close(self) -> None
```

A mock for your loop only has to implement those five methods. Worth knowing:

- `step` raises `pydantic.ValidationError` on a bad action before anything changes, so you can return the error to the model and ask again. `parse_action(raw, targets)` lets you validate first, and `action_json_schema()` can constrain the model's output.
- `result.captures` is `[+15 s, +30 s]`. Drift checks get a render every 15 sim-seconds from there. `result.final_state` is the +30 s state.
- `result.outcome.status` can be `in_progress`. Send `{"type": "continue"}` to keep a long `move_to` going. Anything else cancels it, except `speak` and `set_speed`.
- `speak` has no physics effect. `result.speech_events` lists who was in range, and they don't react, so anything NPCs "say" is up to your side.
- A null agent sends `{"type": "wait"}`.
- If `step` raises `SimWorldError`, the world is half-advanced. It refuses further steps until `restore_state` or `reset`, so **save a checkpoint with `get_state().save(path)` at whatever interval you want to resume from**. It costs a few round trips.
- `SimWorldPhysics` needs `unrealcv==1.3.2`, numpy and pillow, so it won't import from the root `.venv`. Import it lazily, or run the loop's physics side from the venv made by `tools/pace/setup_client.sh`.

I did not create `kokopelli/loop/interfaces.py`, `kokopelli/loop/loop.py`, `kokopelli/loop/run.py` or mocks.

## Proposed: `.gitignore`

`sbatch` writes to `logs/`, which isn't ignored. Renders go to `out/`, which already is.

```diff
--- a/.gitignore
+++ b/.gitignore
@@ -1,6 +1,7 @@
 __pycache__/
 *.pyc
 out/
+logs/
 models/
 .venv/
 .DS_Store
```

## Proposed: a test target

`Makefile` isn't in this branch's tree, so I can't give an exact diff. Add:

```make
test-simworld:
	simworld/.venv/bin/python -W ignore -m unittest discover -s tests/loop -t . -p 'test_simworld*.py'
```

## Proposed: `README.md`

Add a row to the file table:

```
| `kokopelli/loop/` | The world-model loop. `kokopelli/loop/SIMWORLD.md` covers the physics side |
```

## Proposed: `requirements.txt`

No change. The root `.venv` already has pydantic through `mlx-vlm`. If the loop is ever meant to import `kokopelli/loop/physics.py` on a machine without it, add `pydantic>=2`. The SimWorld client's packages are in `tools/pace/setup_client.sh`, deliberately separate, since this Mac doesn't run Unreal.

## Proposed: fixes to `simworld/`

The adapter works around all of these and doesn't need them. They would help anyone calling SimWorld's client directly. I checked the patch with `git apply --check` against this branch, but didn't run the code with them applied, and the upstream project may have its own view.

1. **`check_connection` loops forever** on a down server. Now gives up after 30 tries.
2. **`get_image` returns a black frame on any error**, which looks like a dark scene. Now raises. Check first: `simworld/` code that relies on the black frame would start raising, and I found no such code, but I didn't test the notebooks.
3. **`Success` parsing returns None for JSON booleans.** `.lower()` handles both forms. If the real server only sends strings, this is harmless.
4. **`local_planner.py:223` unpacks 3 values from a 4-value return**, so vision-based navigation raises `ValueError` the first time it steps forward. This one is a clear bug from reading the code.
5. **`clear_env` destroys actors using lowercased names** (`communicator.py:889,902`), which only works if Unreal's name lookup ignores case. Unverified, so this may not be a live bug. The fix is safe either way.

Not proposed: the raw-depth problem at `unrealcv.py:1096`. Changing `_decode_npy` would break notebooks that display its result, so the fix is an added method, which is your call.

```diff
--- a/simworld/simworld/communicator/unrealcv.py
+++ b/simworld/simworld/communicator/unrealcv.py
@@ -68,9 +68,12 @@
 
     def check_connection(self):
-        """Check connection status, attempt to reconnect if not connected."""
-        while self.client.isconnected() is False:
+        """Check connection status, attempt to reconnect a limited number of times."""
+        for _ in range(30):
+            if self.client.isconnected():
+                return
             self.logger.error('UnrealCV server is not running. Please try again')
             time.sleep(1)
             self.client.connect()
+        raise ConnectionError('UnrealCV server is not running')
 
     # Deprecated
@@ -678,5 +681,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -693,5 +696,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -730,5 +733,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -745,5 +748,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -761,5 +764,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -777,5 +780,5 @@
         with self.lock:
             res = self.client.request(cmd)
-            success = str(json.loads(res)['Success'])
+            success = str(json.loads(res)['Success']).lower()
             if success == 'false':
                 return False
@@ -1082,6 +1085,5 @@
 
         except Exception as e:
-            print(f'Error reading image: {str(e)}')
-            return np.zeros((480, 640, 3), dtype=np.uint8)
+            raise RuntimeError(f'Failed to read {viewmode} image from camera {cam_id}') from e
 
     def _decode_npy(self, res):
--- a/simworld/simworld/local_planner/local_planner.py
+++ b/simworld/simworld/local_planner/local_planner.py
@@ -221,5 +221,5 @@
                     action_str += f'I chose to step backward for {vlm_action.duration} seconds.'
 
-                _human_collision, _object_collision, _building_collision = self.communicator.get_collision_number(self.agent.id)
+                _human_collision, _object_collision, _building_collision, _vehicle_collision = self.communicator.get_collision_number(self.agent.id)
                 if _human_collision > 0 or _object_collision > 0 or _building_collision > 0:
                     action_str += 'But I have collided with something.'
--- a/simworld/simworld/communicator/communicator.py
+++ b/simworld/simworld/communicator/communicator.py
@@ -887,5 +887,6 @@
 
         # Get all objects in the environment
-        objects = [obj.lower() for obj in self.unrealcv.get_objects()]  # Convert objects to lowercase
+        original_names = list(self.unrealcv.get_objects())
+        objects = [obj.lower() for obj in original_names]  # Lowercase only for matching
         # Define unwanted objects
         if keep_roads:
@@ -900,5 +901,5 @@
         if indexes is not None:
             for index in indexes:
-                self.unrealcv.destroy(objects[index])
+                self.unrealcv.destroy(original_names[index])
 
         self.unrealcv.clean_garbage()
```

## From the SimWorld Mac server session (2026-11-06): stop NPCs on close

Found on the real Mac server (`mac_server/`, packaged, port 9001). `SimWorldPhysics.close()` resumes the game but leaves
NPCs walking: `npc_forward` has no end, so pedestrians walk in a straight line indefinitely, leave the map and fall.
About 25 minutes later UE 5.8 asserted in `FSceneCullingBuilder::ProcessPostSceneUpdate` (`UploadDataProxy == nullptr`)
and the server died, three times, including once with no client connected. Measured: one NPC moved 132 m in 20 s after
close, then reached 508 m south. Proposed: in `close()`, before `resume()`, send `npc_stop` for every NPC spec and
`stop_agent` for the agent. `kokopelli/agents/live.py` does this itself for now (`Life.halt`), and after it nobody moved
in 40 s.

## Ask from the sensations work (2026-11-10): `WorldModelLife.__init__` logs before the clock exists

Not applied. `kokopelli/agents/live_wm.py` belongs to the Sim-Transfer area; it's written here because this file is where asks about the loop go.

`Life.log` (`kokopelli/agents/live.py:246`) reads `self.sim_t`, which only `Life.run` sets (`live.py:479`). `WorldModelLife.__init__` calls `self.log("world_model", ...)` at `kokopelli/agents/live_wm.py:104`, before `run`. Read from the code, not run: `live_wm.main` builds a plain `WorldModelLife(args)`, so that line should raise `AttributeError: ... no attribute 'sim_t'` once the world-model worker has started. `lunch_wm.py` sets its own clock in `__init__` (line 97) and isn't affected.

`kokopelli/agents/egg_wm.py` works around it by setting `self.sim_t = 0.0` before `super().__init__(args)`. The fix on your side is one line, `self.sim_t = 0.0` at the top of `Life.__init__` (`live.py:216`), after which the workaround in `egg_wm.py` can go. Still the case on `main` at 6d6e339.

## Ask from the sensations work (2026-11-10): `visible` should be what was painted, not what the sim holds

Not applied. This is the patch for the known gap in `kokopelli/mind/OPEN_DECISIONS.md` ("`visible` comes from the sim, not from what the world model drew"). It uses `kokopelli/wm/seen.py` (branch `sens/seen`; the loop may import `wm`).

What it does: `Loop._decide` no longer hands `self.visible` (every NPC and present object the sim holds) to the prompt, the agent and `parse_decision`. It first asks `seen()` which of them a detector finds in the newest painted frame, and uses that shorter list. The sim proposes, the picture decides; the detector can only drop ids, never add one. Each check is logged as a `seen` event (`frame`, `sim_visible`, `kept` with boxes and scores). Behind `Config.seen`, off by default, so nothing changes until you turn it on.

How it was checked: applied in the `sens/seen` worktree on 2026-11-10, `tools/fable/test_all.sh tests/loop tests/mind` gave 145 passed (the two new tests below included; they use a fake detector) and py310 197 passed; ruff 0.11.4, pyright and lint-imports clean; then reverted. It has not run with a real detector or a real world model.

Things to decide before turning it on:

- **Labels.** A detector needs words. The patch looks for "a person" for any NPC id and the id with spaces for an object ("bread_basket" becomes "bread basket"), with `Config.seen_labels` to override per id. The sim's object `kind` would be a better default, but `SimStep.state` puts "held by X" in the same field.
- **Who is who.** The candidates carry no box, so two NPCs and one painted person confirms whichever comes first in `visible`. `seen.Candidate` takes a `box`; filling it from `Capture.seg` (the actor's mask) or from the pose and camera would fix that, and would also stop a stranger Cosmos painted from confirming a sim person who is off screen. Whether that matters in practice is what the evaluation in `docs/log/sensations/2026-11-11-seen.md` measures.
- **Other paths that still read the sim.** `outcome_text(self.pending, self.visible, step.visible, ...)` in `tick` and the saved `visible` in the checkpoint still use the sim's list, on purpose: the patch only changes what the agent is told and may act on. `kokopelli/mind/feeling.py` reads `agent_input.visible`, so it gets the painted list with no change.
- **A forced `wait`.** If the agent names something the detector dropped, `parse_decision` rejects it with "isn't something you can see", which is the intended behaviour, and after two tries the turn is lost as today.
- **Memory.** The detector lives in a worker process under `simworld/.venv` (torch) from the first check to the end of the run. `seen_wm.release()` after the call gives it back at the cost of a reload each tick.
- **The mock world model.** Its frames are drawings a detector finds nothing in, so `seen=True` with `wm="mock"` drops everything. The tests below patch the detector.

```diff
diff --git a/kokopelli/loop/config.py b/kokopelli/loop/config.py
index d5ea5f7..89f4550 100644
--- a/kokopelli/loop/config.py
+++ b/kokopelli/loop/config.py
@@ -44,6 +44,11 @@ class Config:
     agent_frames: int = 6
     notes_shown: int = 5
     counterfactual: bool = True
+    # Tell the agent only about things a detector finds in the newest painted frame (kokopelli/wm/seen.py). Off by
+    # default: the mock world model paints nothing a detector could find. seen_labels maps a sim id to the words to
+    # look for; a person not named there is "a person", a thing is its id with spaces.
+    seen: bool = False
+    seen_labels: dict = field(default_factory=dict)
 
     wm_preset: str = "mock"
     wm_style: str = "A steady view of the scene, natural light, continuous motion."
diff --git a/kokopelli/loop/loop.py b/kokopelli/loop/loop.py
index 7979132..4027515 100644
--- a/kokopelli/loop/loop.py
+++ b/kokopelli/loop/loop.py
@@ -11,6 +11,7 @@ from kokopelli.loop.leak_guard import LeakError, drop_future
 from kokopelli.loop.memory import MemorySampler
 from kokopelli.loop.notebook import latest, remember, write_bundle
 from kokopelli.loop.prompt_builder import build_agent_prompt, build_wm_prompt, outcome_text
+from kokopelli.wm import seen as seen_wm
 
 
 def text_hash(text):
@@ -28,6 +29,7 @@ class Loop:
         self.cond = []
         self.since_anchor = 0
         self.visible = []
+        self.people = set()
         self.outcome = None
         self.memory = MemorySampler().start()
 
@@ -39,7 +41,7 @@ class Loop:
         first = self.sim.reset(self.config.seed, start, self.out, self.config.capture_offsets)
         # Real video can't start from the mock sim's grid drawing, so it starts from the prompt alone.
         self.cond = [] if self.config.text_start or self.config.wm_filter else [CondFrame(first.captures[0].rgb, "sim")]
-        self.visible = first.visible
+        self.visible, self.people = first.visible, set(first.state.get("npcs", ()))
         self.log.append("sim_reset", 0, {"state": first.state, "capture": self._capture_data(first.captures[0]), "visible": first.visible})
 
     def resume(self, saved):
@@ -74,7 +76,7 @@ class Loop:
         memory["sim"] = self.memory.take()
         now = step.state["sim_time"]
         self.outcome = outcome_text(self.pending, self.visible, step.visible, step.state.get("last_result")) if tick > 1 else None
-        self.visible = step.visible
+        self.visible, self.people = step.visible, set(step.state.get("npcs", ()))
         self.log.append("sim_step", tick, {"state": step.state, "captures": [self._capture_data(c) for c in self._logged_captures(step)],
                                            "visible": step.visible, "seconds": step.seconds})
 
@@ -200,19 +202,33 @@ class Loop:
             self.log.append("reanchor", tick, {"offset_s": offset, "reason": reason, "frame": self._rel(frame),
                                                "replaced": "oldest", "cond": [self._cond_data(item) for item in self.cond]})
 
+    def _painted(self, tick, images):
+        """The sim's visible list, cut down to what a detector finds in the newest painted frame. The sim proposes, the
+        picture decides: an id the frame doesn't show is not something the agent can see, name or act on this tick."""
+        if not self.config.seen or not images or not self.visible:
+            return self.visible
+        labels = self.config.seen_labels
+        asked = [seen_wm.Candidate(name, labels.get(name, "a person" if name in self.people else name.replace("_", " ")))
+                 for name in self.visible]
+        kept = seen_wm.seen(images[-1], asked)
+        self.log.append("seen", tick, {"frame": self._rel(images[-1]), "sim_visible": list(self.visible),
+                                      "kept": [{"id": s.id, "label": s.label, "box": list(s.box), "score": s.score} for s in kept]})
+        return [s.id for s in kept]
+
     def _decide(self, tick, now, context, images):
+        visible = self._painted(tick, images)
         notes, _ = drop_future(self.notes, now)
         notes = latest(notes, self.config.notes_shown)
-        prompt, _ = self._guarded(tick, now, build_agent_prompt, context, notes, self.visible, len(images), now, self.outcome)
+        prompt, _ = self._guarded(tick, now, build_agent_prompt, context, notes, visible, len(images), now, self.outcome)
         self.log.append("agent_input", tick, {"prompt": prompt, "hash": text_hash(prompt), "images": [self._rel(p) for p in images],
                                               "image_hashes": [file_hash(p) for p in images], "notes": notes, "leak_check": "passed"})
         error, forced = None, False
         for attempt in (1, 2):
             clock = time.perf_counter()
-            raw = self.agent.decide(AgentInput(prompt, images, self.visible, now, tick, error))
+            raw = self.agent.decide(AgentInput(prompt, images, visible, now, tick, error))
             latency = round(time.perf_counter() - clock, 4)
             try:
-                decision = parse_decision(raw, self.visible)
+                decision = parse_decision(raw, visible)
                 self.log.append("agent_output", tick, {"attempt": attempt, "raw": raw, "valid": True, "reshaped": was_reshaped(raw), "seconds": latency})
                 break
             except InvalidDecision as invalid:
@@ -220,7 +236,7 @@ class Loop:
                 self.log.append("agent_output", tick, {"attempt": attempt, "raw": raw, "valid": False, "error": error, "seconds": latency})
         else:
             # Two bad replies. The agent loses its turn rather than the run stopping.
-            decision, forced = parse_decision('{"action": {"type": "wait"}}', self.visible), True
+            decision, forced = parse_decision('{"action": {"type": "wait"}}', visible), True
             self.log.append("agent_fallback", tick, {"action": "wait", "reason": error})
         if decision.diary:
             write_bundle(self.out / "memory", remember(self.notes, now, decision.diary))
diff --git a/tests/loop/test_seen_visible.py b/tests/loop/test_seen_visible.py
new file mode 100644
index 0000000..b0b8b9f
--- /dev/null
+++ b/tests/loop/test_seen_visible.py
@@ -0,0 +1,48 @@
+"""The loop's visible list filtered by kokopelli/wm/seen.py, on the mock loop with a fake detector (no model)."""
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest import mock
+
+from kokopelli.loop.config import Config
+from kokopelli.loop.run import run
+from kokopelli.wm import seen as seen_wm
+
+
+class OnlyTheBench:
+    """A fake detector: whatever is asked, it finds a bench and nothing else."""
+
+    def detect(self, frame, labels):
+        return [seen_wm.Detection("bench", (10.0, 10.0, 60.0, 40.0), 0.9)] if "bench" in labels else []
+
+
+def prompts(out):
+    events = [json.loads(line) for line in (Path(out) / "events.jsonl").read_text().splitlines()]
+    return [e["data"]["prompt"] for e in events if e["kind"] == "agent_input"], [e for e in events if e["kind"] == "seen"]
+
+
+class SeenVisibleTest(unittest.TestCase):
+    def setUp(self):
+        patch = mock.patch.object(seen_wm, "default_detector", lambda: OnlyTheBench())
+        patch.start()
+        self.addCleanup(patch.stop)
+
+    def test_off_by_default_the_agent_is_told_everything_the_sim_holds(self):
+        out = tempfile.mkdtemp(prefix="wmloop_")
+        run(Config(ticks=2, counterfactual=False), out)
+        told, seen_events = prompts(out)
+        self.assertEqual(seen_events, [])
+        self.assertTrue(all("bench" in p and "ball" in p for p in told))
+
+    def test_on_the_agent_is_told_only_what_the_detector_found(self):
+        out = tempfile.mkdtemp(prefix="wmloop_")
+        run(Config(ticks=2, counterfactual=False, seen=True), out)
+        told, seen_events = prompts(out)
+        self.assertEqual(len(seen_events), 2)
+        self.assertTrue(all("You can see: bench." in p for p in told))
+        self.assertTrue(all([k["id"] for k in e["data"]["kept"]] == ["bench"] and len(e["data"]["sim_visible"]) > 1 for e in seen_events))
+
+
+if __name__ == "__main__":
+    unittest.main()
```
