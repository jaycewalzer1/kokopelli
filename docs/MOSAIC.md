# Mosaic: stillness or elapsed time?

Result on 2026-11-10: **inconclusive at 150 frames.**

Three paints with Cosmos3-Nano-Sim-Transfer (8-bit), Variant A, four controls at 0.25, 832x480, 150 frames, same caption and seed (2025), scored per frame with `core/video_check.py` (mosaic threshold 1.0, higher is worse):

| Set | Controls | Mosaic median | Mosaic max | Crossed 1.0 | Paint time |
|---|---|---|---|---|---|
| A `a4_full_8bit` | moving, 150 frames | 0.415 | 0.546 | no | earlier run |
| B `fable_still_B` | still from frame 0 | 0.392 | 0.759 | no | 819 s |
| C `fable_still_C` | moving 60, then still 90 | 0.397 | 0.496 | no | 782 s |

What this shows: stillness alone does not break the picture inside 150 frames. B's maximum is higher than A's and C's, but it stays under the threshold.
What it doesn't show: whether a still camera breaks later. Earlier still-camera failures appeared near frame 224, just past the 51-latent history window, and 150 frames is 38 latents. The next test is the same three sets at 300 frames, about an hour of GPU.

Curves and per-frame scores: `out/wm_multicontrol/fable_still_C/score/` (`stillness.json`, `.csv`, `.svg`). Rerun: `python3 ops/memguard.py run --name score --gb 2 -- .venv/bin/python scripts/fable/stillness_score.py`.
