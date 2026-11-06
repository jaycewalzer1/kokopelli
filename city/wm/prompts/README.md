# Prompts for the sim-to-real world model

The world model (Cosmos3-Nano-Sim-Transfer, or base Cosmos3-Nano through `world_filter.py`) gets two things: **controls**
rendered from SimWorld (depth, segmentation, edges, blur) and a **text prompt**. The controls decide *where things are*.
The words decide *what they are made of and how the light falls*: timber or plastic, real bougainvillea or green blobs,
crisp noon or golden haze. So the prompt is where the city's look lives, and it has to describe the same shapes the
controls show, or the model gets two conflicting instructions and the picture breaks up.

## Files

| File | What it is |
|---|---|
| `bridge.json` | The sky-bridge shot (`out/filter_test/test_clip/`): three variants, each with `prompt` (send this), `caption` (the same as an object), `reasoning`, `tokens` and `carries` (for each sentence: the VIBE.md qualities, kept moodboard images and part of the sim frame it matches). Also `negative_prompt` and notes on where a negative prompt works. |
| `bridge_source.py` | Where the bridge text is written. Edit sentences here and rerun it; don't edit `bridge.json` by hand, because `prompt` and `caption` must stay identical. |
| `build.py` | Builds a first draft for a new shot from a short shot description plus world.json place ids. `--check FILE` reports banned words and token counts. |

## The format the model expects

NVIDIA trained on long **structured captions** written by an LLM ("upsampled" prompts), sent as one JSON string. See
`models/Cosmos3-Nano-Sim-Transfer/assets/sample_data/example1/example1_upsampled_prompt.json`. Fields: `subjects`
(each with description, appearance_details, location, relative_size, orientation, and the empty person fields),
`background_setting`, `lighting` {conditions, direction, shadows, illumination_effect}, `aesthetics` {composition,
color_scheme, mood_atmosphere, patterns}, `cinematography` {camera_motion, framing, camera_angle, depth_of_field, focus,
lens_focal_length}, `style_medium`, `artistic_style`, `context`, `text_and_signage_elements`, `resolution`,
`aspect_ratio`, `duration`, `fps`. Their two examples are 980 and 1,266 tokens. For the transfer example NVIDIA removed
`actions` and times, since the control video already carries the motion; we do the same.

The model also gets a fixed system sentence, set in `world_filter.py`: "You are a helpful assistant that generates
images or videos following the user's instructions and control signals (edge maps, blur, depth, or segmentation)." Don't
repeat or fight it in the prompt.

**Negative prompts.** Sim-Transfer is distilled to 4 steps with guidance built in, so it has no negative branch and a
negative prompt does nothing. The base model through `world_filter.py` does use one (guidance 3.0), read from
`models/Cosmos3-Nano/assets/negative_prompt.json`; `world_filter.py` has no flag for another one yet. `bridge.json`'s
`negative_prompt` is that stock file plus our own failure modes (game render, illustration, blob foliage, golden or
grey haze), ready for when it does.

## Recipe for a new shot

1. **Look at the sim frames** (first, middle, last, and every head turn; `head.jsonl` gives the yaw). List what is in
   frame and where: foreground, left, right, far, sky. Only name what the controls contain. A bench where the depth
   map shows empty paving makes the model fight the control and flicker.
2. **Name each shape as a real thing.** A smooth green cushion becomes "a tightly clipped clump of small-leaved
   evergreen"; a pink blob becomes "bougainvillea in full magenta flower". Use real species and real materials.
3. **Say how it has aged.** Timber silvering at the ends, oak darkened by hands, verdigris with rain streaks, moss in
   joints. Wear is what separates a photograph from a clean game asset (VIBE.md quality 5).
4. **Fix the light in camera terms**: time of day, where the sun is (match the shadows in the sim render), shadow
   quality, "near-white, not golden" (VIBE.md 1 and 2).
5. **Keep people far away and few**, where depth is coarse (VIBE.md 6). If no one is in the sim, say the near space is
   empty.
6. **Describe the camera**: walking height, lens from the FOV (90 deg horizontal on 16:9 is about 18 mm full frame),
   handheld bob, which way the head turns.
7. **Never use style or genre words.** "Solarpunk", "futuristic", "festoon lights", "balloons" and "lush" pulled an
   earlier test toward illustration. Physical words carry the vision better. `build.py --check` enforces the list in
   `BANNED`.
8. **Make three variants**: full (about 1,000-1,400 tokens), light (under 512, in case long text fights the controls or
   the distilled model's 512-token text cache cuts it), and a phone-video one. Run all three on the same seed and
   compare.
9. **Write down what each sentence carries** (`carries`), so when a run looks wrong you can tell which sentence to blame.

## Using build.py

Write a shot description, for example:

```json
{"id": "commons_plaza", "duration_s": 3, "fps": 16, "size": [448, 256], "time": "late morning",
 "sun": "High sun from the left, behind the camera",
 "setting": "A small paved square between low civic buildings, seen at walking height.",
 "places": ["market_hall", "chess_garden", "library"],
 "in_frame": [
  {"what": "A timber vaulted market hall with a wide open front, long tables and food stalls inside.",
   "where": "Left half of frame", "size": "Large", "places": ["market_hall"], "vibe": [5]},
  {"what": "A terrace of stone chess tables under two old plane trees.", "where": "Centre right",
   "size": "Medium", "places": ["chess_garden"], "vibe": [4, 6]}],
 "people": "Three or four people at the chess tables, one walking a dog.",
 "camera": {"motion": "Slow walk forward, looking straight ahead",
            "composition": "Eye-level view across the square toward the hall", "mm": 22},
 "colors": "Rose earth, verdigris copper, honey timber, green leaves, blue sky",
 "context": "A late-morning walk across a market square in a small green town."}
```

then `.venv/bin/python city/wm/prompts/build.py shot.json --mode full|light|phone --out out.json`. `places` and
`in_frame[].places` are ids from world.json (buildings, places, cells, landscape, sky bridges, lanes). Their materials
and block palettes become physical words through the `PHYSICAL` table ("verdigris" becomes "copper weathered to
blue-green verdigris"). The sky, light, planting and wear sentences come from `VIBE_LINES`, and the moodboard ids in
`carries` are read from VIBE.md. The output is a first draft: read it against the frames, and rewrite anything generic
(the bridge prompt is the standard to aim for).
