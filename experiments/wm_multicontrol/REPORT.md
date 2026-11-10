# Multi-control Cosmos transfer: report (2026-11-06)

## What was built
- **Variant A, `world_transfer_multi.py`**: weighted multi-control on the causal 4-step Sim-Transfer. It imports
  `world_transfer.py` and doesn't edit it. There is one history per control and one shared history for the painted
  frames. In each layer the painted frame attends once per control, and the outputs are mixed by weight before the
  output projection, as NVIDIA's base model does. Tests: `tests/test_wm_multicontrol_a.py` (10, unittest).
- **Variant B, `world_multicontrol_base.py`**: NVIDIA's supported path on base Cosmos3-Nano: 50 UniPC steps (shift 10),
  text CFG 3, control CFG 1.5 with upstream's rescale, per-control weights, and query-chunked attention. Only the
  ~14 GB generation half stays in memory. Tests: `tests/test_wm_multicontrol_b.py` (19).
- Deviations from NVIDIA's reference: `NOTES.md`. Optional hooks for `world_transfer.py`: `HANDOFF.md`, none needed.
  Run script for A: `run_a.sh`.

## Results (`out/wm_multicontrol/`, each mp4 has a JSON sidecar)
| Run | Controls | Size | Time | Peak |
|---|---|---|---|---|
| a1/blur_world_transfer.mp4 | blur (baseline) | 832x480 | 72 s | 13.9 GB |
| a1/blur_multi_w1.mp4 | blur, weight 1, new code | 832x480 | 104 s* | 13.9 GB |
| a2/a2.mp4 | blur .5 + seg .5 | 832x480 | 100 s* | 14.2 GB |
| a3/a3.mp4 | blur .4 + seg .3 + depth .3 | 832x480 | 97 s | 14.4 GB |
| a4/a4.mp4 | blur/seg/depth/edge .25 each | 832x480 | 111 s | 14.7 GB |
| a4_full/a4_full.mp4 | blur/seg/depth/edge .25 each, **150 frames** | 832x480 | 3518 s† | 24.2 GB |
| b1/b1.mp4 | blur .5 + seg .5, base model | 448x256 | 609 s | 14.8 GB |
| b4/b4.mp4 | blur/seg/depth/edge .25 each, base model | 448x256 | 1005 s | 14.8 GB |
| b4_832/b4_832.mp4 | same, base model, fair size | 832x480 | 4180 s (~80 s/step) | 15.0 GB |

\* An Unreal window was open during part of these runs.
† Latents 0-32 took 10-58 s each (the history grows); from latent 33 (~22.8 GB) each took ~360 s because the Mac
swapped (6.4 GB in swap afterwards). Without swapping it would have been ~25 min. The full clip holds its look from
frame 0 to 149. Capping the history (NVIDIA's long-clip setting, window 30 / sink 3) would cap memory and time per latent.

- **Hard check passed:** with one control at weight 1, the new code's latents are bit-identical to `world_transfer.py`'s
  (`a1/equivalence.json`, max diff 0.0).
- **First look** (`compare_f12.png`, frame 12; top row A1, A2, A3; bottom row A4, B1, B4). Blur alone
  copies the blur: the A1 frame itself looks soft. Adding seg (A2) or seg + depth (A3) gives sharp rails, planks and
  skyline with the same layout, so the untrained mix doesn't look broken in this frame. B1 and B4 are sharp too, at a quarter
  of the pixels. A4 and B4 (all four controls) were queued by the realism session at the user's request. This is one frame of a 17-frame clip, judged by eye; check motion and flicker in the videos.

- **Fair comparison** (`a4_vs_b4_832.mp4`, `a4_vs_b4_832_edges_f12.png` = frame 12 with the sim's edge map overlaid).
  At equal size B costs ~38x A (4180 s vs 111 s). B looks more photographic (softer light, natural colour, finer
  texture); A is more saturated. Both put the rails, deck, arch and dome on the sim's edges. A also follows the sky
  edges (clouds where the sim has them); B mostly ignores them and adds small things the sim doesn't have (a blue cloth
  on the right rail). By eye only; a depth/seg agreement score per run would settle which is more faithful.

## Findings outside this work
- `world_filter.py` `guided()` applies control CFG without upstream's `1 + (g_c - 1)/g` rescale (4.5x instead of 3.5x
  on the control increment at g=3, g_c=1.5). It also ignores the flow shift, assumes 24 fps positions, and builds 4 latents
  from 17 frames where the VAE makes 5. Details are in `NOTES.md`; it was not changed (another session owns it).

## Open
- Nothing is compared against a CUDA run; B's exact UniPC sigma grid and two guidance defaults are unconfirmed upstream.
- **Decision (2026-11-07): the user chose Variant A** ("A looks substantially better - that is what we will use").
  `wmmc_b4_full` (base model, 4 controls, 832x480, 93 frames, queued by the realism session) was stopped at the user's
  request at step 39 of 50, after 8.6 h (~13 min/step at 20.5 GB peak). No video; the log is
  `out/ops/job_logs/20261107-015353-wmmc_b4_full.log`.
- Next: make full-length A runs fit in memory (cap the history window, free memory, or 8-bit weights; the user's
  choice), and a depth/seg agreement score per run before using A's clips as training data.
