# Building kinds for the varied city

Goal (the user, 2026-11-07): replace the seven cloned courtyard blocks (28 near-identical bars) with **variety**: a
mix of buildings from the moodboard (`city/moodboard/board.json`, kept images; `city/VIBE.md`) and famous
**mid-century modern** buildings, re-imagined for a lush solarpunk village. The **Commons civic buildings** (market
hall, library + observatory dome, bathhouse) are what the user thinks looks really good: they are the quality bar,
and they stay untouched. Reference renders: `out/city_kinds/_reference/` (commons_aerial, commons_plaza,
market_street; aerial_overview shows the clone problem).

## How a kind works

* One Python module per family in this folder exports `KINDS = {"name": build_fn}` and `SIZES = {"name":
  {"w": (min, max), "d": (min, max), "h": (min, max), "floors": (min, max), "use": "homes|shops+homes|..."}}` so the
  planner can fit kinds to plots.
* `build_fn(plot) -> Kit` draws in the plot's **local frame in metres**: x along the street (0..plot.w), y away from
  the street (0..plot.d, front line at y = 0), z up. `kit.py` documents every op (box, obox, beam, cyl, pole, prism,
  ribbon, ell, gable, vault, slope, quad, tri), instanced plants (`plant`) and collision (`solid`).
* It must fit **any** size within its SIZES range (stretch bays/modules, don't scale the whole thing), stay inside
  the plot (planting may touch the edge), keep the building under `plot.h_max` (trees and planting may rise up to ~8 m above it), and be deterministic from `plot.seed`
  (`plot.rng`). Use `plot.palette` (3 sRGB colours of the block) for accents so a kind looks different in each block.
* The C++ side (`mac_server/.../City/SWCityKit.cpp`, class `SWCityKit`) is generic: **do not edit C++**. If a kind
  truly needs something the kit can't express, write it in your notes for the integrator.

## Previewing (the one editor)

    ~/Desktop/kokopelli/simworld/.venv/bin/python -m city.ue.kinds.preview --kind NAME --w 30 --d 20 --h 12 --seed 2
    ~/Desktop/kokopelli/simworld/.venv/bin/python -m city.ue.kinds.preview --kind NAME --w 30 --d 20 --json-only   # no editor

Renders front / front_r / aerial / back / eye views to `out/city_kinds/NAME/<time>_<w>x<d>/`, then **look at them**
(Read the PNGs; tile them with PIL to save context). The editor on **port 9003** serves one client at a time;
the preview takes a file lock (`out/city_kinds/.editor.lock`) for about a minute, so several agents can preview
safely: never connect to 9003 any other way while you work, never kill or relaunch the editor, never touch port
9001 or `mac_server/Packaged/`. If the editor is down, say so in your notes and keep authoring with `--json-only`.

## Budgets (the whole city must stay < ~25 ms GPU)

* Per building: under ~4,000 ops and ~600 plant instances; one slot per (material, tint), so reuse slots (each
  slot is one draw call; aim for <= 12). Don't model what can't be seen from the street or the canopy walk at
  17.5 m (interiors: a dim back wall plane and a few warm "lit" boxes behind glass sell it).
* Planting is the moodboard's soul: balconies spill (Puff + Fringe), roofs are green, flowers in the green.

## Materials that read well (from the existing city)

Timber (warm, tint it), RammedEarth (plaster/render/painted walls when tinted; earth when warm), PermeableStone
(concrete, terrazzo, stone; brick when tinted red), SolarGlass (glazing: opaque dark blue-grey and ignores tint, so a lit room only shows through an OPEN or missing
pane: draw a warm back wall + Lantern pendants behind a gap; dim Lantern panes read as solid orange), Metal (white = painted steel, dark = mullions; green tint = old copper), Fabric (flat
coloured panels, e.g. Eames House infill), GreenRoof, Foliage. Materials are world-projected: no UVs needed.

Learned in the overnight run: Plain gives crisp white/black (Metal tinted white renders tan); SolarGlass at scale 0
shows a PV grid, scale 400 gives smooth window glass; Fabric is striped and RammedEarth shows strata even when tinted;
each (prim, material, tint) of plants is its own component, so draw foliage colours from a small fixed set.

## Your output

* Kind module(s) in this folder (only your own files; don't edit other agents' modules, `kit.py`, `preview.py` or
  `__init__.py` — ask the integrator in notes if the shared kit needs something).
* `out/city_kinds/<family>/NOTES.md`: each kind, its reference (moodboard image ids, real building + architect +
  year), what it does well, what still looks off, its best preview folder.
