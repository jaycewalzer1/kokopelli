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
walk and a sky bridge, creek/pond (ground + aerial), the Commons (aerial + plaza), parkway, food forest, plus
(polish pass) `canopy_raised` (raised deck over a 14 m roof), `market_street`, `landscape_north`, `willow_bank`.
Reference sets: `out/city_renders/final/` (before the polish pass) and `out/city_renders/polish/` (after).

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
| `SWCityGround` | `CITY_ground` | city ground slabs, plaza paving, meadow blotches (macro variation), flowers |
| `SWCityGround` | `CITY_landscape` | the surroundings: field patchwork, hedgerows, backdrop hills (`"gi": false`) |
| `SWCityOpenSpace` | `CITY_space_commons_plaza` | kind `plaza`: `props` list (stalls, sails, pool, planter benches, bikes, lights, tables, kiosks, flower beds) |
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

## Polish pass (Nov 2026)

* **Canopy walk is continuous at 17.5 m.** `build_city.py` computes each walk bar's deck line (`deck_line_cm`,
  mirroring the C++ setbacks) and the join points inside each block: where an E/W bar's deck meets a N/S bar,
  where a landing tower stands, where a bridge lands (`deck_spurs_cm`, `terrace_gaps_cm`). In C++:
  * roofs at walk level: deck down the roof as before, plus gaps in the edge and end planters where spurs/neighbour
    decks arrive (bridges used to hit a planter wall);
  * roofs below it (the 14 m / 10.5 m south bars, birch W/E): a **raised boardwalk on posts** at walk level
    (glulam edge beams, knee-braced posts, slatted balustrade, hung planters with trailing plants, pergolas,
    a stair down to the roof garden), kept to the court side so it clears the landing towers;
  * 6-storey bars (top floor at 17.5 m): **open loggias** through both ends of the top floor, both 17.5 m terraces
    become walk decks, and short decks bridge from the terrace to the neighbour's roof. Upper collision now leaves
    terraces and loggias walkable. The Commons landings still connect only by their lifts (no deck between them).
* **Foliage.** New shared primitives `Puff` (cushion with flat underside), `Fringe` (9 hanging strands), `Cone`
  (stacked conifer skirts). Species shapes: layered broadleaf (2 tiers, darker below), spreading (cherry/jacaranda,
  green lower tier), willow (dome + two rings of fringe curtains to ~0.6 m above ground), columnar (birch, poplar,
  pawpaw), conifer (cypress), bamboo clumps, orchard (apple/persimmon with fruit dots, "fruit" with blossom),
  small roof trees, `copse` for hedgerows. `"<species>@far"` = 2-instance distant tree. Balcony/terrace "drapes"
  are fringe curtains (no more grape bunches). Tints are quantised (3 brightness levels): every distinct tint is
  its own instanced component, and per-cushion random tints had produced 10 k components.
* **Facade styles per block** (`STYLES` in build_city.py -> `st_*` fields): timber tone, wall core (timber / lime
  render on the earth material / rammed earth), bay width, window ratio and tall French windows with rails,
  balcony type (`bosco` deep staggered, `gallery` continuous planter ledges, `sparse`, `default`), vertical-garden
  strips, fins (timber / copper / none), and the 21 m roofs' profile (`gable` sedum+PV, `sawtooth` north-light PV,
  `pavilions`). Window/railing glass uses `Scale` 5 (material Scale override; `GetMaterial(Mat, Tint, Scale)`), so
  the PV grid no longer reads at distance; the bridge and terrace glass rails became timber slats.
* **Commons plaza**: a market street of 14 stalls under festoon lights between the market hall and the
  amphitheater, three shade sails over the chess garden, a reflecting pool with jets on the east lawn, planter
  benches, cafe tables, kiosks, bike parking, flower beds (placed greedily on free paving). Bike racks in the
  street furniture now hold bikes; lantern posts carry hanging baskets.
* **Ground and surroundings**: meadow blotches of different tints/scales over the parkway and creek corridor;
  `CITY_landscape` covers the 4 km floor with a field patchwork (flat colour `Plain` material: textured
  materials tiled visibly at field scale and cost shading), hedgerows with copses (shadows only within ~500 m,
  culled past 1.7 km far out), poplar windbreaks, orchards, woods, and two rings of backdrop hills hiding the floor
  edge. Far landscape trees (`CITY_trees_far`) have no shadows, no GI and a 1.7 km cull.

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

## Measured after the polish pass (M4 Max, 1280x720, Lumen + VSM)

* Build: 259 actors, spawn 0.2 s, Configure 1.8-2.4 s, total 2.1-2.6 s. C++ incremental compile ~10 s, relaunch ~10-20 s.
* ~12.2 M triangles (estimate), 154.8 k instances, 3734 components (was 16.4 M / 205.6 k / 2301).
* Captures: 0.17-0.23 s per 1280x720 lit PNG (25 views).
* GPU frame time is **not stable across a session**: the same scene read 16.4-16.8 ms (aerial overview) right
  after a fresh launch + full build, and 10.7-15.1 ms minutes later / after other work (the window is vsync
  capped and the GPU clock scales). Same-protocol comparison right after launch: old code 11.6-12.3 ms aerial,
  12.3 ms street; polish pass 16.4-16.8 ms aerial, 10.9-12.5 ms street. Attribution (destroy one group at a
  time, fresh): landscape ~1.2-2.3 ms, landscape trees ~0.5-1.7 ms, courtyards ~1.4 ms, street trees ~0.2-1.1 ms.
* A pitfall when measuring: destroying actors without `vset /action/clean_garbage` and then re-spawning the same
  names gave implausibly cheap numbers (probably the re-spawned actors weren't rendering; not verified). Measure
  after a full `build_city.py`, and compare numbers taken at the same point after a launch.

## Measured before the polish pass (M4 Max, 1280x720 window, Lumen + VSM)

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
* Canopy walk: continuous inside every block; between the two Commons landings there is no deck (lifts only).
  The raised decks' stairs are a single flight with no landing; loggia posts are simple timber.
* No interiors, doors are glazing only; balconies on the street side are sparse by design.
* Foliage cushions are big and smooth close up (the foliage material's texture reads as "cabbage" at 2 m);
  crowns were cut from 3 tiers to 2 for frame time.
* No lights: lanterns are emissive only; a dusk variant with real lights was not done.
* Fields are flat colour (no crop rows); hills are smooth hemispheres that read blue-grey through the haze.
* No mesh distance fields for runtime meshes, so Lumen GI on city geometry is screen-space only.
* **Frame time varies with session state** (see Measured). Knobs, in order: `cull_cm`/count of `CITY_trees_far`,
  hedgerow `step`/density in `plan_landscape`, crown tiers in `AddTree`, drape/shrub cull distances (35 000 cm).
