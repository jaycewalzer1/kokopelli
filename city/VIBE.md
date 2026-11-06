# VIBE: what it should feel like to stand in Garden Village

Read from the moodboard (`moodboard/board.json`) on 2026-11-06: all 42 kept pictures, the 7 pictures the user
removed by hand, and the intent text in `world.json` (`aesthetic`, `places[].vibe`).

**A note on the evidence.** None of the 42 kept pictures has a note. All 300 notes on removed pictures are the
same bulk "[Claude cleanup] not about the city" tag (299) or "a swamp with no built form" (1), so they say
nothing about mood. The user's own taste therefore shows in **what they kept** and in the **7 they removed by
hand with no note**. Where this file says "the user rejects X", it is inferred from those 7, not quoted.

## The feeling in one paragraph

A bright, clear **late morning in early summer**. The sky is a deep, clean cerulean with fat white cumulus
clouds. Sunlight is crisp and nearly white, not golden: colours are saturated and true, shadows are cool and
blue, and under the big old trees the light breaks into dappled pools. Everything is **soft and alive**: plants
spill over every edge, vines hang off roofs, flowers dot the green with red, pink, yellow and white. Materials
are **handmade and a little old**: bamboo, timber, stacked stone, mossy bark, with the wear left in. It is
**quiet and unhurried**: a few people, alone or in pairs, picnicking on a lawn, walking barefoot, cleaning a
solar panel; a dog in a big shady hall. There is **whimsy**: balloons in the sky, a car turned into a planter,
houses perched on a grassy hill. It feels like a Hiroo Isono painting you could walk into, kept honest by real
Singapore and Tirana buildings.

## The qualities, with the evidence

### 1. Clear cerulean sky with big white cumulus (light / weather)
* `def46dad836a`, `9ede10e3e51a`, `aa91bad1aa52` (Hiroo Isono): saturated flat cerulean, crisp white
  cumulus banks, horizon haze only at the very back.
* `a404a3a3cc94` (Ghibli 2): deep blue sea and sky, puffy cumulus row on the horizon.
* `9e668dceb256`, `a9a4dc0f1f79` (Tirana Vertical Forest): hard clear blue sky, full sun.
* `7158e81aabaa` (Coconut Club), `a7a2cd5a7035`, `3c7bfe2b7d79`, `7872720915d2`, `e929f29cc9ee`: cumulus
  piles in a blue sky in five of them.
* **Not this:** `7239c7f565fb` (removed by hand: golden, sepia, hazy AI solarpunk with the sun burning through
  smog), `652a0bb82039` (removed: sepia desert sun), `9c88b003afb3` (removed: golden back-lit ruins),
  `2786cbf7aabe` (removed: flat white overcast over a real Milan street), `f28b2e510a62` (removed: smoke and
  grey sky with a fake blue sky hung in front of it). Grey or golden-brown air is out.
* Two kept exceptions are golden (`9edadb16abc3` Kyoto sunrise, `c30540fb9286` pastel sunset): golden light
  is welcome as a *special* time of day, not as the default.

### 2. Crisp, near-white daylight; saturated, true colour (time of day / grade)
* The Isono paintings and the Supertrees (`f3a3e86b27ca`, `12c4a4ec735c`) are high-sun daylight: short
  shadows, vivid greens and purples, no orange cast.
* `28072b34a9d0` and `e942be46d019` (bamboo pavilions under trees): clean morning light, deep blue sky, warm
  bamboo glowing in sun against cool green shade.
* `b645a8fdfa9c`: "a hopeful, green vision", "feel good anime vibe": the caption is the brief.
* Current city: 18 deg late-afternoon golden sun + warm grade, which reads as a greyish, tired dusk. Wrong
  default.

### 3. Lush, overflowing, soft planting with flowers in it (density of life / wildness)
* `a9a4dc0f1f79`, `9e668dceb256`: a tree on every balcony; `623179efd1ce` (Oasia): the whole tower is creeper.
* `daade5134c59` (WOHA): curtains of vines hanging two storeys, tree ferns, planting right up to the rail.
* `7158e81aabaa`: vines dripping off a roof edge, bananas and palms at the base.
* `54011b7fbc86`, `3c9466d14b2d`: fern floors you wade through.
* Colour inside the green: `a404a3a3cc94` red geraniums and yellow flowers on a wall top; `b645a8fdfa9c` a
  meadow full of daisies, orange and blue flowers; Isono's red and pink flowering trees in every painting.
* Tended softness is welcome too: `11bb4c0ad5e2` (cloud-pruned yew hedges on a mown lawn) is the same rounded,
  cushiony language as our trees.
* **Not this:** `f75990c53ede` (removed: endless grey industrial solar field), `0f1e8862470c` (dead, brown,
  dry swamp forest).

### 4. Big old trees and dappled shade (scale / intimacy)
* `28072b34a9d0`, `e942be46d019`: huge trees over small buildings; lawn in sun, pools of shade.
* `b67659d01290`: thin trunks in front of a breeze-block facade; you see the building through trees.
* `41a7e5afcb60` (Seiken Densetsu 2 art): one giant mossy tree, tiny people at its foot.
* `aa91bad1aa52`: the city sits *inside* a park; the path winds across open lawn.

### 5. Handmade, aged, mossy materials (patina)
* `de1e4899d847`, `3d76a0d47a89`: moss and lichen on bark, close up. `8c15170e420e` (Pompeii Flora): cracked,
  green-washed plaster. `a25bc39342c8` (Coal Palace): an old hall with plants growing through the floor.
* `b4970f245701` (Corbero house): stacked rough stone wall, worn pale arches, potted cacti, a still pool.
* `90cf64448d13`, `28072b34a9d0`, `e942be46d019`: bamboo; `e929f29cc9ee`: timber stilts and decks.
* `41ce7cceb2f2`, `85a683f9f9aa` (Art Nouveau plates): sage, rose, ochre, muted teal: the palette of the
  details.

### 6. Few people, unhurried, doing ordinary things (signs of life)
* `90cf64448d13`: a lone dog in a vast bamboo hall. `28072b34a9d0`: one woman in a green sari.
  `54011b7fbc86`, `3c9466d14b2d`: one person among ferns. `46a20df40629` (Wyeth): a girl alone on a rock by the
  sea. `575a4771197a`: "barefoot on grass commute".
* `aa91bad1aa52`: tiny picnickers and dogs on a lawn. `51da750e8159`: a family cleaning solar panels, a
  child, a canal. `7158e81aabaa`: outdoor tables and chairs in the shade.
* Calm, not crowds; the scale of one person.

### 7. Whimsy and things in the sky (play)
* `aa91bad1aa52`: two hot-air balloons and birds. `775433dea919`: paragliders over the sea.
  `41a7e5afcb60`: red birds. `3c7bfe2b7d79`: birds and wind turbines.
* `5388faed0202`: an upside-down car turned into a bamboo planter. `575a4771197a`: a grass hamster wheel.
  `129473520e6f` (Shiroiya): white houses with chimneys perched on a grass hill. `b645a8fdfa9c`: old TVs in a
  flower meadow.

### 8. Water that holds the sky (water / sound)
* `b4970f245701`: a still, dark pool mirroring the arches. `a404a3a3cc94`, `aa91bad1aa52`: deep blue sea.
* `6671a04db98c`, `e929f29cc9ee`: waterfalls behind the buildings; `51da750e8159`: a canal in a field.
* world.json: "water everywhere you can hear it: runnels in the lanes feed the creek".

## What the city looks like now (polish renders) against this

* Sky: pale blue-grey gradient, no clouds. Light: low golden sun, warm grade; overall greyish, cool-dull.
* Greens: olive and dark; few flowers visible; flowering cherries and jacarandas read green from below.
* Big hard grey paving in the plazas and lanes, looking blue-grey in sky light.
* No people-scale clutter in the green; nothing in the sky.
* Pond water pale and grey, not holding the blue.

## Changes, ranked by emotional payoff per effort

1. **Time of day and sky colour** (SWEnvironment.cpp): sun up to ~42 deg, late morning from the south-east,
   near-white warm sun, deeper cerulean, haze only far away. One file, the biggest single change. *Carries 1, 2.*
2. **Grade** (SWLook): drop the golden-hour gain, a little more saturation and contrast, neutral highlights,
   slightly cool shadows; exposure re-tuned for the brighter sun. *Carries 2.*
3. **White cumulus clouds**: the board's most repeated element. Volumetric clouds if they fit the 16 ms
   budget, else cheap stylised puff clouds built from the same cushions as the trees. *Carries 1, 7.*
4. **Brighter, varied greens + more blossom**: emerald/lime leaf palette, more flowering trees and
   blossom-capped shrubs, more flower dots in the meadows and lawns. *Carries 3.*
5. **Things in the sky**: a couple of hot-air balloons and flocks of birds. Tiny cost. *Carries 7.*
6. **Warmer, mossier ground**: paving tinted warm sandstone so it stops reading blue-grey. *Carries 5.*
7. **Water holds the sky**: darker, glossier pond and creek. *Carries 8.*
8. **People-scale life on the green**: picnic blankets, chairs under trees. *Carries 6.* (People themselves
   come from the humanoid work, not this pass.)
9. Later: moss bands on wall bases, hanging vines off every roof edge, a dusk variant with real lantern light
   as a special mode (the board allows golden light as an occasion, `9edadb16abc3`).

## Done in the vibe pass (2026-11-06)

Before/after pairs: `out/city_renders/vibe/before_<view>.png` (= `polish/`) and `after_<view>.png` (= `vibe/final2/`).

| # | Change | Where |
|---|---|---|
| 1 | Sun 18 -> 40 deg, golden (1, .84, .65) -> near-white (1, .96, .90), 14 -> 11 lux; clearer air (Mie .005 -> .0025, sky luminance (.85, 1, 1.25), aerial perspective 1.5 -> 1.0) | `SWEnvironment.cpp` |
| 2 | Daylight grade: no golden gain, saturation 1.1 -> 1.12, contrast 1.06, neutral highlights, vignette .3 -> .2 | `SWEnvironment.cpp` (SWLook) |
| 3 | Volumetric cumulus `SWClouds`: engine default cloud material via a MID with coverage -0.15, scale 90, density 0.04; 30 % ray-march samples | `SWEnvironment.cpp` |
| 4 | **Flower colour fix**: foliage tint cap 1.8 -> 14 (every flower/blossom/fruit was rendering brown); new red `flame` tree (top-tier blossom only); more flowering shrubs (lanes 25 -> 40 %, tree groups 20 -> 35 %), chestnut bloom .10 -> .22, meadow flowers 5000 -> 8700 | `SWCityMesh.cpp`, `SWCityActors.cpp`, `build_city.py` |
| 5 | 6 striped hot-air balloons and 5 bird flocks (`balloons`/`birds` on `CITY_ground`) | `SWCityActors.cpp`, `build_city.py` |
| 6 | Thinner far fog (density .003 -> .002, max opacity .85 -> .55), lighter inscatter | `SWEnvironment.cpp` |
| 7 | Village green: 12 picnics (blanket, basket, cushions, parasol on every third) and 8 pairs of deck chairs | `SWCityActors.cpp` |
| tool | `vbp CITY_manager Look <json>`: live tuning of cloud params, sun pitch/yaw/intensity, saturation, contrast (not saved) | `SWCityActors.*` |

Not done / didn't work: the backdrop hills stay flat slate (lighter tints and thinner fog both had no visible effect; the
cause is something else, probably the hemisphere mesh or its material, not the fog). Warm-sandstone paving turned out
unnecessary: the new light already makes the paving cream in sun. Water left as is (it already mirrors the bright sky).
Packaging note: the cloud material lives in engine content (`/Engine/EngineSky/VolumetricClouds/`) and is referenced
only at runtime, so a packaged build must make sure it is cooked (e.g. add it to DirectoriesToAlwaysCook).
