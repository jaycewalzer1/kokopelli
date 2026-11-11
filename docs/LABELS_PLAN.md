# Plan: optional object labels on top of segmentation (Sim-Transfer, MLX)

**Status:** plan drafted 2026-11-10 against `main` @ "Pin total memory in the memguard give-way test". Milestones 1, 2, 4
and 5 are built on branch `feat/object-labels` (code and tests, no model run yet). See "Build status" below; the plan
itself follows unchanged.
**Goal:** any SimWorld actor *can* carry a text label ("red latex balloon on a thin white string"). The label rides along
with the seg control into Cosmos3-Nano-Sim-Transfer, so that region gets painted as that thing and keeps being that thing
frame after frame. No label = today's behavior, bit for bit.

**Verdict:** this repo is unusually well set up for it. You own the attention code (`kokopelli/wm/world_transfer.py`
`Generator.__call__`), so the "real" fix (each labeled region gets to read its own label's words) is a mask on one
`scaled_dot_product_attention` call, not a fine-tune. Plan: plumb labels through capture first, put them in the caption's
`subjects` (cheap baseline), build a Qwen3-VL label checker, then add the regional attention mask. Fine-tuning stays off
the table unless the mask fails a clear gate.

---

## Build status (2026-11-10, branch `feat/object-labels`)

Everything below is code plus tests on synthetic data and the tiny fake model; the one real-data check
was the no-GPU half of a paint (label pass, caption, tokenizer spans, regions, mask) on the bridge clip.

**2026-11-11, first real paints:** the ambiguous-circle test (`experiments/labels/README.md`). One plain disc in the seg
control came out as a stone sphere with no label, a soccer ball or a pumpkin under those labels, steady for 93 frames,
caption-only and masked alike. So Tier A works for a single object and the masked path runs on the real model; what the
mask adds is still unmeasured. Milestones 3 and 6 on the regression clip are still not run.

The plan's line numbers are `main`'s. On this branch `world_transfer.py` has grown: the target's attention is at
lines 313-316, `patchify` at 355, `tokenize` at 142, `text_cache` at 225, the store pass at 501.

| # | Milestone | State |
|---|---|---|
| 0 | Read-through + decisions D1-D5 | Leans confirmed by the owner 2026-11-11 ("solid"), each one a flag or a one-line change (table below). Section 9's prediction: "idk" |
| 1 | Label colours in capture, `labels/` pass, `labels_meta.json` | Code done: `SimWorldConfig.label_actors`, `kokopelli/wm/labels.py build`, `capture.py --labels`. **No regression clip:** it needs the Unreal server and the sphere stand-ins |
| 2 | Label checker + calibration | Code done: `kokopelli/wm/label_check.py`. **Not calibrated:** needs 50 hand-sorted crops and a Qwen run |
| 3 | Baseline: no labels vs Tier A | Not run (needs the clip, the GPU queue, and your prediction, section 9 question 4). Tier A is `--label-steps 0` |
| 4 | Spans, regions, mask + unit tests | Done: `kokopelli/wm/labels.py`, `tests/wm/test_labels.py` |
| 5 | Mask in `Generator.__call__`, bit-identical test, runner flags | Done on the fake model: `tests/wm/test_label_paint.py`. No real masked paint yet |
| 6 | Ablation slice | Not run. Commands: `experiments/labels/README.md` |
| 7 | Gate B, then `world_transfer_multi` and `world_stream` | Not started, on purpose: the plan ports only after B passes |

### How the leans were built in

| Decision | Built as | To change it |
|---|---|---|
| D1 where labels live | `labels.json` keyed by actor; an entry may give `world_id` instead and `labels.load(path, actors)` resolves it through an id -> actor table | Nothing reads world.json yet; pass the table when one exists |
| D2 hard or soft | Both: `--label-mode hard\|soft --label-beta` | Flag |
| D3 "balloon" is banned | (c): a label may carry a banned word. The sidecar lists them per label and sets `banned_words_reach_whole_frame` when the mask isn't a hard one (Tier A, soft) | `labels.Paint.report` |
| D4 max labels | 6, heroes first then mean area: `--label-max` | Flag |
| D5 mask the store pass | Off by default: `--label-store` turns it on | Flag |

### Where the build differs from the plan

- **The runner compiles the caption, not `prompts/build.py`.** `world_transfer.py --labels` appends the label subjects to
  the structured caption itself, for the frames it is about to paint. Tier A and Tier B are then the same command and
  the same caption, differing only in `--label-steps`, and the runner knows exactly where each label's words sit.
  `build.py` is unchanged. A plain-text prompt with labels is an error.
- **Token coverage is taken over a token's real pixels.** With an odd latent height or width the last row or column of
  tokens is half zero padding; no token is all padding. The padded half is left out of the share instead of counting
  against it.
- **A label with no token in a latent frame is read by nobody in that frame** (hard) or pushed down for everyone (soft),
  so an off-screen object's words can't act on the picture.
- **`labels_meta.json` also has a box per frame** (the checker crops from it) and remembers the actor order the frames
  were built with; a paint or a check refuses a `labels.json` whose order has changed since.
- **An entry with a `class` and no `label` is watched only:** it gets a mask colour and a checker score and is never
  named in the caption. That is how "the unlabeled ball next to the balloon" (neighbor leak) is measured.
- **The checker allows for the batch paint's 3-frame lag** (`docs/SIM_TRANSFER_MLX.md`, deviation 8): painted frame
  i + 3 is cropped with clip frame i's mask. `--lag 0` for stream films.
- **`leak_guard` is not wired in.** It lives in `kokopelli/loop`, which `kokopelli/wm` may not import, and it needs the
  life's clock. It belongs where the live loop hands labels to the stream (milestone 7).
- **The manifest's `labels` field is only present on labeled paints**, so existing sidecars keep their shape.

### Found while building

- **A label costs about 114 text tokens**, almost all of it NVIDIA's empty subject fields: two labels took the bridge
  caption from 1,453 to 1,681 tokens. Six would add about 680. The label's own words are about 15 of those.
- **The text is encoded causally**, so every caption token after a label has already read it. The mask stops picture
  tokens from reading the label's own keys, not from reading what later text keys absorbed from it. D3(c) holds at the
  attention, not absolutely.
- **MLX's attention with an all-zero mask is bit-identical to no mask**, and hiding keys with -inf matches deleting them
  to bf16 rounding (2% of the mask's effect through all 36 layers of the fake model). No timing yet (section 4.2g).
- **For the stream (milestone 7):** recompiling the caption per chunk changes its token count, and the position clock is
  `text length + margin + f * stride`. History keys already carry the old clock, so the text length used for positions
  has to stay fixed when the caption changes.

---

## 0. Big picture: why seg alone can't say "balloon"

What the model gets today (see `kokopelli/wm/controls/prompts/README.md`):

- **Controls say where.** `controls.py` builds `seg.mp4` from UnrealCV `object_mask` split by material, painted with
  **random** colours (`Palette`, `controls.py:144`), because that's how NVIDIA trained it (`generate_distinct_colors`).
  So a seg colour carries zero meaning. Blue doesn't mean "balloon" and never can with the stock weights.
- **Text says what.** One structured caption (NVIDIA's upsampled JSON: `subjects`, `lighting`, ...) is encoded once by
  the understanding pathway (`text_cache`, `world_transfer.py:189`) into per-layer keys/values.
- **The link between them is attention.** Every latent token of the frame being painted attends to *all* text tokens
  equally (`world_transfer.py:275-278`). A round blob in the seg map reads "balloon" and "soccer ball on the lawn" with
  the same access. It picks whichever its prior likes for that shape and place.

So your idea (a label placed on objects in addition to segmentation) is exactly right, but the label can't live *in*
the seg video. It has to be a second channel that says "these tokens, these words". The attention mask is that channel.

### Facts from the code that shape every decision below

| Fact | Where | Consequence |
|---|---|---|
| VAE is 16x spatial, 4x temporal; `patchify` packs 2x2 latents into one token | `docs/SIM_TRANSFER_MLX.md:17`, `world_transfer.py:317` | **One token = 32x32 px, 4 frames.** 832x480 is a 26x15 token grid (390 tokens). 448x256 (the stream default) is 14x8 (112 tokens) |
| Target attends over `[text \| history... \| itself]`, one SDPA per layer, 36 layers, 32 Q heads / 8 KV heads | `world_transfer.py:255-278` | One place to add a mask (plus its twins in `world_transfer_multi.py:145` and `world_stream.py:243`) |
| 4 fixed denoise steps, sigmas `[1, 15/16, 5/6, 5/8]`, guidance baked in | `world_transfer.py:381`, `prompts/README.md` | "Mask only early steps" means 1-2 of 4 steps, not a percentage. **Negative prompts do nothing here** (correction to my earlier general plan) |
| Text is encoded once, causally, chat-templated | `tokenize` `world_transfer.py:127`, `text_cache:189` | Label words can sit inside the normal caption; each label's token span is visible to the whole earlier caption, which is good |
| Seg mask colours for tracked actors are set and read back over UnrealCV | `simworld.py:330`, `simworld_commands.py:44` | The actor -> mask colour map already exists, it just only covers tracked actors |
| Sim-Transfer is single-control; Variant A multi-control is an untrained combo | `world_transfer.py:41`, `world_transfer_multi.py` | Labels must work with seg alone first; multi-control is a second axis, don't mix them in the first experiments |
| `BANNED` includes "balloon", "balloons" | `prompts/build.py` | Real conflict, see Decision D3 |
| Each model peaks ~18 GB, Cosmos and Qwen can't co-reside | `kokopelli/wm/README.md` | The label checker runs after a paint (or between chunks with unload), never inside the loop |

**Size floor (read this twice).** A region needs roughly 2x2 tokens (64x64 px) to be reliably steerable. A 40 px balloon
at 832x480 covers 1-4 tokens: marginal. The same balloon in the 448x256 stream is ~22 px: under one token, so no method
in this plan will reliably fix it there. Labels are for objects that are big on screen, or for offline 832x480 paints.

---

## 1. Data contract

### 1.1 Where labels are written: `labels.json` (per world or per shot)

```json
{
  "version": 1,
  "labels": [
    {"actor": "GEN_BP_balloon_0", "label": "red latex balloon on a thin white string, slightly wrinkled near the knot",
     "class": "balloon", "priority": "hero"},
    {"actor": "GEN_BP_ball_2", "label": "black and white leather soccer ball, scuffed", "class": "ball"}
  ]
}
```

- Keyed by UnrealCV actor name, because that's the key the mask colour map already uses.
- `label` optional by definition: actors not listed get nothing. `class` is a short noun for the checker and confusable
  lists. `priority` decides who wins when a frame has too many labels (cap per latent frame, D4).
- Labels are strings that reach a model, so they go through `kokopelli/loop/leak_guard.py` like every other prompt.

### 1.2 Capture: actor -> mask colour for labeled actors

`_setup_mask_colors` (`simworld.py:330`) only colours tracked actors. Extend it to also assign fixed colours to every
actor in `labels.json`, then read them back (readback is what the mask actually uses). Store in the capture sidecar
next to `mask_colors`. Same colour scheme, just a longer list. Test with `tests/loop/fake_unrealcv.py`, which already
fakes `vset/vget /object/{name}/color`.

### 1.3 New pass: `labels/NNNN.png` + `labels_meta.json`

Next to `rgb/`, `depth/`, `segmentation/` in the clip folder:

- `labels/NNNN.png`: 16-bit PNG, 0 = unlabeled, k = index into `labels.json` order. Built from `segmentation/NNNN.png`
  by exact colour lookup against the readback colours. **Lossless PNG, never mp4**: one colour bleed from H.264 and
  the balloon's mask eats its neighbour.
- `labels_meta.json`: which labels appear in which frames, pixel area and centroid per frame. The prompt compiler and the
  checker both read this.

`controls.py` keeps writing `seg.mp4` exactly as now. Labels are a sidecar, not a change to the seg control.

### 1.4 Manifest

`manifest.py:69` gets a `labels` field (hash of `labels.json`, label count, mask settings), so every painted video says
which labels it was painted with.

---

## 2. Tier A: labels into the caption (no model change)

`prompts/build.py` already emits NVIDIA's structured caption with a `subjects` list where each subject has
`description`, `location`, `relative_size`. That is literally a per-object slot. Compile labels into it:

- One subject per visible labeled actor (cap N, sorted by priority then area).
- `location` from the centroid in `labels_meta.json`, in the caption's own words ("upper left of frame, above the lawn").
- `relative_size` from area ("small, about a hand's width in frame").
- Recompile per shot (batch) or per chunk (stream) using only labels visible in that span.

This is the baseline every later tier must beat. Expect it to help large hero objects and do little for two similar
round things in one frame, because location words are weak and every token still sees every word.

---

## 3. The label checker (build it before Tier B, it's the scoreboard)

New `kokopelli/wm/label_check.py`, CPU-side except the VLM call, shaped like `video_check.py`:

1. For each labeled actor, every 4th frame (one per latent), crop the painted frame to its mask bbox + 25% padding.
2. Ask Qwen3-VL-8B (`llm_model.ask(prompt, images)`) a forced choice: `{label class}` vs its confusables vs "other",
   answer with one word. Confusables come from a small hand table (balloon: ball, orange, lamp globe, fruit) plus, once,
   asking Qwen "what could this be mistaken for", cached per class.
3. Score per actor = fraction of sampled frames answered correctly. Also record **flip count** (how often the answer
   changes across frames: that's the "turned into a ball halfway through" bug).
4. Run after the paint with Cosmos unloaded. Write `<output>.labels.json` next to the existing sidecar.

Calibrate first: 50 hand-labeled crops (some real balloons, some real balls) to see how often Qwen is wrong on its own.
If it's above ~10% wrong, the checker is the bottleneck, not the world model.

---

## 4. Tier B: regional attention mask (the actual fix)

### 4.1 What changes, in one sentence

When a target token at grid cell (y, x) attends, it may see the words of label k only if (y, x) is inside label k's
region in this latent frame; everything else (global caption, history, itself) stays visible to everyone.

### 4.2 Pieces

**a. Label token spans.** Tokenize the chat string with `return_offsets_mapping=True` (same tokenizer as `tokenize`,
`world_transfer.py:127`) and find each label subject's `description` substring. Output: for each label k, a list of text
key indices `[s_k, e_k)`. The `ids` order and positions are unchanged, so RoPE and the text cache are untouched.

**b. Region masks per latent frame.** Latent f covers frame 0 (f = 0) or frames 4f-3..4f. For each label, coverage of
token (y, x) = mean over those frames of the fraction of its 32x32 pixel block inside the label mask. Region = tokens
with coverage >= tau (start 0.25). If a visible label gets zero tokens, give it its single best token (so small objects
get *something*). Padding tokens from `patchify` (odd latent h or w) are never in a region. Order tokens exactly as
`patchify` does (row-major over hp, wp); write a test that patchifies an index image and checks the order.

**c. The additive mask.** Shape `[1, 1, N, K_total]` where `K_total = L_text + history + N`. All zeros, except: for each
label k, columns `[s_k, e_k)` get `-inf` in rows of tokens outside region k. (Option D2: soft version uses `-beta`
outside and `+beta` inside instead of a hard wall.) Global caption columns never masked, so no row is ever all `-inf`.

**d. Where it's applied.**

| Pass | Apply? | Why |
|---|---|---|
| Target denoise steps 1..S (S in {1, 2, 4}) | yes | Identity is decided at high noise |
| Target denoise steps after S | no | Lets lighting and edges blend across the region border |
| Clean R_f store pass (`world_transfer.py:448`) | ablate (D5) | Its K/V become history. Masking it bakes identity into the cache the next frames read |
| Control C_f pass | no (first) | The control pass reads the seg map; leave it as trained |

**e. Code touch points.**
- `world_transfer.py` `Generator.__call__`: add `mask=None`, pass it to the SDPA at line 277. None = today.
- `world_transfer_multi.py` `MultiGenerator.target` (line 120/145): same mask per branch (the text span columns sit at
  the same offset in each branch's key list).
- `world_stream.py` `_paint_latent` (line 243): build the mask per latent from the pushed label frames. The stream's
  `push(controls)` grows an optional `labels` array.
- New `kokopelli/wm/labels.py`: span finder, region builder, mask builder. Pure numpy + tokenizer, testable without MLX.
- CLI: `--labels labels.json --label-frames clip/labels --label-steps 2 --label-tau 0.25 --label-mode hard|soft`.

**f. Tests.**
- `tests/wm/test_labels.py`: token order matches `patchify`; tiny object gets one token; padding never selected;
  spans found for every label; rows never all masked.
- No labels -> bit-identical to `world_transfer.run` on the tiny fake model (same pattern as
  `test_wm_multicontrol_a.py`'s N=1 check).
- A label covering the whole frame with mode hard changes nothing vs no mask (every row may see every column).

**g. Cost.** One extra additive mask per SDPA in 36 layers for S of 4 steps. MLX's fused SDPA with an array mask may be
slower than without; measure seconds per latent against `docs/PAINT_PROFILE.md` numbers before and after.

### 4.3 Ablations (one seed set, the regression clip)

S in {1, 2, 4} x mode {hard, soft beta 2, soft beta 5} x store-pass {masked, unmasked} x tau {0.1, 0.25, 0.5}.
Start with the 6-run slice S in {1, 2} x mode {hard, soft 5} x store {masked, unmasked} at tau 0.25; widen only if it
moves.

---

## 5. Tier C (only if B fails its gate): learn it

Short version, details when needed: LoRA on the generation pathway's attention (`add_q/k/v_proj`) with the region mask
always on and label dropout (30-50% of labels removed per sample, 10% all removed) so unlabeled behavior stays trained.
Data from SimWorld renders with labels plus real clips auto-labeled (SAM2 masks + Qwen captions) for the photoreal side.
This is a PACE job, not a Mac job (`kokopelli/ops/cloud/pace.py`).

---

## 6. Evaluation

**Regression clip** (`out/labels/regression/`): 5 s plaza shot with, in frame together, 2-3 balloons, 1 soccer ball,
2 lantern-post globes, 1 fruit tree. Balloons and balls aren't in SimWorld's asset images, so spawn simple stand-ins
(sphere actors scaled and tinted) via `spawn` commands; the shape ambiguity is the point. Capture at 832x480 and
448x256, three object sizes.

**Metrics** (all in `<output>.labels.json`):

| Metric | Catches |
|---|---|
| Label accuracy per actor (checker) | balloon -> ball |
| Flip count per actor | identity changing mid-clip |
| Neighbor leak: checker on the *unlabeled* ball next to a balloon | "balloon" bleeding onto the ball |
| Unlabeled-region change vs no-label run (pixel distance outside all regions, `pixel_distance.py`) | labels breaking the rest of the frame |
| `video_check.py` mosaic/drift scores | the mask causing blocky borders |
| Seconds per latent | cost |

**Gates**
- Tier A done when baseline numbers exist. No pass/fail, it's the reference.
- Tier B wins if label accuracy beats A by >= 15 points on hero objects at 832x480, flips drop, unlabeled change and
  mosaic scores don't get worse. Kill if borders show visible seams in every setting or the store-pass variant smears
  identity into neighbors over time.
- Tier C only if B < 85% accuracy on objects >= 2x2 tokens.

---

## 7. Milestones

| # | Milestone | Output | Rough time |
|---|---|---|---|
| 0 | Read-through (section 9) + decisions D1-D5 | answers in this doc | 1 evening |
| 1 | Label colours in capture + `labels/` pass + `labels_meta.json` | regression clip with labels | 2-3 days |
| 2 | Label checker + calibration on 50 crops | `label_check.py`, checker error rate | 2 days |
| 3 | Baseline: no labels vs Tier A caption subjects | first numbers | 1 day |
| 4 | `labels.py` (spans, regions, mask) + unit tests | green tests, no MLX needed | 2 days |
| 5 | Mask in `Generator.__call__`, bit-identical test, batch runner flag | first masked paint | 2 days |
| 6 | Ablation slice (6 runs) | table in `experiments/labels/README.md` | 1-2 days of queue |
| 7 | Gate B. If pass: port to `world_transfer_multi` and `world_stream` | labels in the live loop | 2-3 days |

---

## 8. Decisions (your call; options and tradeoffs, my lean is folded under each)

**D1. Where labels are authored.**
(a) `labels.json` keyed by actor name: simple, works today, but actor names change when the world regenerates.
(b) A `label` field on `world.json` entries (`street_furniture`, `places`...): survives regeneration, but not every
actor comes from world.json. (c) Unreal actor tags in `mac_server`: labels live with the asset, but needs a new
UnrealCV query and Unreal-side editing.
<details><summary>lean</summary>(a) now, with a resolver that also accepts world.json ids, so (b) slots in later without changing the mask code.</details>

**D2. Hard wall or soft bias.**
Hard (`-inf`): strongest, can leave a seam where a region's tokens stop reading the label. Soft (`+/-beta`): gentler
borders, may be too weak to beat the prior on confusable shapes.
<details><summary>lean</summary>Run both in the first slice; the checker decides. Hard first, because if hard doesn't fix it, soft won't.</details>

**D3. "balloon" is in `BANNED`.**
The ban exists because the word pulled renders toward illustration. (a) Labels bypass `BANNED` (they're object
identity, not style). (b) Labels must pass the ban; author "red latex sphere on a string" instead. (c) Labels bypass
it but only inside their masked span, so the word can't reach the rest of the frame.
<details><summary>lean</summary>(c). That's the whole point of the mask: the illustration pull stays inside the balloon.</details>

**D4. Max labels per latent frame.**
More labels = more spans, more chance of leak and longer text. Options: 3, 6, unlimited.
<details><summary>lean</summary>6, by priority then area. Revisit after the checker shows where it breaks.</details>

**D5. Mask the clean store pass?**
Masked: identity gets baked into history, so later frames inherit it (could kill flips). Unmasked: the history stays
exactly as the model was trained to see it.
<details><summary>lean</summary>Ablate. My guess is masked helps flips at 832x480 and doesn't matter at 448x256 because the objects are under one token anyway.</details>

---

## 9. Read before building (answer these, then we start)

1. `kokopelli/wm/world_transfer.py:275-278`: what three kinds of keys does a target token attend to, and in what order?
   Where would column index `s_k` of a label land in `mx.concatenate(ks, axis=2)`?
2. `kokopelli/wm/world_transfer.py:317-328` (`patchify`): for an 832x480 frame, what are `h`, `w`, `hp`, `wp`, and
   which token index does pixel (x=400, y=200) end up in for latent frame 0?
3. `kokopelli/wm/controls/controls.py:144-167` (`Palette`): why would giving balloons a fixed seg colour not teach the
   stock model anything?
4. Prediction before milestone 3: out of 3 balloons in the regression clip at 832x480 with no labels, how many come out
   as balloons? With Tier A subjects? Write the numbers here before running.
