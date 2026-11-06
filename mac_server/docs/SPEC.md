# SimWorld macOS UE5 server: protocol and behavior spec

Status: authoritative for `~/Desktop/kokopelli/mac_server`. Derived from reading
the client only:

- `simworld/simworld/communicator/unrealcv.py` and `communicator.py`
- every caller: `agent/`, `traffic/`, `local_planner/`, `weather/`, `utils/video_recorder.py`, `examples/*.ipynb`, `config/*.yaml`, `data/*.json`
- the `unrealcv` 1.3.2 package in `simworld/.venv` (`__init__.py`, the wire client)

The original Windows/Linux server source is not public. Where the client does not
pin a behavior down, this spec makes a choice and marks it **[choice]**. Where
the client has a bug or quirk the server has to work around, it is marked
**[quirk]**. Requirement words: MUST = the unchanged client breaks without it;
SHOULD = recommended, tested under the `should` marker.

Conformance tests: `tests/test_conformance.py`. Each test docstring cites the
section it checks.

---

## 0. Conventions

| Item | Value |
|---|---|
| Length unit | centimetres (UE units). Speeds are cm/s (`SetMaxSpeed 200` = 2 m/s). |
| Angles | degrees |
| Rotation tuple order on the wire | **pitch yaw roll**, for both `vset` and `vget` on objects and cameras |
| Axes | UE left-handed, Z up. Yaw 0 faces +X; yaw +90 faces +Y. Seen from above, positive yaw is clockwise, so "right" means +yaw. The client turns yaw into a heading with `(cos yaw, sin yaw)`. |
| Ground | z = 0. The client spawns humanoids at z=600, pedestrians at z=110, vehicles, scooters and signals at z=0, and city nodes at their JSON z (0 or 20). |
| Default port | 9000 on 127.0.0.1. `TrafficController.init_communicator()` hard-codes 9000. |
| Python numbers | Arguments are built with f-strings, so a token can be `1`, `0.4`, `-90.0`, `1e-05` or `-2.5E+02` (numpy types print the same way). The server MUST parse all of these, scientific notation included. |
| Python bools | Sent as `True`/`False`. The server MUST accept `True/False/true/false/1/0`. |

---

## 1. Wire protocol (byte level)

### 1.1 Framing
TCP stream (AF_INET; the client sets TCP_NODELAY). Every message in both directions is one frame:

```
offset size  field
0      4     magic        uint32 little-endian = 0x9E2B83C1  -> bytes C1 83 2B 9E
4      4     payload_size uint32 little-endian
8      N     payload      N = payload_size bytes
```
(The client uses `struct.pack('I')`, which is native order. On every Mac it is
little-endian.) There is no CRC. The server MUST cope with frames split across
TCP reads and with several frames arriving in one read.

If the magic is wrong, the client prints an error, retries the read up to 10
times with backoff (0.5 s up to 8 s), then raises `ConnectionError`. A desync
therefore costs about 30 s and then a dead client.

### 1.2 Handshake
After `accept()`, the server MUST send one frame **before reading anything**,
with a payload that starts with the bytes `connected`. UnrealCV sends
`connected to <ProjectName>`. If the first frame does not start with
`connected`, `Client.connect()` returns False. simworld's `UnrealCV.__init__`
then loops forever (`check_connection` sleeps 1 s and retries with no limit).

### 1.3 Request and reply payloads
- Request payload: `<id>:<command>` with `<id>` as ASCII decimal and the command in UTF-8, e.g. `12:vget /objects`.
- Reply payload: `<same id>:<body>`. The body is UTF-8 text or raw binary (PNG, BMP, NPY).
- The server MUST echo the id **verbatim** and MUST NOT assume ids start at 0 or are contiguous. The client keeps counting ids across reconnects of the same `Client` object.
- The client parses a reply with `rb'(\d{1,}):(.*)'` and takes the body as `raw[len(id)+1:]`. It then tries `body.decode('utf-8')`: on success the caller gets a `str`, on failure it gets `bytes`.
- If the reply id differs from the id the client expects, the client's receive thread raises `AssertionError` and dies. After that, `request()` times out after 15 s and `request_batch()` **hangs forever**.

### 1.4 Ordering, pipelining, async
- Replies MUST come back in request order, exactly one per request, **including requests sent "async"**. `request(cmd, -1)` (used for `vrun setres` and `vrun Editor.AsyncSkinnedAssetCompilation 2`) still queues one reply to read and throw away. A missing reply shifts every later reply by one, which triggers the id assertion in 1.3.
- `request_batch([...])` (used by `get_location_batch` and `get_orientation_batch`) sends all frames first and then reads N replies. The server MUST handle pipelined requests and process them in order.
- Errors are ordinary replies (section 2.5). Never drop a request.

### 1.5 Binary bodies
- PNG bytes start with `0x89` and NPY bytes with `0x93`, so neither can be valid UTF-8 and both always reach the caller as `bytes`.
- **[quirk]** BMP starts with `BM`. A BMP whose bytes are all below 0x80 (for example an all-black frame) decodes as UTF-8. The caller then gets a `str`, `_decode_bmp` raises `TypeError`, and `get_image` silently returns `zeros(480,640,3)`. The server SHOULD make sure every BMP reply contains at least one byte ≥ 0x80. A cheap way: set a reserved header field (bytes 6–9) to `0x80`.

### 1.6 Connections
- The client has the comment "Currently only one client is allowed at a time". The server MUST serve at least one client. A second concurrent connection MUST NOT disturb the first. **[choice]** Close it without a handshake, as UnrealCV does.
- After a client disconnects, the server MUST accept a new client. Notebooks reconnect often.
- Client timeouts: `request()` defaults to 15 s per request. `request_batch()` has no timeout.

### 1.7 Capability probe (`vget /unrealcv/commands`)
The first time a `Client` connects, it immediately sends `vget /unrealcv/commands`, so it holds request id 0 and user commands start at id 1. The server SHOULD reply with newline-separated **command templates**:
- The list must contain the literal line `vget /unrealcv/commands`, otherwise the client ignores it.
- A placeholder is anything in `[...]`, and it matches exactly one whitespace-free token (`\S*`). Matching is a full match after whitespace is collapsed, so **variable-arity commands need one template per arity**. Example: `vbp [str] [str]`, `vbp [str] [str] [str]`, … up to 8 extra args. `SetDuration` takes 3 args; nothing simworld sends takes more than 3.
- If a command matches no template, the client issues `UserWarning: server may not support command` and still sends it. If the probe reply starts with `error`, the client warns once ("too old") and skips all checks. Neither case is fatal. The full template list is in `tests/mock_server.py:TEMPLATES`.

### 1.8 Throughput
`Communicator.generate_world` sends 7 requests per node (spawn, color, location, rotation, scale, collision, mobility), strictly one after another. demo_city_1 has 638 nodes, about 4.5k round trips. The traffic loop sends one `VSetState` plus one `GetInformation` per 0.1–0.2 s tick. The server SHOULD process **all queued commands each frame** rather than one command per frame, and handle ≥ 200 small requests per second. Replies to `vbp` motion commands MUST come back without waiting for the motion to finish (section 7).

---

## 2. Generic object and engine commands

Reply conventions: `vset` replies `ok` on success **[choice]**; the client
ignores every `vset` body. Numbers in `vget` replies are `%.3f`, separated by
single spaces. Object names never contain whitespace.

### 2.1 Console
| Command | Reply | Notes |
|---|---|---|
| `vrun setres {W}x{H}w` | any (e.g. `ok`) | Sent async from `UnrealCV.__init__`. Sets the window size. Default (1280,720); TrafficController uses (720,600). |
| `vrun Editor.AsyncSkinnedAssetCompilation 2` | any | Sent async, followed by `sleep(1)`. May be a no-op. |
| `vrun <anything>` | any | MUST reply. |

### 2.2 Listing
`vget /objects` returns `name1 name2 …`, space-separated. The client does
`np.array(res.split())`.
- MUST list every spawned actor under the name it was given (original spelling).
- MUST never be empty. **[quirk]** `clear_env` calls `np.char.startswith` on the list, which raises `UFuncNoLoopError` when the list is empty (verified). The level MUST keep at least one permanent actor, e.g. `Floor`.
- After `GetOffScooter`, the rider re-appears as an actor whose name contains `Base_User_Agent_C_` (section 6.5).

### 2.3 Spawn, rename, destroy (name lookup is case-insensitive)
| Command | Reply |
|---|---|
| `vset /objects/spawn_bp_asset {/Game/...Class_C} {name}` | Spawned name, or `error …` if the class can't load or the name is taken. **[choice]** |
| `vset /objects/spawn {class} {name}` | Deprecated alias. Same reply. |
| `vset /object/{name}/name {new}` | `ok`. Rename in place, keeping transform and state. |
| `vset /object/{name}/destroy` | `ok` |
| `vset /action/clean_garbage` | `ok`. Runs GC. After it returns, destroyed actors MUST be gone from `/objects`. |

- **[quirk] MUST: name lookup is case-insensitive.** `Communicator.clear_env` lowercases every name from `/objects` and then sends `vset /object/<lowercased>/destroy`. UE `FName` comparison is case-insensitive, so this is natural if lookups go through FName. A plain `FString ==` breaks it.
- A spawn has no transform. The client always follows it with location, rotation, scale, collision and mobility. The spawn origin **[choice]** is (0,0,0).
- Spawning an existing name MUST NOT create a second actor with that name. **[choice]** Reply `error`.

### 2.4 Transform and flags
| Command | Reply / effect |
|---|---|
| `vset /object/{n}/location {x} {y} {z}` | Teleport (no sweep). For characters, the capsule is placed there and then falls. |
| `vget /object/{n}/location` | `"x y z"`. The client does `[float(i) for i in res.split()]`. |
| `vset /object/{n}/rotation {pitch} {yaw} {roll}` | |
| `vget /object/{n}/rotation` | `"pitch yaw roll"`. The client reads yaw as index 1. Any yaw range works because callers normalise. |
| `vset /object/{n}/scale {x} {y} {z}` / `vget …/scale` | `"x y z"`. vget is not used by simworld; SHOULD, tested. |
| `vset /object/{n}/color {R} {G} {B}` | 0–255 ints. Sets the **object_mask** colour (section 3.4). |
| `vget /object/{n}/color` | `(R=r,G=g,B=b,A=255)`. SHOULD, tested by M1. |
| `vset /object/{n}/collision {bool}` | Enable or disable collision. |
| `vset /object/{n}/physics {bool}` | Simulate physics. |
| `vset /object/{n}/object_mobility {bool}` | True = Movable, False = Static. Static actors MUST still accept later `vset location`, because the server can switch them to movable on demand. |
| `vbp {n} EnableController {bool}` | Possess or spawn the AI controller (robot dog). |
| `vget /object/{n}/uclass_name` | Optional. |

### 2.5 Errors and how the client reacts
Errors are reply bodies that start with lowercase `error` (e.g. `error Can not find object X`).

| Call | On an error reply |
|---|---|
| any `vset`, void `vbp` | silently ignored |
| `get_location`, `get_orientation`, `*_batch` | `float('error')` raises `ValueError`, which the caller does not catch |
| `get_image` (all modes) | caught; prints `Error reading image` and returns `zeros(480,640,3)` |
| SitDown, StandUp, PickUp, DropOff, EnterVehicle, ExitVehicle | `json.loads` raises `JSONDecodeError`, which propagates |
| `get_collision_number` | `JSONDecodeError` propagates |
| `get_position_and_direction` (GetInformation) | raises. `TrafficController.simulation` catches it, logs it and stops the simulation. The local-planner update thread dies. |
| weather getters | caught; return `None` or `0.0` |
| camera getters | the raw string is returned to the caller |

### 2.6 Time control
| Command | Effect |
|---|---|
| `vset /action/game/pause` | Pause the world (sync mode). |
| `vset /action/game/resume` | Resume (async mode). |
| `vset /action/tick_intervel {dt}` | **[quirk] the typo "intervel" is literal.** Seconds simulated per `tick`. |
| `vset /action/tick` | While paused, advance exactly one frame of `dt` and render it before replying. `VideoRecorder` calls it after every capture. |
| `vset /action/set_fixed_frame_rate {fps}` | Fixed-timestep rendering. |
| `vget /action/game/is_paused` | `true`/`false` (optional). |

---

## 3. Cameras

### 3.1 Indexing
- `vget /cameras` returns camera names, space-separated. The client only prints it; the tests count the tokens.
- Camera **0** is the level/player camera and always exists.
- **MUST:** every actor spawned from a camera-owning prefab adds exactly one camera, numbered in spawn order. Camera-owning prefabs are `Base_User_Agent_C`, `BP_SpotRobot_C` and **[choice]** `BP_Default_Character_C`. The client relies on `Humanoid.camera_id = humanoid.id + 1`: the first humanoid uses camera 1, the second camera 2, and so on.
- **[choice]** When an owner is destroyed, its camera disappears and the higher indices shift down, as in UnrealCV, which rebuilds the sensor list from the world. **[quirk]** `clear_env` resets `Humanoid._id_counter` but not `Humanoid._camera_id_counter`. A process that clears and respawns therefore asks for a camera id past the end. The client cannot avoid this; the tests reset both counters.
- An agent camera is attached to its owner at eye height and looks along the owner's yaw. It moves with the owner unless `vset /camera/N/location|rotation` overrides it.

### 3.2 Parameters and capture
| Command | Reply |
|---|---|
| `vget /camera/{i}/location` | `"x y z"` |
| `vget /camera/{i}/rotation` | `"pitch yaw roll"`. A docstring says "(yaw, pitch, roll)", but the setter is pitch/yaw/roll and UnrealCV returns pitch/yaw/roll, so use that. |
| `vget /camera/{i}/fov` | `"90.000"` (horizontal degrees) |
| `vget /camera/{i}/size` | `"W H"` (ints) |
| `vset /camera/{i}/location x y z`, `/rotation p y r`, `/fov f`, `/size W H` | `ok`. `size` sets the capture resolution; `VideoRecorder` uses 1440×720. |
| `vget /camera/{i}/{mode} png` | PNG bytes. **MUST be 8-bit RGBA** (colour type 6). `_decode_png` drops the last channel and flips RGB to BGR, so an RGB PNG would silently lose its blue channel. |
| `vget /camera/{i}/{mode} bmp` | BMP bytes ("fast" mode), 24 or 32 bpp, bottom-up or top-down, rows padded to 4 bytes. Must contain a byte ≥ 0x80 (section 1.5). |
| `vget /camera/{i}/depth npy` | `.npy` bytes (section 3.3) |
| `vget /camera/{i}/{mode} {filename}` | Write the image to `filename` (an absolute path on the same machine) and reply with the path. The client then does `cv2.imread(reply)`. Use PNG encoding. |

`mode` ∈ `lit`, `depth`, `object_mask` (+ `normal` optional). Unknown camera →
`error`. Captures MUST finish well inside 15 s at 1920×1080.

### 3.3 Depth
`npy` holds a float32 (or float16/64) array of shape (H, W): per-pixel
**distance in cm** (UnrealCV's convention is the distance to the camera plane).
Values MUST be finite and > 0; sky can be clamped to a large value such as
1e6. The client computes `log(d+1e-6)` and normalises by `max−min`, so an
exactly constant image produces NaN and a garbage colormap. Only the `npy`
format is used for depth.

### 3.4 Object mask
`vget /camera/{i}/object_mask png` returns an unlit image in which every pixel
of an actor equals that actor's `vset /object/X/color` RGB exactly (no AA, no
tonemapping). `generate_world(run_time=True)` colours city nodes by class from
`ue_assets.json["colors"]`: BUILDING (128,0,128), VEGETATION (0,128,0),
SCOOTER (0,0,255), STREET_FURNITURE (255,255,0), FURNITURE (255,0,0),
TRASH (128,128,128), BOX and CAN (255,165,0), TABLE (255,100,0),
ROAD_BLOCKER (255,200,0). **[choice]** Actors with no colour get a stable
per-actor colour; the background is black.

---

## 4. Prefab catalog (`/Game/...` paths the client can spawn)

Every path below MUST load with `vset /objects/spawn_bp_asset`. M1 allows
placeholder meshes; the exposed `vbp` functions arrive in M2–M5.

### 4.1 City (spawned by `generate_world`, static)
All live under `/Game/CityDatabase/blueprints/<N>.<N>_C`. The full list is
`data/ue_assets.json` (161 paths). Group = colour class:

| Group | Assets | Notes |
|---|---|---|
| BUILDING (123) | `BP_Building_01..126` except 57, 64 and 120 are absent from ue_assets | **[quirk]** demo_city_1 uses `BP_Building_64_C`, but ue_assets.json lacks it, so the client logs "Can't find node" and skips it. The server SHOULD still ship `BP_Building_64` (and 57, 120) so a fixed asset file works. The footprint is in `data/bounding_boxes.json`. |
| VEGETATION | BP_Tree1..6 | |
| STREET_FURNITURE | BP_Hydrant, BP_RoadCone, RoadCone, **BP_Road, BP_Road1** | Roads are nodes `GEN_Road_<n>` (instance BP_Road1_C) with scale ~(0.95,0.9,1). They are placed at the midpoint of each road segment; segment length is 200 layout units = 20000 cm. |
| FURNITURE | BP_Couch, Couch, BP_Cart, BP_Cart2 | |
| TABLE | BP_Table, BP_Table2, BP_Table3, Table | |
| ROAD_BLOCKER | BP_RoadBlocker, RoadBlocker | |
| TRASH | BP_Rabbish, BP_Trash_bin_a/b, BP_Trash_can | |
| BOX | BP_Box, BP_Box2, BP_Box3 | |
| CAN | BP_Can, BP_Can2, BP_Soda1..4 | |
| SCOOTER (decor) | BP_Scooter_01..04 | Static props, not the rideable pawn. |

Bounding boxes in `data/bounding_boxes.json` (`buildings`, `elements`) give the
footprint each mesh must roughly have. Placeholders SHOULD be boxes of that size
so that layouts don't overlap.

### 4.2 Dynamic and functional prefabs
| Kind | Path | Spawned by / name | vbp surface (section 6) |
|---|---|---|---|
| UE manager | `/Game/TrafficSystem/UE_Manager.UE_Manager_C` | `spawn_ue_manager`, name **`GEN_BP_UEManager`** | GetInformation, UpdateObjects, VSetState, PSetState (6.6) |
| Humanoid agent | `/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C` | `spawn_agent`, `GEN_BP_Humanoid_<id>`, z=600; owns a camera | 6.1 |
| Humanoid alt. avatar | `/Game/Human_Avatar/DefaultCharacter/Blueprint/BP_Default_Character.BP_Default_Character_C` | ue_command.ipynb; same surface as Base_User_Agent | 6.1 |
| Pedestrian (NPC) | `/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C` | `spawn_pedestrians`, `GEN_BP_Pedestrian_<id>`, z=110 | 6.3 |
| Vehicles | `/Game/TrafficSystem/Vehicle/Vehicle{1..5}.Vehicle{1..5}_C` | `spawn_vehicles`, `GEN_BP_Vehicle_<id>`, z=0. Length 480–500 cm, width 200 cm (`vehicle_types.json`) | 6.2 |
| Traffic light (vehicle+ped) | `/Game/city_props/BP/props/street_light/BP_street_light.BP_street_light_C` | `GEN_BP_TrafficSignal_<id>`, type `both`, movable False | 6.4 |
| Pedestrian light | `/Game/city_props/BP/props/street_light/BP_street_light_ped.BP_street_light_ped_C` | same naming, type `pedestrian` | 6.4 |
| Intersection controller | **unknown path** (`spawn_intersection(name, model_path)` has no caller) | AddVehicleSignal, AddPedSignal, StartSimulation | 6.4 |
| Rideable scooter | `/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn.BP_Scooter_Pawn_C` | `spawn_scooter`, `GEN_BP_Scooter_<id>`, z=0 | 6.5 |
| Weather manager | `/Game/Weather/BP_WeatherManager.BP_WeatherManager_C` | `WeatherManager.spawn`, name **`GEN_WeatherManager`** | 6.7 |
| Robot dog | `/Game/Robot_Dog/Blueprint/BP_SpotRobot.BP_SpotRobot_C` | notebooks, e.g. `Demo_Robot`; owns a camera | 6.9 |
| Light pickup | `/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C` | `spawn_object`, e.g. `BP_Mug_C_1` | target of PickUp (6.8) |
| Heavy pickup | `/Game/InteractableAsset/Box/BP_Interactable_Box.BP_Interactable_Box_C` | e.g. `GEN_BP_Box_1_C` | target of PickUp (6.8) |
| Enterable car | `/Game/Interactable_Vehicle/Blueprint/BP_VehicleBase_Destruction.BP_VehicleBase_Destruction_C` | e.g. `BP_VehicleBase_Destruction_C_1` | target of Enter/ExitVehicle (6.8) |
| Waypoint mark | **unknown path** (`spawn_waypoint_mark(waypoints, model_path)` has no caller) | `GEN_BP_WaypointMark_<n>`, z=30, collision off | none |
| AssetsRP output | `BP_GEN_<asset>_<idx>` ids in JSON for `generate_world` | — | none |

Maps mentioned: `/Game/Maps/demo_1.umap` and `demo_2.umap` go with
`data/example_city/demo_city_{1,2}` (pre-built cities); `/Game/hospital/map/demo.umap`.
**[choice]** The Mac server boots into an empty flat level (ground plane at z=0,
sky, sun). The client then builds the city with `generate_world`.

---

## 5. Composite client flows (the order the server sees)

### 5.1 `Communicator.spawn_object(name, path, (x,y,z), (p,y,r))`
`spawn_bp_asset` → `location` → `rotation` → `scale 1 1 1` → `collision True` → `object_mobility True`.
`spawn_agent`, `spawn_vehicles` and `spawn_pedestrians` follow the same order. Signals and
waypoint marks send `object_mobility False`.

### 5.2 `generate_world(progen_world.json, ue_assets.json, run_time)`
For each node in order: `spawn_bp_asset <asset_path> <node id>` → (`color R G B` if
run_time) → `location` → `rotation` → `scale` → `collision True` → `object_mobility False`.
Node ids look like `GEN_Road_0`, `GEN_BP_Building_64_C_55` and `GEN_BP_Tree5_3_637`.
Locations are already in cm (layout ×100). JSON numbers arrive as `10000.0` or `0`.

### 5.3 `clear_env(keep_roads)`
`vget /objects` → destroy each name that starts (case-insensitively) with `GEN_BP_`
(and `GEN_Road_` unless keep_roads), **sent lower-cased** → `clean_garbage`.
`clean_traffic_only` destroys vehicles, signals, pedestrians and `GEN_BP_UEManager`, then runs `clean_garbage`.

### 5.4 Traffic simulation (`TrafficController`)
spawn vehicles → spawn pedestrians → spawn signals → `spawn_ue_manager` (after
the traffic actors) → loop:
`SetMaxSpeed` for every pedestrian, `SetDuration` for every light (once), then every `dt` (0.1–0.2 s):
`GetInformation` → per-vehicle `MakeUTurn` / batched `VSetState` (only changed vehicles) →
per-pedestrian `StopPedestrian` / `MoveForward` / `Rotate_Angle` →
`SwitchVehicleFrontGreen` / `SetPedestrianWalk`.
Python runs the control loop. The server only applies the controls and reports state.

### 5.5 Local planner / gym loop
`spawn_agent` → `SetMaxSpeed 200` → (`spawn_ue_manager`) → a 10 Hz thread calls `GetInformation`
while the main thread sends `MoveForward`/`StopAgent`/`TurnAround`/`StepForward`/`PickUp`
and `vget /camera/{id+1}/lit png`. One lock serialises everything on one socket.

---

## 6. Blueprint (`vbp`) surface

Generic form: `vbp {object} {Function} {arg…}`. Args are space-separated tokens;
compound args use `,` and `;` and contain no spaces. Reply: the function's
output parameters as a JSON object. **Bool and number outputs are exported as
strings** (UnrealCV's ExportText convention), e.g. `{"Success":"true"}`. A void
function replies `{}` **[choice]**; the client ignores it. An unknown object or
function replies `error …`.

### 6.1 Humanoid (`Base_User_Agent_C`, `BP_Default_Character_C`)
| Function | Args | Observable behavior (what tests check) |
|---|---|---|
| `SetMaxSpeed` | speed cm/s | Walking speed for later moves (config `user.speed`=200). |
| `MoveForward` | – | Walk along current yaw continuously until `StopAgent`. Returns immediately. |
| `StopAgent` | – | Stop moving; no drift (< 15 cm) afterwards. |
| `TurnAround` | `1 {angle} {clockwise}` | Client: right → `angle`, `1`; left → `-angle`, `-1`. Final yaw = start + signed angle, so `angle` already carries the sign. Done within the client's 1 s `sleep`. Returns immediately. |
| `StepForward` | `{duration_s} {dir}` | dir 0 forward, 1 backward. Moves ≈ speed×duration, then stops. **Must return immediately**; the client sleeps `duration`. |
| `SetPath` / `FollowPath` | `"x,y;x,y;…"` / – | Walk the polyline (cm), then stop. No caller yet; SHOULD. |
| `GetCollisionNum` | – | `{"HumanCollision":"n","ObjectCollision":"n","BuildingCollision":"n","VehicleCollision":"n"}`: cumulative hit counts since spawn. Values go through `int()`, so they must be integer strings or ints, not `"1.0"`. **[quirk]** `local_planner.navigate_vision_based` unpacks 3 of the 4 returned values and would raise `ValueError`. That is a client bug the server cannot fix. |
| `SitDown` / `StandUp` | – | `{"Success":"true"/"false"}`. **[quirk] MUST be the lower-case strings.** The client does `str(json.loads(r)['Success'])` and compares it with `'true'`/`'false'`. A JSON boolean becomes `'True'`, so the call returns `None`. SitDown succeeds when a seat (couch, chair, bench) is in reach **[choice: 150 cm]**. |
| `PickUp` | `{object}` | `Success` true if the object is a pickup (BP_Mug, BP_Interactable_Box) within reach **[choice: 200 cm]**. The object then attaches to the hand or body and moves with the agent. Otherwise false. |
| `DropOff` | – | Detach the held object at the feet. true if something was held. |
| `EnterVehicle` / `ExitVehicle` | `{vehicle}` | For BP_VehicleBase_Destruction within reach **[choice: 400 cm]**. Enter hides and attaches the agent at the seat, so its location ≈ the vehicle's. Exit places it beside the car. Success string as above. |
| `GetOnScooter` | – | Find the nearest `BP_Scooter_Pawn` within reach **[choice: 300 cm]**, **destroy the humanoid actor** and mount a rider mesh on the scooter (section 6.5). |
| `Discussion {0/1}`, `Arguing {0/1}`, `Listening`, `Wave2Dog`, `Directing` | | Play a looping gesture montage; movement is blocked. Placeholders are fine. |
| `StopAction` | – | End the current gesture. |
| (generic) `vset location/rotation` | | Teleport, then gravity applies. Characters spawned at z=600 MUST fall to ground (z ≈ capsule half-height ~ 90). |

### 6.2 Vehicle (`Vehicle1..5_C`, also the scooter)
| Function | Args | Behavior |
|---|---|---|
| `SetState` | `{throttle 0..1} {brake 0..1} {steering -1..1}` | Holds until changed. throttle 1 reaches roughly 10 m/s. brake 1 stops within about 2 s. steering ±0.5 is max from the PID (config `max_steering`). Positive steering turns toward +yaw (right). **[choice]** Steering −1 is used for U-turns. |
| `MakeUTurn` | – | Prepares a U-turn. The client then sends `SetState 0.05 0 -1` and polls `GetInformation` until the heading is within 15° of the opposite lane. The server MUST let the car turn with a radius that fits the 300 cm lane offset, e.g. by an in-place kinematic rotation while MakeUTurn mode is on. Test: \|Δyaw\| > 150° within 20 s. |

Vehicles drive on the ground at z=0. Kinematic (non-Chaos) movement is fine for M3.

### 6.3 Pedestrian (`Base_Pedestrian_C`)
| Function | Args | Behavior |
|---|---|---|
| `SetMaxSpeed` | cm/s (config 100 or 200) | |
| `MoveForward` | – | Walk along yaw until stopped. |
| `StopPedestrian` | – | Stop. |
| `Rotate_Angle` | `1 {signed angle} {±1}` | Same convention as TurnAround. Done within about 1 s. The client polls until it faces the waypoint. |
| `SetWaypoints` | `"x,y;x,y"` | Store a path (cm). |
| `MovementSimulation` | – | Autonomously walk the stored waypoints. SHOULD. |

### 6.4 Traffic signals
Light actors (`GEN_BP_TrafficSignal_<id>`):
| Function | Args | Behavior |
|---|---|---|
| `SetDuration` | `{green_s} {yellow_s} {ped_green_s}` | Config 10 / 2 / 30. |
| `SwitchVehicleFrontGreen` | – | Vehicle green for `green_s` (counting down `left_time`), then yellow for `yellow_s`, then red. Pedestrian red throughout. |
| `SetPedestrianWalk` | – | Vehicle red, pedestrian walk for `ped_green_s` (counting down), then pedestrian red. |
Intersection actor (path unknown, unused): `AddVehicleSignal {signal}`, `AddPedSignal {signal}` and `StartSimulation` would let UE drive the light cycle itself. **[choice]** Defer.

Python drives the cycle. It switches the next light to green when the current one stops reporting green. So yellow MUST report `is_vehicle_green=false`.

### 6.5 Scooter (`BP_Scooter_Pawn_C`, name `GEN_BP_Scooter_<id>`)
- `SetState {throttle} {brake} {steering}`: same as vehicles (6.2). Moves the scooter, and the rider with it while mounted.
- `GetOffScooter` (called **on the scooter**): spawn a new `Base_User_Agent_C` next to the scooter, with an engine-default name containing **`Base_User_Agent_C_`** (e.g. `Base_User_Agent_C_0`), and unmount the rider mesh.
  The client then lists `/objects`, takes the **first** name containing `Base_User_Agent_C_`, and, if `GEN_BP_Humanoid_<id>` is gone, renames it with `vset /object/…/name GEN_BP_Humanoid_<id>`. So:
  - after `GetOnScooter` + `clean_garbage`, `GEN_BP_Humanoid_<id>` MUST NOT be listed;
  - after `GetOffScooter` returns, the new agent MUST already be listed;
  - only one `Base_User_Agent_C_*` name should exist at that time.
  The new agent's camera takes the next free camera index, so the camera id can change. **[quirk]**

### 6.6 UE manager (`GEN_BP_UEManager`)
| Function | Args | Behavior |
|---|---|---|
| `GetInformation` | – | JSON object with **all nine keys** present (strings, may be empty): `VLocations, VRotations, PLocations, PRotations, LStates, ALocations, ARotations, SLocations, SRotations` (V=vehicles `GEN_BP_Vehicle_*`, P=pedestrians `GEN_BP_Pedestrian_*`, L=lights `GEN_BP_TrafficSignal_*`, A=agents `GEN_BP_Humanoid_*`, S=scooters `GEN_BP_Scooter_*`). |
| `UpdateObjects` | – | Re-scan the world for the prefixes above. **[choice]** GetInformation SHOULD always re-scan anyway, since the manager can be spawned before or after the actors. |
| `VSetState` | `"n,t,b,s;n,t,b,s"` | Same as SetState for each named vehicle. |
| `PSetState` | `"n,<state>;…"` | Batched pedestrian state. No caller in simworld; accept and ignore unknown formats. |

String formats, which the client parses with regex (non-greedy, `.` does not cross newlines):
- `*Locations`: for each actor, `{name}X={x} Y={y} Z={z}` (FVector::ToString, e.g. `X=120.000 Y=-35.500 Z=90.150`). Client regex: `{name}X=(.*?) Y=(.*?) Z=`.
- `*Rotations`: `{name}P={p} Y={yaw} R={r}` (FRotator::ToString). Client regex: `{name}P=.*? Y=(.*?) R=`.
- `LStates`: `{name}{true|false}{true|false}{left_time}`, i.e. vehicle green, then pedestrian walk, then seconds left, e.g. `GEN_BP_TrafficSignal_3truefalse7.250000`. Client regex: `{name}(true|false)(true|false)(\d+\.\d+)`, so **left_time MUST contain a decimal point and be ≥ 0** (an integer `10` or a negative value does not match, and the light is silently skipped).
- The name is written **immediately** before `X=`, `P=` or `true/false`, with no separator. Between entries **[choice]** use a single newline (JSON-escaped `\n`). Names are not prefix-ambiguous because the next char after a name is `X`, `P`, `t` or `f`.
- The client reads only x and y and yaw. Positions come from the actor root (capsule centre for characters).

### 6.7 Weather manager (`GEN_WeatherManager`)
| Function | Args | Reply / behavior |
|---|---|---|
| `SetSunDirection` | `{pitch -89..89} {yaw 0..360}` | Rotates the directional light (the client clamps and normalises first). |
| `GetSunDirection` | – | `{"rotation":"P=-26.000000 Y=-20.000000 R=0.000000"}`. Parsed with `P=([-\d.]+)` and `Y=([-\d.]+)`, so **no exponent notation**. Return the values as set (`Y` within 0..360, or equivalent mod 360). |
| `SetSunIntensity` / `GetSunIntensity` | `{0..100}` / – | `{"SunIntensity":"…"}` |
| `SetFog` / `GetFog` | `{density 0..100} {distance cm 0..5000} {falloff 0..2}` | `{"FogDensity":…, "FogDistance":…, "FogFalloff":…}` |
| `SetAtmosphere` / `GetAtmosphere` | `{rayleigh 0..2} {mie 0..5}` | `{"Rayleigh Scattering Scale":…, "Mie Scattering Scale":…}` (keys contain spaces) |
The client strips `\r\n\t` and collapses whitespace before `json.loads`, so pretty-printed JSON is fine. Values go through `float()` and may be numbers or numeric strings. Get must return what Set stored (round trip). The effect SHOULD be visible in lit captures.

### 6.8 Interactables
BP_Mug, BP_Interactable_Box and BP_VehicleBase_Destruction have no client-called
functions. They must be physics or movable props that support attach/detach
(pickup) and a seat socket (vehicle).

### 6.9 Robot dog (`BP_SpotRobot_C`)
| Function | Args | Behavior |
|---|---|---|
| `EnableController` | `True` | Possess with an AI controller so movement input works. |
| `Move_Speed` | `{speed} {duration} {dir}` | dir 0 fwd, 1 back, 2 left, 3 right (strafe), for `duration` s at `speed` cm/s. **[quirk]** For speed<0 the client flips dir but keeps the negative speed. **[choice]** Use \|speed\| with the given dir. Returns immediately; the client sleeps `duration`. |
| `Rotate_Angle` | `{duration} {angle} {dir ±1}` | Yaw += angle over `duration` s. The notebook sends `0.7 90 1` and `0.7 -90 -1`. |
| `lookup` / `lookdown` | – | Tilt the dog's camera pitch up or down by one step **[choice: 15°]**. |
The dog owns one camera (section 3.1).

---

## 7. Timing, blocking and ordering assumptions (summary of tricky behavior)

1. **Never block a reply on motion.** The client sleeps itself: 1 s after `TurnAround`, `duration` after `StepForward`, `Move_Speed` and `Rotate_Angle`. A reply that waits for the motion to finish doubles the time and stalls the 10 Hz `GetInformation` thread, which shares the lock.
2. **One reply per request, in order, async included** (section 1.4). This is the main way to brick the client.
3. **Case-insensitive names** (section 2.3), or `clear_env` leaks every actor.
4. **`/objects` never empty** (section 2.2).
5. **`Success` is a lower-case string** (section 6.1); **LStates time has a decimal point** (section 6.6); **PNG is RGBA** (section 3.2); **BMP contains a byte ≥ 0x80** (section 1.5).
6. **Spawn order defines camera ids**; humanoid N uses camera N+1 (section 3.1).
7. **The manager can come after the actors** (traffic notebook) **or before them** (some flows), so re-scan (section 6.6).
8. **Capture freshness**: a `lit` capture after a `vset` or after a `tick` MUST reflect that state. Render on demand, or wait one frame, before encoding.
9. **Characters at z=600** must not stick in the air or tunnel through the ground; z=110 for pedestrians implies a capsule half-height around 90–110.
10. The traffic loop's correctness depends on the server reporting **reasonably fresh** positions (≤ 1 frame old) and yaw. Stale yaw makes the U-turn and pedestrian-turn polls spin.
11. **Thread safety on the server side**: commands arrive on the socket thread and MUST run on the game thread (UnrealCV dispatches to the game thread). Multiple commands per frame are fine as long as they run in order.

---

## 8. Milestones (priority order)

| M | Scope | Done when |
|---|---|---|
| **M0** | Socket server (section 1, all of it), handshake, capability list, `vrun`, `/objects`, spawn of any class as a placeholder actor, object location/rotation/scale/color/flags/name/destroy, case-insensitive lookup, error replies, time control acks, camera 0 params, **lit PNG RGBA** capture. | `pytest -m m0` green |
| **M1** | Every section 4 prefab path resolves to a class (placeholder meshes sized from `bounding_boxes.json`, roads as flat slabs), `generate_world(demo_city_1)` completes, `clear_env` works, `vget scale/color`. | `pytest -m m1` green, plus a visual check of the city in a lit capture |
| **M2** | `Base_User_Agent` character with camera (ids per section 3.1), gravity, MoveForward/StopAgent/TurnAround/StepForward/SetMaxSpeed, GetCollisionNum, UE manager GetInformation (A*, plus all keys) and UpdateObjects. | `pytest -m m2`; gym_interface_demo runs |
| **M3** | Vehicles (SetState, MakeUTurn, VSetState, V*), pedestrians (section 6.3, P*), traffic lights (section 6.4, LStates), TrafficController smoke on demo_city_1. | `pytest -m m3`; traffic_simulation notebook runs for minutes |
| **M4** | depth npy, object_mask (exact colours), bmp, filename mode; weather manager round-trips and visible lighting. | `pytest -m m4` |
| **M5** | SitDown/StandUp, PickUp/DropOff (mug, box), Enter/ExitVehicle, gestures, scooter cycle (section 6.5), robot dog, SetWaypoints/MovementSimulation, SetPath/FollowPath. | `pytest -m m5`; ue_command notebook runs top to bottom |

Not required by any client code (skip or stub): `AddVehicleSignal`, `AddPedSignal`,
`StartSimulation`, `PSetState` semantics, waypoint-mark and intersection prefabs,
shared-memory `_shared` capture commands (the unrealcv package supports them,
simworld never sends them).
