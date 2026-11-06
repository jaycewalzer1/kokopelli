# The solarpunk city in the SimWorld server

"Garden Village + Commons" (`~/Desktop/kokopelli/city/world.json`, 600 x 600 m) built as runtime geometry in
the Mac SimWorld server. Nothing is a saved asset: a Python builder spawns C++ actors over SimCV and hands each
one its world.json element as JSON; the actor builds its own meshes.

## Build and render

```bash
cd ~/Desktop/kokopelli/mac_server
scripts/build.sh editor
CVPORT=9001 scripts/relaunch.sh            # kills only the editor-game of THIS project on THIS port
PY=~/Desktop/kokopelli/simworld/.venv/bin/python
$PY -I ../city/ue/build_city.py --port 9001           # (re)build everything, ~2 s
$PY -I ../city/ue/build_city.py --port 9001 --only bldg_fern,trees_street   # rebuild some actors
$PY -I ../city/ue/build_city.py --port 9001 --clear   # remove every CITY_* actor
$PY -I ../city/ue/build_city.py --dry                 # print the plan only
$PY -I ../city/ue/render_views.py --port 9001 [--only street,canopy] [--perf 5]
```

Renders go to `~/Desktop/kokopelli/out/city_renders/<timestamp>/` (PNG per view, `views.json` with poses and
capture times, `perf.json` with `--perf`). Views: 3 aerials, one street view per cell, a courtyard, the canopy
walk and a sky bridge, creek/pond (ground + aerial), the Commons (aerial + plaza), parkway, food forest.

Frame stats: `vbp CITY_manager ResetFrameStats`, wait, `vbp CITY_manager GetFrameStats` returns averaged
`delta_ms`, `game_ms`, `render_ms`, `gpu_ms` (RHIGetGPUFrameCycles), `fps` and city totals. The manager ticks
even when paused.

## Coordinates

world.json: origin at the NW corner, x east, y south, metres. UE: X = east, Y = south, Z up, cm. So UE = world x 100
with no flip. UE is left-handed, so seen from above with +X to the right +Y points down = south: a top-down camera
with yaw 270 (looking north) shows north at the top. Verified in `aerial_topdown.png`: creek on the right (east),
parkway at the top (north), plots at the bottom, food forest on the left.

## Architecture

| File | What |
|---|---|
| `Source/SimWorld/Public/City/SWCityActors.h` | all city UCLASSes |
| `Source/SimWorld/Private/City/SWCityMesh.*` | `FSWMeshBuilder` (boxes, quads, prisms, ribbons, ellipsoids, gables, vaults -> one runtime `UStaticMesh` via `BuildFromMeshDescriptions` fast path), shared primitives for instancing, material loading |
| `Source/SimWorld/Private/City/SWCityJson.h` | JSON readers, shared colours |
| `Source/SimWorld/Private/City/SWCityActors.cpp` | base, manager, ground, lane, path, water, trees, furniture, places, open spaces |
| `Source/SimWorld/Private/City/SWCityBuilding.cpp` | buildings, sky bridges, canopy landings |
| `~/Desktop/kokopelli/city/ue/build_city.py` | world.json -> actor plan (coords, derived fields, tree placement) -> SimCV |
| `~/Desktop/kokopelli/city/ue/render_views.py` | camera poses + captures + perf |

Every class derives from `ASWCityActor` and has `UFUNCTION Configure(const FString& Json)` (re-callable: it
replaces the old geometry) and `GetBuildInfo(FString& Info)`. JSON fields ending in `_cm` are UE coordinates;
`loc_cm` places the actor, `yaw` rotates it (furniture, places, bridges).

| Class | Names | Built from |
|---|---|---|
| `SWCityBuilding` | `CITY_bldg_<id>` | footprint, floors, height, materials, palette, entrances, `street_sides`, `walk_cm`, `rooftop_feature`, `deck_spurs_cm`, `keep_clear` |
| `SWCanopyLanding` | `CITY_landing_<id>` | footprint, `base_cm` (host roof), `top_cm` |
| `SWSkyBridge` | `CITY_bridge_<id>` | span midpoint, yaw, length, width, elevation |
| `SWCityLane` | `CITY_lane_<id>` | rect, runnel (lane_y1/y2) |
| `SWCityPath` | `CITY_path_<id>` | green loop trail, creek boardwalk, + a parkway trail |
| `SWCityWater` | `CITY_water_<id>` | creek centreline (Chaikin-smoothed), pond ellipse |
| `SWCityTrees` | `CITY_trees_<group>` | `[[x_cm, y_cm, species, scale], ...]`, placed by the builder |
| `SWCityOpenSpace` | `CITY_space_<id>` | courtyards, amphitheater, chess garden, playground, village green, plots, food forest |
| `SWStreetFurniture` | `CITY_furn_<type>_<nnn>` | the 136 items; murals on their building's street wall |
| `SWCityPlace` | `CITY_place_<id>` | category dressing at the place's facade (cafe tables + umbrellas, market stalls, ...) |
| `SWCityGround` | `CITY_ground` | grass, meadow skirt, plaza paving, meadow flowers |
| `SWCityManager` | `CITY_manager` | frame stats |

Buildings (bars of the courtyard blocks plus the library, school, bathhouse): per floor a CLT slab with a lip, a
recessed wall core (rammed earth with proud strata on the two lowest floors where the materials say so, solar
glass curtain on "+ solar glass" bars, else timber), timber fins every bay, punched windows with sills and palette
shutters, glass shopfronts + sign band + striped awnings and planters at every shopfront entrance, open
courtyard passages through the ground floor, Bosco-style staggered balconies with planters, shrubs, small trees
and trailing greenery, green-wall panels (living facade), climbing jasmine on south walls, bamboo louvers.
Stepped terraces: 6-storey bars step back 3 m then 6 m on the courtyard side and 3 m on the street side at
level 5 (17.5 m, where the canopy walk runs); 5-storey bars step the top floor back on the courtyard side.
Roofs: green roof, edge planters spilling over, south-tilted PV rows on one end, roof trees and shrubs, the canopy
walk deck with pergolas/benches on 17.5 m roofs (spurs out to where bridges land), and the cell's rooftop feature
on the east bar (greenhouse, dye garden, herb terrace, hammock deck, solar lab with turbine, dance deck,
observatory dome on the library). Civic: timber-vaulted market hall on branching columns, mobility-hub PV canopy,
glass greenhouse.

## Decisions

* **Runtime static meshes, not ProceduralMeshComponent.** `BuildFromMeshDescriptions(bFastBuild)` gives normal
  static-mesh draw paths (cached draw commands, auto-instancing across actors) and works in game builds.
* **One mesh per actor + instanced primitives.** Unique geometry is merged per actor (one section per
  material+tint); foliage, stones, reeds, crops are `UInstancedStaticMeshComponent`s of 7 shared primitives
  (jittered icosphere blob, tapered trunk, cube, cylinder, reed, stone, disc). Material instances are cached per
  (material, tint) so equal pieces batch across actors.
* **Static mobility** for all city components (keeps virtual-shadow-map pages cached); `Configure` flips the root
  movable only to place the actor.
* **Tint semantics.** The Solarpunk materials look natural at Tint = white (checked with a swatch render), so
  colours are passed *relative to a reference colour per material* (`RefColor` in SWCityMesh.cpp); palettes shift
  hue from there. Dark metal tints switch M_Metal's `Steel` to 1. With the BasicShapeMaterial fallback the
  colour goes to "Color" as is.
* **Builder does placement, C++ does geometry.** Street trees (every 8 m, two rows in the wide lanes, one row
  outside the edge lanes), food forest, parkway grove, willows along the creek, courtyard fruit trees, village
  green shade trees and commons planting are placed in Python with a fixed seed, avoiding buildings, bridges,
  landings, water, paths, furniture, place frontages, entrances and lane intersections.
* **Runnels** sit 6 m off the lane_y1/y2 centre lines so the green-loop trail (which runs on the lane centre
  lines) keeps its line. The parkway trail and the meadow/woods skirt round the plan are extras for the views.
* **Canopy walk** deck tops are at elevation + 55 cm (`SWCity::WalkDeckLift`) on roofs, terraces, bridges and
  landings, so they meet.
* Collision: hidden boxes for building masses (ground-floor passages left open), roof/terrace walk decks, bridge
  decks, boardwalk and dock. Foliage has none.

## Measured (M4 Max, 1280x720 window, Lumen + VSM)

* Build: 256 actors, spawn 0.2 s, Configure 1.7 s, total ~2 s.
* 2301 components, ~16.4 M triangles (estimate, instances x primitive), 205 k instances, 1943 trees.
* Captures: 0.17-0.24 s per 1280x720 lit PNG (21 views in 3.8 s plus 2.5 s settle each).
* Frame (5 s free-running averages): aerial overview GPU 12.6-15.0 ms, street GPU 10.7-11.5 ms, game thread
  ~1 ms; delivered 59-60 fps (the window is vsync-capped at 60), i.e. ~65-90 fps of GPU headroom. Another agent's
  game instance shares the GPU, so the numbers wobble.

## Known gaps

* **Material usage flags.** The Solarpunk materials are saved without `bUsedWithInstancedStaticMeshes`; in
  this uncooked editor-game build `SWCityMesh.cpp` sets the flag and recompiles at load (logs a warning). A
  packaged build needs the flag saved in the assets, or all foliage renders with the default material.
* Canopy walk continuity: the 4-storey south bars' roofs sit at 14 m, so the walk steps down there (landing
  towers connect the bridges as world.json says, but there are no stairs between roof levels).
* No interiors, doors are glazing only; market stalls/tables are simple boxes; balconies on the street side are
  sparse by design.
* Foliage is blob-based (stylised, low-poly icospheres); willow curtains read as columns from a distance.
* No lights: lanterns are emissive only (66 point lights would cost more than they show in late-afternoon light).
* The moss/meadow textures tile visibly from the air (material scale), and there are no mesh distance fields for
  runtime meshes, so Lumen GI on city geometry is screen-space only.
* Instance count is high; if perf drops, the first knobs are the drape/shrub cull distances (35 000 cm) in
  SWCityBuilding.cpp and the street-tree spacing in build_city.py.
