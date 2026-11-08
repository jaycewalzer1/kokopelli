# Realistic bodies for the city agents

Goal (user, 2026-11-07): replace the cylinder-and-ball placeholder (`SWCharacterBase::BuildHumanBody`) with realistic,
animated human bodies (MetaHuman first choice), wired through the server, the Python agents and the world-model
pipeline, tested by unit tests and in the real sim, with results shown as model runs. Realism matters for demos.

## What already exists

- Server: `ASWCharacterBase` (capsule 34x90 cm, `CharacterMesh` / `CharacterAnimClass` / `CharacterMeshOffset` /
  `CharacterMeshYaw` in `USWSettings`, commented out in `Config/DefaultGame.ini:40`). `SWHumanoid` (agents, eye camera on
  the capsule), `SWPedestrian` (scripted residents). Movement, PickUp/DropOff, SitDown/StandUp, scooter are all done and
  covered by `mac_server/tests` (234 tests).
- On disk, UE 5.8: MetaHuman plugins (`Engine/Plugins/MetaHuman/*`, incl. `MetaHumanCharacter` = in-editor creator,
  `MetaHumanCrowd`), the Manny mannequin + locomotion set (`Engine/Plugins/Experimental/MoverExamples/Content/Characters/
  Mannequins/`: SKM_Manny_Simple, ABP_Manny, BS_MM_WalkRun, MM_Idle, MM_Walk_Fwd, RTG_Mannequin, IK_Mannequin).
- Python: `city/agents/live.py` (one Qwen + scripted `npcs.json`), `city/agents/lunch_wm.py` (Mara + Iris, two humanoids
  GEN_BP_Humanoid_0/1), adapter `runtime/adapters/simworld.py` (other session; read-only).

## Interface (fixed now so the waves can work in parallel)

Bodies are chosen **server-side by actor name**, so no client that already works has to change:

`mac_server/Config/Bodies.json`
```json
{
  "default_agent": "mara", "default_resident": "ana",
  "actors": {"GEN_BP_Humanoid_0": "mara", "GEN_BP_Humanoid_1": "iris"},
  "bodies": {
    "mara": {"mesh": "/Game/Characters/Bodies/Mara/...", "anim_class": "/Game/Characters/Anim/ABP_Body.ABP_Body_C",
             "eye_socket": "FACIAL_C_FacialRoot", "hand_socket": "hand_r", "height_cm": 168, "fallback": "manny"}
  }
}
```
- New command: `vbp <actor> SetBody <body_id>` -> `{"ok": true, "body": id}` or an error naming the missing asset.
  `vbp <actor> GetBody` -> current id. Unknown/unloadable body -> fallback chain, then the placeholder, with a log warning
  (never a crash, never an invisible actor).
- Python side: an optional `"body"` field on agents and on each NPC in `npcs.json`; `live.py` sends `SetBody` after spawn.
  Clients that never send it get the Bodies.json mapping.

Invariants every wave must keep: capsule size and movement speeds unchanged (all 234 tests pass); the eye camera follows
the head (eye socket) at the body's real eye height; carried objects attach to the hand socket; the body shows up in
depth and in the object masks (segmentation) the world-model controls use, as one object id per person; GPU frame time of
the aerial view stays in budget (note the number with 2 and with 8 bodies).

## Near/far bodies, revised (user decision, 2026-11-07, supersedes the section below where they differ)

- **Far body = a Low-quality MetaHuman export of the SAME person** (cards hair, small textures, simple face, no cloth
  sim), not the mannequin. Near body = the high-quality export. Same skeleton and ABP for both.
- **Switch by on-screen height, not metres:** a person goes near when they are taller than `near_px` (default 28 px,
  measured at the 832x480 world-model capture size) in any active camera, far below `near_px - 6` (hysteresis).
  `max_near` still applies; measure Low cost and raise it if Low is cheap.
- **Short dithered fade** (~0.4 s) across the swap: both bodies drawn in the same pose (leader pose), dither param on
  the materials. Seg mask: both meshes carry the person's one object id.
- **Mannequin = fallback only** (body failed to load, or memory pressure as a last step). It is never the normal far body.
- Sidecars still record tier per person per frame (now `near` / `far` / `fallback`).

## Near/far bodies, first version (user decision, 2026-11-07)

The user ruled out 8 full MetaHumans at once (memory). Each person has a **near body** (MetaHuman) and a **far body**
(Epic's free mannequin, tinted per person so they stay recognisable). A person shows the near body only while within
`near_m` of any active camera (agent eyes, the capture cameras, the player view) and the far body beyond it.
- Bodies.json: each body gets `"far": "manny_<tint>"`; top level gets `"near_m"` (default 12, tunable) and `"max_near"`
  (hard cap on MetaHumans shown at once, default 3; extra ones stay far, nearest first).
- Hysteresis (switch to near at `near_m`, back to far at `near_m + 3`) so a person on the boundary doesn't flicker.
- Same skeleton/animation pose is kept across the swap (shared retargeted ABP), so the swap doesn't restart a walk cycle.
- Memory: only the MetaHuman assets of bodies currently near stay loaded (async load on approach, release after leaving
  for 30 s); measure peak with 3 near + 5 far.
- `GetBody` also returns `"tier": "near"|"far"`; the JSON sidecar of every capture records the tier per person per frame,
  because a swap in view is a visible pop in the world model's input.

## Waves

1. (parallel)
   - **A. MetaHuman spike + characters.** Can MetaHuman Creator run on this Mac (UE 5.8, editor Python, no GUI clicks)?
     Does any step need an Epic/Fab login or cloud service (texture synthesis, assembly)? Make Mara, Iris and 4 resident
     bodies (varied age, build, skin, clothes), assembled at a LOD that fits memory, in a scratch copy of the project.
     Fallback ladder if blocked: MetaHuman presets that ship with the plugin -> report what needs the user's login ->
     Manny. Output: assets ready to migrate + `city/bodies/METAHUMAN.md`.
   - **B. Server wiring + animation.** Bodies.json, `SetBody`/`GetBody`, skeletal mesh on `SWCharacterBase`, one shared
     animation blueprint (idle / walk / run blend by speed, sit, pick-up and carry, turn in place, talk gesture when the
     actor is speaking), retargeted from the Manny set via IK Retargeter so it works on MetaHuman skeletons. Built and
     tested with Manny as the stand-in body until A delivers. New pytest conformance tests (`m6` marker).
   - **C. Python wiring + unit tests.** `body` fields in `npcs.json` and live.py args, `SetBody` calls, the mock server
     learning `SetBody`/`GetBody`, unit tests in `tests/test_city_bodies.py`. Handoff note for the lunch and adapter owners
     instead of editing their files.
2. **Integration.** Migrate A's assets into `mac_server/Content/Characters/`, cook + package to
   `mac_server/Packaged_bodies/` (NOT `Packaged/`, which queued jobs use on 9001), full test suite, close-up / mid / aerial
   renders and first-person views, perf numbers, seg/depth check. Swap `Packaged_bodies` in only when nothing uses 9001.
3. **Model runs.** Through the GPU queue (`bodies_*` jobs, `--about` and `--output`, `ram_share` hold): a short `live.py`
   run with residents, and the two-agent lunch with bodies, plus a Sim-Transfer clip of a person walking. Results grouped
   as "Bodies" on the dev panel's Model runs page, with before/after (cylinder vs body) side by side.

## Rules for every agent on this

- Editor work on **port 9004** only, under `python ram_share.py claim --name bodies_9004 --gb 10 --pid <PID>`; never
  9001, 9003 or `mac_server/Packaged/`. Minimize the window (Metal present leak, see `mac_server` notes).
- Model jobs only through `.claude/worktrees/ops/ops/gpu.py run ... --about ... --output ...`.
- Don't edit files other sessions own (AGENTS.md); write a handoff note instead.
- Every output folder gets a JSON sidecar naming models/assets used.
- Results and decisions go in `city/bodies/LOG.md` (dated, short).
