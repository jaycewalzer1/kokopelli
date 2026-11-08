# Body animation and server wiring (wave 1, agent B)

How bodies are chosen, animated and swapped on the Mac SimWorld server. Plan and interface: `PLAN.md`.

## Pieces

| What | Where |
|---|---|
| Body registry (Bodies.json loader, `-bodies=<path>` override) | `mac_server/Source/SimWorld/{Public,Private}/SWBodies.*` |
| Body on every agent/resident (load, fallback, scale, crossfade, eye/hand helpers) | `SWCharacterBase.*` |
| Near/far tier decision + delayed asset release | `SWBodyTiers.*` (`USWBodyTierSubsystem`) |
| The one shared animation | `SWBodyAnimInstance.*` (C++), `/Game/Characters/Anim/ABP_Body` (empty template ABP whose parent is that class) |
| Commands | `Private/SimWorldModule.cpp` `RegisterBodyRoutes` |
| Assets made by script | `mac_server/Tools/bodies/author.sh` → `author_bodies.py`: `M_BodyStandIn`, `M_BodyAnnotation`, `ABP_Body`, `IK_Mannequin_Body` |
| Source clips + mannequin meshes | `mac_server/Content/Characters/Mannequins/` (see Licence) |
| Tests | `mac_server/tests/test_bodies.py` (marker `m6`), mock: `mac_server/tests/mock_server.py` |

## Commands

| Command | Reply |
|---|---|
| `vbp <actor> SetBody <id>` | `{"ok":true,"body":<shown id>,"tier":...,"requested":<id>}` (+ `"warning"` naming each asset that failed). Unknown id: `error unknown body '<id>' ...`, body unchanged. A tiered body starts on its far twin; the near one follows when the tier logic asks. |
| `vbp <actor> GetBody` | `{"body":...,"tier":"near"\|"far"\|"fallback"\|"placeholder","requested":...}` |
| `vbp <actor> SetSpeaking <seconds>` | `{}`; talking gesture for that long (0 stops). `Discussion`/`Arguing`/`Directing` also talk until `StopAction`. **Handoff for agent C / live.py:** send `SetSpeaking <~0.4 s per word>` when an actor says something. |
| `vbp <actor> GetBodyDebug` | tier, `px`, `fading`, `visible_meshes`, `phase`, `time`, alphas, `feet`/`eye`/`hand`/`camera` world positions, held item + its attach parent/socket, clip speeds. For tests and debugging. |
| `vget /bodies` | `{actor: {body, tier, requested, px, fading}}` for every person: what capture sidecars should record per frame (tier per person per frame). |

## Choosing a body

`actors[name]` → else `default_agent` (Base_User_Agent / BP_Default_Character) or `default_resident` (Base_Pedestrian).
A body that can't load walks its `fallback` chain (tier `fallback`, warning in the log and in the SetBody reply);
if nothing loads, the old cylinder placeholder (tier `placeholder`). Never invisible, never a crash. Until agent A's
MetaHumans land every person shows `manny` (tier `fallback`), tinted per actor; `kai` falls back to `manny_child`
(Manny at 140 cm). Optional body keys beyond the plan: `eye_offset_cm` [fwd,right,up] added to the eye socket,
`mesh_yaw` (default -90), `material` (all slots), `tint` ([r,g,b] or `"auto"`).

Size: the mesh is scaled uniformly to `height_cm` (from its imported bounds) and its feet put on the capsule bottom.
The capsule (34 x 90 cm) and all movement code are untouched.

## Near / far tiers

Every frame, for each person whose body has a `far` twin: the tallest it appears in any SimCV camera (agent eyes,
`vset`-placed capture cameras, camera 0 = player view; never its own eyes), as pixels at the 832x480 capture size
(focal = 416 / tan(fov/2)). Near above `near_px` (28), far below `far_px` (22), unchanged in between. At most
`max_near` (3) near, tallest first. The near mesh loads asynchronously (the person stays far until it is in memory);
a handle that stops being shown is released `release_s` (30 s) later. Occlusion is not considered.

Swap: the old mesh moves to a second component (`FadeMesh`) that follows the new one through leader pose, and both
dither over `fade_s` (0.4 s) via the scalar material parameter **`BodyFade`** (1 = visible). Both meshes belong to
the one actor, so they share its single `object_mask` colour. **MetaHuman materials need a `BodyFade` input**
(multiply into their opacity mask through `DitherTemporalAA`, as `M_BodyStandIn` does); a material without it makes
the swap a clean cut half way through the fade instead. Pose continuity: walk phase, anim clock and every blend
weight live on the actor (`FSWBodyAnimState`), not in the anim instance, so a new mesh continues the cycle.

Controls never dither (wave 2b): only the lit pass shows the dithered pair. Around every depth, normal and
object-mask capture SimCV broadcasts `USimCVCameraComponent::OnAnnotationCapture`; `USWBodyTierSubsystem` answers
for every fading person: the losing set (old body before fade 0.5, new body from 0.5) goes on that capture's hidden
list, and the winner's `BodyFade` is 1 for the capture, then restored. No visibility changes, so nothing's render
state is rebuilt between the lit and the control captures. Grooms and clothes (Bodies.json `grooms`/`outfit`) are
part of each set: they fade (or cut at 0.5 if their materials lack `BodyFade`), move to the old body during a
swap, and carry the person's object id. Test hook: `vbp <actor> HoldFade <0..1>` pins a crossfade (-1 releases).

## The animation (one for all bodies)

`USWBodyAnimInstance` builds the pose natively in its proxy's `Evaluate` (the engine's native-evaluation hook), so
there is no graph to author by hand and it runs on any skeleton with UE5 bone names (Manny/Quinn and MetaHuman
bodies share them: `pelvis`, spine chain up to `neck_01`, `thigh/calf/foot_*`, `upperarm/lowerarm/hand_*`, `head`).

| Behaviour | Source | How |
|---|---|---|
| idle | `MM_Idle` (clip) | |
| walk / run by ground speed | `MF_Unarmed_Walk_Fwd`, `MF_Unarmed_Jog_Fwd` (clips) | Shared phase; the cycle advances by distance walked / distance one cycle covers. Each clip's stride speed is **measured** from its planted foot (walk 287, jog 561 cm/s in mesh units, matching the 300/600 Epic gives them in `BS_Idle_Walk_Run`), scaled by body height, so feet don't slide at any speed. Run blends in above 1.25 x walk speed. Root motion is locked. |
| turn in place | walk clip (no turn clips exist) | Steps the walk cycle in place at a rate set by yaw speed while not moving. |
| sit (SitDown/StandUp) | **no clip: procedural** | Pelvis down to a 45 cm seat, feet forward via two-bone leg IK, hands on thighs via arm IK, 0.6 s blend. |
| pick-up then carry | **no clip: procedural** | 0.9 s reach (squat by pelvis drop + leg IK, 60 deg spine bow, arm IK to the item); at the bottom (0.45 s) the item is attached to the **hand socket** and kept in the palm (light) or between both hands (heavy box, both arms IK'd to its sides). DropOff puts it down 50 cm in front of the feet. |
| talking gesture | **no clip: procedural** | Right hand drifting in front of the chest, left hand lower, small head nod (`SetSpeaking`, or the Discussion/Arguing/Directing gestures). |

Eye camera: an agent's camera sits at the eye socket + `eye_offset_cm` every frame (so it is at the body's real eye
height and drops when sitting or bending) and looks along the actor's yaw. A client `vset /camera/N/location` takes
over. The agent's own body is hidden from its own camera (no inside-of-head views; first person shows no hands).

## Gaps (honest list for the user)

- **Sit, pick-up and talk have no motion-capture source**: the Manny set has no such clips. They are procedural IK
  poses: readable at mid/far range, stiff close up (no weight shift, fingers don't close on the mug, talk is a
  generic loop). Fix: add mocap clips (e.g. Fab's free "Game Animation Sample" set) and slot them in as sequences.
- Turning in place reuses the walk cycle (no turn clips).
- Sitting happens where the agent stands (SitDown never moved the agent onto the seat); with the 45 cm seat height
  it lines up only if the agent stands at a seat's front edge.
- Walk clip is a brisk 3 m/s walk; at the 1-2 m/s our agents move it plays slowed down (no sliding, but long strides).
  A slow-walk clip would look more natural.
- Tier uses on-screen height only, not occlusion.
- MetaHuman materials need `BodyFade` added (above); without it, near/far swaps cut instead of fading.
- Packaging: `/Game/Characters` is not in `DirectoriesToAlwaysCook` yet (bodies are loaded by path, so the cooker
  won't find them). Wave 2 adds it when packaging to `Packaged_bodies/`. Without it a packaged app falls back to the
  placeholder (and object masks of skinned meshes fall back to `BasicShapeMaterial`). `Config/Bodies.json` must be
  staged too (`+DirectoriesToAlwaysStageAsNonUFS` or copy next to the app and pass `-bodies=`).

## IK Retargeter path to MetaHuman skeletons

MetaHuman bodies in UE 5.x use bone names compatible with the UE5 mannequin, so the clips may play directly once the
skeletons are marked compatible. If proportions differ visibly (they will for a child), retarget:

1. Source rig: `/Game/Characters/Anim/IK_Mannequin_Body` (made by `Tools/bodies/author.sh`: retarget root `pelvis`,
   chains Root, Spine, Neck, Head, Left/RightClavicle, Left/RightArm, Left/RightLeg with hand and foot goals).
2. Target rig: in the scratch project, editor Python on the MetaHuman body mesh:
   `rig = AssetTools.create_asset("IK_<Person>_Body", ..., unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())`,
   `c = unreal.IKRigController.get_controller(rig)`, `c.set_skeletal_mesh(body)`, `c.set_retarget_root("pelvis")`,
   then the same chain names (`spine_01..spine_05`, `neck_01..neck_02`, `clavicle_*`, `upperarm_* .. hand_*`,
   `thigh_* .. ball_*`).
3. Retargeter: `unreal.IKRetargeterFactory` → `RTG_Mannequin_To_<Person>`; `unreal.IKRetargeterController`:
   `set_ik_rig(SOURCE, IK_Mannequin_Body)`, `set_ik_rig(TARGET, IK_<Person>_Body)`, `auto_map_chains(EXACT, True)`;
   align the retarget pose to the A-pose if needed.
4. Batch: `unreal.IKRetargetBatchOperation.duplicate_and_retarget([MM_Idle, MF_Unarmed_Walk_Fwd, MF_Unarmed_Jog_Fwd],
   source_mesh, target_mesh, retargeter, suffix="_<Person>")` into `/Game/Characters/Anim/<Person>/`.
5. Point the person's anim at them: subclass `ABP_Body` per skeleton (`ABP_Body_<Person>`, set `IdleClip`/`WalkClip`/
   `RunClip` defaults) and put that class in Bodies.json `anim_class`. The procedural layers need nothing: they find
   bones by name.

## Licence

The mannequins and clips are copied from the engine's Third Person template content
(`UE_5.8/Templates/TemplateResources/High/Characters/Content/Mannequins`). That copy already references
`/Game/Characters/Mannequins/...`, so it works without re-pathing (the `MoverExamples` copy references
`/MoverExamples/...`; it holds the same Manny meshes but no Quinn). Epic ships this as template/sample content under the
Unreal Engine EULA: it may be used and shipped inside projects made with Unreal Engine; it may not be redistributed on
its own. Fine for this project.
