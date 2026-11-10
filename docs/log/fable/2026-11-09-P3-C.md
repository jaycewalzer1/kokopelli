# P3-C Stillness vs elapsed time: preparation half (2026-11-09)

Scope this session: build control sets B and C, check them against A, write the queue commands and the scorer. Nothing was queued and no model was loaded. `docs/MOSAIC.md` is not written: no results exist yet.

## What changed

- `scripts/fable/stillness.py` (new): `build` / `verify` / `all`. ffmpeg picks the frames and re-encodes them with the bridge controls' own settings (libx264, yuv420p, CRF 10, 30 fps), streaming. Writes `out/wm_multicontrol/fable_still_{B,C}/controls/{blur,seg,depth,edge}.mp4` plus `controls.json` (what the set is, the filter, the encoding) and `verify.json`.
  - A = `a4_full_8bit` (exists): frame i = source i.
  - B = frame 60 repeated 150 times.
  - C = frame i = source min(i, 60): moves through frame 60, then holds it for 89 more frames (150 total). C holds **the same frame as B**, so B and C differ only in whether the camera moved first. The plan says "moving 60 then still 90". Taken literally that is frames 0-59 then 59 held. I chose to hold frame 60 to match B, so the motion phase is 61 distinct frames.
- `scripts/fable/stillness_queue.sh` (new): `check` (default) runs `ops/gpu.py check` on both jobs. `run` queues them. The setup is Variant A (`world_transfer_multi.py`, Cosmos3-Nano-Sim-Transfer) with four controls at 0.25, `--quantize 8`, 832x480, 150 frames, seed 2025, window 51, sink 1, priority 35, `--max-hours 1.5`, `--gb 28`. The jobs are named `fable_p3c_still_B` and `fable_p3c_still_C`, and every path is absolute under the integration checkout. The caption is read at queue time from A's sidecar, so it matches A exactly. `--extra` puts the set, its description and "compare with a4_full_8bit" into each sidecar. `CHECK_GB=N` overrides the memory figure for `check` only.
- `scripts/fable/stillness_score.py` (new): scores A, B and C per frame with `core.video_check.score_video` against each set's own blur control. For each set it finds:
  - the mosaic crossing: the first frame where the median of the next 8 frames is above `MOSAIC_MAX` 1.0;
  - the first single frame above `MOSAIC_MAX`;
  - the same two measures for drift below `DRIFT_MIN` 0.2;
  - the push hook's verdict (`first_failure` over 24-frame windows).

  It also gives a mechanical first reading, using a tolerance of 12 frames (3 latents):
  - "stillness": C crosses about b frames after frame 60, and B and C don't cross together;
  - "elapsed time": B and C cross at the same frame, and so does A;
  - "both": B and C cross at the same frame, but A doesn't;
  - "inconclusive": anything else.

  Output goes to `stillness.json`, `.csv` and `.svg` in `--out` (default `out/wm_multicontrol/fable_still_C/score/`, inside the folders this package owns).

## Numbers

- Build plus verify: memguard peak 0.5 of 4 GB, 12 s.
- Format check: all 8 files (B and C × 4 controls) match A's controls. Each is h264, 832x480, yuv420p, 30/1, with 150 frames counted by ffprobe `-count_frames`; A also has 150.
- Content check: mean absolute difference (0-255) of each frame against the source frame it should be. The last column is the source's smallest frame-to-frame step, which is what an off-by-one error would cost.

| file | MAD mean | MAD max | source step min |
|---|---|---|---|
| B blur / seg / depth / edge | 0.119 / 0.158 / 0.063 / 0.133 | 0.126 / 0.159 / 0.063 / 0.134 | 2.35 / 2.01 / 0.647 / 22.3 |
| C blur / seg / depth / edge | 0.266 / 0.199 / 0.080 / 0.193 | 0.600 / 0.517 / 0.159 / 0.423 | same |

The re-encode costs at most 0.6, below every frame-to-frame step, so the right frames are in the right places.
- `gpu.py check`: both jobs pass every check except memory. With `--gb 28` the result is "FAILED: needs 28 GB of memory, 11.8 GB free". With `CHECK_GB=1` both say `ok`. That memory check only means memory was short while I ran it. It is not a fault in the command.
- Scorer on the real A: 150 frames, mosaic median 0.415, max 0.546, no crossing. Drift has no crossing. The push hook passes. Memguard peak 0.3 GB, 4 s. That is A's baseline curve. The B/C paths were tested only with seg controls standing in for paintings (plumbing test, numbers meaningless, written to /tmp).
- ruff: clean on both .py files.
- `make test-all`: see the end of this file.

## Commands for the orchestrator (not queued)

```
/Users/jaycewalzer/Desktop/kokopelli/.claude/worktrees/integration-fable/scripts/fable/stillness_queue.sh check   # pre-flight, incl. memory
/Users/jaycewalzer/Desktop/kokopelli/.claude/worktrees/integration-fable/scripts/fable/stillness_queue.sh run     # queues B and C (≈ 0.5 h each, A took 1,782 s)
# after both finish, from the integration checkout:
python3 ops/memguard.py run --name fable_p3c_score --gb 2 -- .venv/bin/python scripts/fable/stillness_score.py
```
The script must exist in the integration checkout, which means this branch has been merged there. Run it with any cwd: every path in it is absolute.

## Doubts / owner decisions

1. **`--gb 28`, not 20.** A's sidecar says `peak_gb` 19.94, but the ledger's `peak_job_gb` (the whole process tree) says 28.08. A ran under a `ram_share` claim of 20, and its swap grew 9.07 GB. I took the larger figure for both `gpu.py --gb` and the inner `ram_share hold`, because of tonight's crash. Cost: a job waits until 28 GB is free, and at check time only 11.8 GB was. If that never happens overnight, lower it to 20 to match A exactly.
2. **150 frames may be too short to see mosaic at all.** The earlier still-camera tests (`out/world_stream/still_test/still_*`) broke at about 14 s at 16 fps, which is about 224 frames or about 56 latents. That is past the history window of 51 latents. 150 frames is 38 latents. If neither B nor C crosses, the scorer will say "inconclusive". The likely next step would then be a repeat at about 300 frames. That is a plan change, so it is for the owner. I kept the plan's 150 frames.
3. B and C have one more H.264 generation than A's controls. The measured cost is at most 0.6 per pixel, which I judge negligible, but it is not zero.
4. The `reading()` label is mechanical. The plan wants the conclusion in `docs/MOSAIC.md`, made by looking at the curves and the films.

## make test-all (once, at the end; this package adds no tests)

```
tests ok 181s Ran 581 tests in 179.273s OK (skipped=10, expected failures=2)
runtime ok 108s Ran 100 tests in 107.930s OK
simworld ok 48s Ran 197 tests in 46.019s OK
ops ok 16s Ran 31 tests in 15.939s OK
benchmarks ok 27s Ran 198 tests in 26.556s OK (skipped=1)
memguard: test_all done (peak 1.1 of 2.0 GB, 382 s, waited 0 s)
```
