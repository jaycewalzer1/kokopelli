# Packaged (cooked) Mac build

    scripts/build.sh package      # ~4 min cold; -> Packaged/SimWorld.app (879 MB, self-contained)
    CVPORT=9002 scripts/run.sh packaged

Verified 2026-11-05: 234/234 conformance tests, city build (259 actors, 4.3 s), aerial GPU 11.8 ms, street 6.3 ms.

## Traps hit on the way (each one breaks only the packaged app, never editor -game)

1. **Editor-only API.** `FStaticMaterial`'s imported-slot-name argument exists only when
   `WITH_EDITORONLY_DATA`; guarded in `SWCityMesh.cpp`.
2. **Assets loaded by path string aren't cooked.** The cooker follows references; `TryLoad("/Game/Solarpunk/...")`
   isn't one. `DirectoriesToAlwaysCook` in `DefaultGame.ini` lists `/Engine/BasicShapes` and `/Game/Solarpunk`.
   Materials also need "Used with Instanced Static Meshes" saved in the asset (`Tools/look/set_usage.py`).
3. **oneTBB not staged** by the launcher-installed 5.8 engine -> `dyld: Library not loaded: @rpath/libtbb.12.dylib`.
   `SimWorld.Build.cs` adds it as a `RuntimeDependency`.
4. **UAT `-archive` copies the wrong bundle on Mac** (`Binaries/Mac/SimWorld.app`, no paks). `build.sh` copies
   `Saved/StagedBuilds/Mac/SimWorld.app` instead, into `Packaged/` (not `Build/`, which Unreal owns).
5. **App Sandbox.** The engine signs Development builds with `Sandbox.Server.entitlements` (writes confined to the
   container, so `vget /camera/0/lit /abs/path.png` fails) and Shipping with `Sandbox.NoNet` (no listening socket).
   `Build/Mac/Resources/SimWorld.entitlements` (network only, no sandbox) is set for both in `DefaultEngine.ini`.
