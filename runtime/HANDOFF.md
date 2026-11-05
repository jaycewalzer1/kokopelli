# Handoff

From the SimWorld overnight session to the main session and the owner. Nothing here is applied. These are all in files I was told not to edit.

## For the main session: how to use this

Import from `runtime/physics.py`, which only needs pydantic, so it works from the root `.venv`:

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
- `SimWorldPhysics` needs `unrealcv==1.3.2`, numpy and pillow, so it won't import from the root `.venv`. Import it lazily, or run the loop's physics side from the venv made by `scripts/pace/setup_client.sh`.

I did not create `runtime/interfaces.py`, `runtime/loop.py`, `runtime/run.py` or mocks.

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
	simworld/.venv/bin/python -W ignore -m unittest discover -s runtime/tests -t . -p 'test_simworld*.py'
```

## Proposed: `README.md`

Add a row to the file table:

```
| `runtime/` | The world-model loop. `runtime/SIMWORLD.md` covers the physics side |
```

## Proposed: `requirements.txt`

No change. The root `.venv` already has pydantic through `mlx-vlm`. If the loop is ever meant to import `runtime/physics.py` on a machine without it, add `pydantic>=2`. The SimWorld client's packages are in `scripts/pace/setup_client.sh`, deliberately separate, since this Mac doesn't run Unreal.

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
