## P3-B Mouse turns camera 0 (2026-11-10, orchestrator with the owner at the mouse)

Change: `-nomouse` on the server command line (or `NOMOUSE=1` with `mac_server/scripts/run.sh`) makes `ASWPlayerController::Look()` return before it reads the mouse. Keys still work. Without the flag nothing changes.
Files: `mac_server/Source/SimWorld/{Public/SWPlayerController.h,Private/SWPlayerController.cpp}`, `mac_server/scripts/run.sh`, and `NOMOUSE=1` added to the server launch in `city/agents/run_wm_life.sh` and `run_wm_lunch.sh`.

Test, editor-game build on port 9003, `vget /camera/0/rotation`, the owner clicking into the window and circling the mouse for about five seconds:

| Build | Before | After |
|---|---|---|
| `-nomouse` | 0.000 0.000 0.000 | 0.000 0.000 0.000 |
| no flag | -34.377 41.881 0.000 | 14.186 -57.729 0.000 |

Editor build: `scripts/build.sh editor` succeeded, 12 s, peak 4.1 GB under the memory guard.

Not done: no packaged build has the fix. The packaged servers in `mac_server/Packaged*` ignore the flag, so a capture from port 9001 can still be turned by the mouse until the owner approves a repackage (hours). The brief's rule to step away during packaged-server runs still applies until then.

### Packaged, 2026-11-10 afternoon
`mac_server/scripts/package_nomouse.sh` built `mac_server/Packaged_nomouse/SimWorld.app` from main. Not launched or tested: the owner asked for no GPU use. To check it, start that app with `-nomouse -cvport=9003`, read `vget /camera/0/rotation`, circle the mouse in the window, and read it again. `mac_server/scripts/run.sh packaged` still launches `mac_server/Packaged/`, so capture runs use the old build until the owner swaps the folders or points the scripts at the new one.
