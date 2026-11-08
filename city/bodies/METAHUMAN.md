# MetaHuman on this Mac (wave 1, agent A), 2026-11-07

Short version: **MetaHuman Creator runs headless on this Mac, from editor Python, without any login or cloud
service.** All 7 bodies (mara, iris, ana, tomas, wen, priya, kai) are created, rigged and assembled at **High (near)
and Low (far)**. But they are **grey clay, bald and in underwear**. Skin tone, skin textures, hair, eyebrows and
clothes all come from the **"MetaHuman Creator Core Data"**, and that isn't installed with the engine. Installing it
is a launcher step only the user can do (see "What the user must do"). After that, one script re-run gives the real
look.

Renders: `out/bodies/renders/wave1/` (`<id>_{high,low}_{front,34,head}.png`, `<id>_low_far.png`,
`mara_high_fade050.png`). Numbers: `costs.json` and `out/bodies/make/make_report_all.json`.

## What I verified by running it, and what I only read

| Step | Status | How I know |
|---|---|---|
| MetaHumanCharacter plugin loads in the 5.8 Mac editor (Mac dylibs ship) | works | ran |
| Create a character asset from Python (`MetaHumanCharacterFactoryNew`) | works | ran |
| Body: 30 parametric constraints (height, fat, muscularity, masculine/feminine, chest, waist...) | works | ran; heights hit exactly |
| Face sculpt by moving landmarks (`translate_face_landmarks`, 79 landmarks), seeded and symmetric | works | ran; renders differ per person |
| Face via `set_face_model_coefficients` | **fails**: the array is a serialized blob (`PatchBlendModel: Deserialize from vector failed`) | ran |
| Eye colour, eyelash type | works | ran |
| Skin tone / freckles / body textures (`commit_skin_settings`) | **blocked (Core Data)**: asserts in `BodyTextureUtils` (`Optional/BodyTextures` missing); face texture synthesis says `Optional/TextureSynthesis ... does not contain valid data` | ran |
| Hair, eyebrows, beard, clothes (wardrobe items `/MetaHumanCharacter/Optional/...`) | **blocked (Core Data)**: folder absent | checked disk; read plugin source |
| Face rig ("auto-rig") | Epic's path is a **cloud call that needs an Epic account login** (EOS auth in `MetaHumanCloudAuthentication.cpp`). **Local workaround works:** write the edited face state to a DNA and import it as the whole face rig (`MHLocal.write_face_state_dna` + `import_from_face_dna(import_whole_rig=True)`). Joints-only rig quality. | ran; never called the cloud |
| "Download Texture Sources" (cloud, login) before assembly | skipped. Assembly is gated on it; `MHLocal.set_has_high_resolution_textures` lifts the gate. With Core Data the locally synthesized textures (1-2k) are used instead of the cloud 4-8k ones. | ran (gate); 2k quality after Core Data: read, not run |
| Assembly, UE Optimized pipeline, High and Low | works headless in the **full editor** (`-ExecutePythonScript`, window minimized). In a `-run=pythonscript` commandlet, Texture Graph baking doesn't run and the error report crashes (no Slate). Body texture baking has to be off without Core Data (`MHLocal.build_local(..., bake_body=False)`), or the pipeline asserts on missing body textures. | ran, 7 x 2 builds |
| `BodyFade` crossfade param on every material (High and Low) | works: 1 shows the body, 0.5 dithers, 0 hides it. Set with `SetScalarParameterValueOnMaterials`, as agent B's server does. | ran (`fadetest.json`, `mara_high_fade050.png`) |
| Child body (kai) | **no real child**: the parametric body's height floor is 135 cm and it keeps adult proportions (adult head size). kai is a small adult at 138 cm. A real child needs a child body from Fab or a custom mesh conformed with `conform_body_to_target`. | ran |
| Fab / MetaHuman presets from the web | not tried (they need the user's Fab login) | read (`Plugins/Fab/.../MetaHumanImportWorkflow`) |

`MHLocal` is a small editor plugin I wrote (`city/bodies/metahuman/MHLocal/`, about 150 lines). It calls public C++
API that Python doesn't expose: `FState::StateToDna`, `SetHasHighResolutionTextures`, pipeline material-baking switches,
`FlushRenderingCommands`, `LoadPackageAsync` timing. It doesn't modify the engine or any plugin. It has to be in any
project that rebuilds the bodies; the server doesn't need it at runtime.

## What the user must do (once)

1. Open the **Epic Games Launcher**, signed in as you. Go to **Unreal Engine → Library**, open the **▾** menu on the
   5.8 engine tile, choose **Options**, tick **"MetaHuman Creator Core Data"**, then **Apply**. This puts files in
   `/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional/` (the editor
   checks for `TextureSynthesis/*.ar` and `BodyTextures`). It's a few GB of download; I haven't measured it.
2. Run `city/bodies/apply_core_data.sh` (wave 2b). It runs `make_bodies.py` (skin tone, freckles, skin detail,
   hair / brows / beard / moustache grooms and the outfit, all planned per person in `city/bodies/looks.json` and
   resolved against the installed wardrobe by `metahuman/looks.py`), `add_fade.py`, `migrate_bodies.sh`,
   `write_parts.py` (Bodies.json `grooms`/`outfit`), `package_bodies.sh`, the full suite on the packaged build, and
   the wave 2 renders into `out/bodies/renders/wave2_core/`. Dry run any time: `python3 city/bodies/metahuman/looks.py --check`.

Optional, and needs the user's login inside the editor:
- Cloud auto-rig, for a better face rig with blendshapes, so faces animate when the agents talk.
- Cloud "Download Texture Sources", for 4k/8k skin textures.

Neither is needed for the city's distances.

## Decisions for the user

1. **Clay now, or wait for Core Data?** Integration can migrate the clay bodies today (the shapes, rig, LODs, fade
   and costs are real), or wait for the Core Data re-run. My recommendation: install Core Data before wave 2 so
   wave 2 migrates the final look once. The clay bodies are good enough to get B's wiring working against now.
2. **kai:** accept a 138 cm small adult, use the Manny child stand-in (B's `manny_child`), or get a child body.

## Assets (scratch project `out/bodies/scratch_project`)

Per body `<id>` (all ids lowercase; heights are the MetaHuman "Height" measurement, which reaches the top of the head):

```
/Game/Characters/Bodies/<id>/MHC_<id>                                  editable MetaHuman character (source of truth)
/Game/Characters/Bodies/<id>/High/<id>_high/Body/SKM_MHC_<id>_BodyMesh near body
/Game/Characters/Bodies/<id>/High/<id>_high/Face/SKM_MHC_<id>_FaceMesh near face (follows the body by leader pose)
/Game/Characters/Bodies/<id>/High/<id>_high/BP_<id>_high               assembled actor blueprint (reference only)
/Game/Characters/Bodies/<id>/Low/<id>_low/...                          same layout, far body
/Game/Characters/Bodies/Common/...                                     shared materials, skeletons, post-process ABPs (228 MB on disk; migrate it too)
```

| id | who | height cm | eye height cm (ref pose) | build |
|---|---|---|---|---|
| mara | woman ~30, warm, chatty | 168 | 157.8 | feminine, slim-average |
| iris | Mara's neighbour, ~40 | 174 | 163.7 | tall, slim |
| ana | barista, ~25 | 162 | 152.0 | small, slim |
| tomas | baker, ~45 | 178 | 166.5 | broad, heavy |
| wen | retired engineer, ~72 | 166 | 155.1 | slight, low muscle |
| priya | librarian, ~55 | 160 | 149.8 | average, soft |
| kai | child (see above) | 138 | 127.8 | small adult |

Age, skin tone and hair are what Core Data adds. Without it, the people differ in face shape, body and eye colour.

**Skeletons.** Body: `/Game/Characters/Bodies/Common/Female/Medium/NormalWeight/Body/metahuman_base_skel`. That is
one skeleton for all 7 bodies, High and Low. It has 342 bones and **UE5 mannequin bone names** (root, pelvis,
spine_01..05, neck_01/02, head, clavicle/upperarm/lowerarm/hand_*, thigh/calf/foot/ball_*, plus twist and corrective
helpers), so B's name-based animation and the Manny IK retargeter apply. The face uses `Face_Archetype_Skeleton` (875
bones) and is driven by leader pose from the body. Both meshes face +Y (B's default `mesh_yaw` -90 is right).

**Sockets.** There are no sockets; use bones.
- Hand: `hand_r` on the body.
- Eye: `FACIAL_L_Eye` / `FACIAL_R_Eye` live on the **face** mesh. On the body mesh, use `head` with
  `eye_offset_cm` ≈ **[8, 0, 6]** (forward, right, up). Measured from the reference pose: for mara, the eyes are at
  y=+8.2, z=157.8 and `head` is at z=151.9. This holds for every body to within about 1 cm.
- `FACIAL_C_FacialRoot` exists on the face skeleton.

**Handoff to B (Bodies.json).** A MetaHuman is **two skeletal meshes**: body, plus a face that follows the body by
leader pose. So `mesh` should point at the body, and a new optional key `face_mesh` should be attached to the body with
`SetLeaderPoseComponent`. That is how the assembled BP does it. The alternative is merging them into one mesh. The
plugin can do that (`export_geometry(full_body_skeletal_mesh=True)`), but the result has clay materials and every LOD,
so it isn't done here. The face mesh's post-process anim BP needs **RigLogic** enabled in `mac_server` (the body's
corrective ABP does too).

## Costs (measured in the uncooked editor, M4 Max 36 GB)

| | High (near) | Low (far) |
|---|---|---|
| Disk per body | 58 MB | 7 MB |
| Skeletal meshes (body + face, all LODs) | 7.7 MB (body 4.8 + face 2.9) | 1.4 MB (0.7 + 0.7) |
| Own textures (estimated, all mips) | 42 MB (2k eye and teeth maps; head maps are 32 px placeholders until Core Data) | 4.9 MB (512 px) |
| Shared `Common` (loaded once for all bodies) | ~650 MB estimated resident (skin region / micro-detail textures up to 4k); 228 MB on disk | same |
| Async load, uncooked editor (`LoadPackageAsync` + flush) | 270-350 ms per body (first one ~900 ms, because it pulls in Common) | 60-90 ms |

- **Memory budget.** Per person, a Low body is about 6 MB and a High body about 50 MB, on top of the shared ~650 MB
  that is paid once. With clay, 3 High + 8 Low is about 0.85 GB. Expect the textures to grow with Core Data: synthesized
  face maps at 1-2k and body maps, maybe +30-60 MB per High body (estimate, not measured). On memory alone,
  `max_near` could go from 3 to 6, and Low is cheap enough for every resident.
- **GPU.** **Not reliably measured.** I timed `CaptureScene + FlushRenderingCommands` at 1280x720 with N copies. The
  empty-scene baseline wandered between 6.7 and 12.8 ms between runs (the machine was shared with other jobs), so
  deltas for 1-8 bodies are within the noise. The only clear signal: 16 High bodies at 4 m add about 12 ms, and 8 High
  at 40 m add about 8 ms. Numbers are in `costs.json` `perf`. Treat them as an upper bound and redo this in the
  packaged game in wave 2 (`stat gpu`, B's aerial view, 2 and 8 bodies).
- **Hitches.** The async load is cheap for Low and about 0.3 s for High in the editor. Cooked async loading runs on
  the loading thread, so the main-thread hitch left over is creating render resources and MIDs. I haven't measured that
  (it needs the packaged build). B's plan (the near body only appears once loaded, the far body stays until then) hides
  the load time either way.

## Re-running (reproducible)

```
city/bodies/metahuman/setup_scratch.sh                         # scratch copy + plugins + MHLocal, builds the editor (~2 min)
city/bodies/metahuman/run_editor_gui.sh city/bodies/metahuman/make_bodies.py   out/bodies/make.log     # ~1 min per body
city/bodies/metahuman/run_editor_gui.sh city/bodies/metahuman/add_fade.py      out/bodies/add_fade.log # BodyFade on Common masters
city/bodies/metahuman/run_editor_gui.sh city/bodies/metahuman/render_bodies.py out/bodies/render.log   # renders + costs
```

`MH_BODIES=mara,iris` limits the bodies. The runner launches the full editor with `-nosimcv` (it opens no port;
9004 is B's), claims 10 GB as `bodies_mh_editor` in `ram_share`, minimizes the window, and kills the crash reporter
that UE 5.8 sometimes leaves behind after `quit_editor` (a Slate teardown crash after all work is saved).

How the fade was added: `add_fade.py` adds `BodyFade` to the 8 master materials in Common (skin baked, skin UI, eye,
teeth, eye occlusion, lacrimal fluid, eyelashes, M_Hide). The MetaHuman masters use **Material Attributes**, so a plain
OpacityMask pin is ignored. The script re-makes the attributes with OpacityMask × DitherTemporalAA(BodyFade). Opaque
masters become Masked, which costs a little early-Z. Translucent ones get their Opacity multiplied by the fade.
Assembly may re-copy Common masters, so always run `add_fade.py` after `make_bodies.py` (it is idempotent).
