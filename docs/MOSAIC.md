# Mosaic: stillness or elapsed time?

Result on 2026-11-10: **inconclusive at 150 frames.**

Three paints with Cosmos3-Nano-Sim-Transfer (8-bit), Variant A, four controls at 0.25, 832x480, 150 frames, same caption and seed (2025), scored per frame with `kokopelli/wm/video_check.py` (mosaic threshold 1.0, higher is worse):

| Set | Controls | Mosaic median | Mosaic max | Crossed 1.0 | Paint time |
|---|---|---|---|---|---|
| A `a4_full_8bit` | moving, 150 frames | 0.415 | 0.546 | no | earlier run |
| B `fable_still_B` | still from frame 0 | 0.392 | 0.759 | no | 819 s |
| C `fable_still_C` | moving 60, then still 90 | 0.397 | 0.496 | no | 782 s |

What this shows: stillness alone does not break the picture inside 150 frames. B's maximum is higher than A's and C's, but it stays under the threshold.
What it doesn't show: whether a still camera breaks later. Earlier still-camera failures appeared near frame 224, just past the 51-latent history window, and 150 frames is 38 latents. The next test is the same three sets at 300 frames, about an hour of GPU.

Curves and per-frame scores: `out/wm_multicontrol/fable_still_C/score/` (`stillness.json`, `.csv`, `.svg`). Rerun: `python3 kokopelli/ops/memguard.py run --name score --gb 2 -- .venv/bin/python tools/fable/stillness_score.py`.

## 300 frames, 2026-11-10 (partial: stopped when the owner took the GPU back)

Only the moving clip was painted. `fable_still_A300` (bridge controls forward then backward, 300 frames, same model and settings, 2,334 s):

| Frames | Mosaic median | Mosaic max |
|---|---|---|
| 0-150 | 0.417 | 0.536 |
| 150-204 | 0.433 | 0.533 |
| 204-260 | 0.417 | 0.503 |
| 260-300 | 0.405 | 0.504 |

It never comes near the 1.0 threshold, including past frame 204 where the 51-latent history window fills. So **elapsed time alone does not break a moving camera** on recorded controls. That removes one of the two explanations, but it does not prove stillness is the cause: the two still clips (`B300`, `C300`) were not painted. `B300` was stopped 29 minutes in and left no file.

To finish: `tools/fable/stillness300.sh run B300 C300` (about 40 minutes each, 24 GB), then score each with `kokopelli.wm.video_check.score_video`. Per-frame scores for A300: `out/wm_multicontrol/fable_still_A300/mosaic_per_frame.json`.
