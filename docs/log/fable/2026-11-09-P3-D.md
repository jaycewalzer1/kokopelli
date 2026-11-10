# P3-D: mosaic and drift metric, automatic run check

Branch `fable/P3-D`, base `6479b67`. CPU only; no model loaded, no GPU job needed.

## What changed

- `core/video_check.py` (new). Per-frame `mosaic` and `drift` scores, `judge()` per window, `RunCheck` (push-by-push, 3 bad in a row = failed), `score_video`/`check_file` for finished files (ffmpeg in 16-frame batches, never a whole clip), CLI, and `calibrate`, which re-runs the labelled clips and writes `out/test_outputs/video_check/{clip}.svg` + `calibration.json`.
  - mosaic = sqrt(blob/25 × grid/0.08), bad above **1.0**. blob = mean |Laplacian| of the saturation map at 1/4 size (the measure in `out/world_stream/still_test.py`). grid = how unevenly the luma gradient spreads over the 16 column (and row) phases mod 16, the latent tile. Neither alone separates good from bad: paving repeats near 16 px, sunny gardens are colourful. The product does.
  - drift = correlation of painted luma with the **blur** control at 1/8 size (layout only), bad below **0.2**.
  - Window = 24 frames (one lunch push). A run fails after 3 bad windows in a row (≈ 4.5 s at 16 fps).
- `core/world_stream_multi.py`: `push()` hands each push's painted frames and blur control to a per-stream `RunCheck`, writes `<out_dir>/check.json` (all streams), and in `stop` mode raises `RuntimeError("video check failed for <stream>: …")` after 3 bad pushes in a row. **Outside the push loop** I also added a `check=None` argument and 3 lines in `__init__` (mode: `KOKO_VIDEO_CHECK` env, then the argument, then `off` for `fake=True`, else `stop`). P3-A owns the module top and argparse; this doesn't touch either, but merge carefully.
- `runtime/check_video.py`: delegates the picture check to `video_check.check_file` and reports `mosaic_max` and `mosaic_from_s` as **facts, not problems**. The runtime's mock world model paints a grid picture, which scores as mosaic by design. Making it a problem failed 2 existing tests in `runtime/tests/test_full_run_tools.py` (`mosaic 1.21 > 1.0`), and that file isn't mine.
- `tests/test_video_check.py` (new, 14 tests): synthetic clean and tiled frames, drift, the 3-in-a-row rule and its reset, lag alignment, short pushes skipped, check.json, and the hook through the fake worker (off by default, `stop` raises, `warn` only records).

## Labels (set by eye from contact sheets, before choosing thresholds)

- Iris film (`out/bodies/demo/runs/wm/film/iris.mp4`, 16 fps): good 0–46 s, bad 58–120 s (46–58 s is a visible transition, unlabelled).
- Mara film: good 9–50 s; bad 64–71 s and 98–108 s; 72–96 s is mixed and unlabelled.
- **Mara 0–8.5 s: the plan calls this good, and it looks clean, but it doesn't follow its control.** The painted film shows the courtyard while the blur control shows a wall close-up. At any lag up to 400 frames the best layout match is 0.35, against −0.75 at the same frame. I labelled it `drift`, and the check flags it as drift. Owner: confirm or overrule.
- a4: `a4_full_8bit`, `a4_full` and both panels of `a4_8bit_blind/side_by_side.mp4` (832 px crops), all good, scored against `out/city_wm/bridge/controls/832x480/blur.mp4`.
- wmstill_test outputs (`out/world_stream/still_test/`): the frames look fine until about 14 s. In the last second the sky smears and colours oversaturate; the picture doesn't tile. Labelled good 0–13 s, bad 14–15 s. The 8-bit clip, the bf16 clip and the sway clip all look alike until that last second.

## Acceptance

- **Classification at one threshold set (mosaic 1.0, drift 0.2, 3 windows in a row): 12 of 14 labelled segments correct. 2 missed, both the last second of still_8bit and still_bf16.** Their mosaic stays at about 0.6 (that breakage isn't tiling), and a 1 s stretch is shorter than the 3 pushes (4.5 s) a failure needs anyway. Drift can't be judged there because the clips have no control video (one frame was repeated). Drift against that source frame falls slowly from 0.735 to 0.617 for 8-bit and to 0.637 for bf16; sway stays at 0.76. That's a trend, but nowhere near 0.2. **Not met for the still-camera clips.**
- Ranges per 24-frame window (mosaic / drift):
  - iris good 0.48–1.00 / 0.47–0.81, one window over the line (39 s: 1.004, sky already blotchy on inspection); iris bad 1.24–1.75 / 0.45–0.68, 41 of 41 windows bad.
  - mara good 0.45–0.90 / 0.43–0.80, 0 of 27 bad; mara bad 1.01–1.15 and 1.08–1.53, all 10 windows bad; mara 0–8.5 s drift −0.74 to −0.11, 6 of 6 bad.
  - a4 (all 4) 0.39–0.47 / 0.63–0.75, 0 bad.
  - **The mosaic margin per window is thin (good max 1.004, bad min 1.01).** The 3-in-a-row rule is what makes the segments clean. Expect the odd single bad window on good video.
- Curves: `out/test_outputs/video_check/*.svg` (mosaic and drift panels per clip, threshold lines, labelled stretches shaded) and `calibration.json` (every window). Re-run with `python3 ops/memguard.py run --name vc --gb 4 -- .venv/bin/python -m core.video_check calibrate` (exit 1 while the still-clip misses stand).
- CPU time per 100 frames, every frame scored: 0.30–0.37 s at 448×256 and 1.30–1.34 s at 832×480 (target < 2 s). The hook scores every 2nd frame, so it costs about half that. Peak memory 0.6 GB for the whole calibration.
- Old metric on the same clips, for contrast: `runtime/drift.py` score, 0 = same, 1 = unrelated, against the blur control.
  - iris good 0.27–0.50 (median 0.36) vs iris bad 0.33–0.48 (median 0.39): no separation.
  - mara good 0.26–0.51 (median 0.32) vs bad 0.47–0.55: partial separation.
  - mara 0–8.5 s 0.86–0.93: it does see the off-control start.
  - a4 0.25–0.63.
  - Why it read 0.99 on garbage (`runtime/THIRTY_MIN.md`, commit `87d3526`): it compared against the mock sim's grid picture, which shares no layout with any painting, so it sat at its ceiling for good and broken frames alike. Its reference was wrong; and its histogram half can't see tiling at all. `runtime/check_video.py`'s old checks (scene cuts, black, frozen) don't look at the picture either.
- Edge-vs-edge drift (the plan's candidate) was measured and dropped. Canny on the painted frame against the edge control, with 5 px tolerance, scored F1 0.35–0.84 on good stretches and 0.74–0.81 on mosaic ones. Coarse gradient-vs-edge correlation was 0.24–0.61 aligned against −0.1–0.54 for a 30 s-shifted control. The edge control is full of sim-only texture (the paving grid) that a good painting leaves out. Blur-control layout scored 0.43–0.80 aligned against mostly ≤ 0.35 shifted (higher only when the camera stands still, when the shifted frame is the same view).
- Tests: `tests.test_video_check` 14 OK; with `runtime.tests.test_full_run_tools` 34 OK; `tests.test_city_lunch` passed in the same earlier run (49 run, the only 2 failures were the check_video ones fixed above).
- `make test-all` (one run, 350 s, peak 1.1 GB, exit 0): tests 564 OK (10 skipped, 2 expected failures); runtime 100 OK; simworld 197 OK; ops 26 OK; benchmarks 198 OK (1 skipped). Before (P2-D's run): tests 550 (10 skipped, 2 xfail), 100, 197, 26, 198 (1 skipped). +14 = the new `tests/test_video_check.py`; everything else is unchanged.
- ruff check clean on all four touched files.

## Owner decisions

1. **The hook is on by default in real runs, in `stop` mode.** On the demo run it would have stopped Mara's stream at push 3 (frame ~72) for drift, and later on mosaic. To run without it: `KOKO_VIDEO_CHECK=warn` (record only) or `off`.
2. Mara 0–8.5 s: is a painting that ignores its control (but looks fine) a failure? The check says yes.
3. The still-camera breakage (smeared sky, oversaturation) isn't caught. It needs its own measure, or a run longer than 15 s to see whether it grows.
4. `check_video`: mosaic is a fact, not a problem, because mock runs are grids. Make it a problem for real runs if wanted.
