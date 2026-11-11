# Object labels on the seg control

**What it asks (2026-11-10):** when a SimWorld actor carries a text label, does Cosmos3-Nano-Sim-Transfer paint that
region as that thing and keep it that thing, and what does the rest of the frame pay? Tier A puts the label in the
caption. Tier B also lets only the label's own picture tokens read its words (an attention mask). Plan, decisions and
build status: [`docs/LABELS_PLAN.md`](../../docs/LABELS_PLAN.md). Code: `kokopelli/wm/labels.py`,
`kokopelli/wm/label_check.py`, the `--labels` flags of `kokopelli/wm/world_transfer.py`.

**State:** nothing has been run. No regression clip, no checker calibration, no paint. The table below is empty on purpose.

These paints use **seg alone** (`world_transfer.py`), not the four-control default: the plan keeps multi-control out of
the first experiments. Say so in every `--about` and sidecar. They keep the default's 8-bit weights.

## Run it

1. **Clip.** Capture the regression shot with the labeled actors in frame (needs the packaged server on 9001; the
   balloon and ball stand-ins still have to be spawned). A capture script that passes `SimWorldConfig(label_actors=...)`
   and calls `labels.build_pass`, as `experiments/filter_test/scripts/capture.py --labels labels.json` does, leaves
   `labels/NNNN.png` and `labels_meta.json` in the clip. For a clip that already has `mask_colors` in its `capture.json`:
   `.venv/bin/python -m kokopelli.wm.labels build --clip CLIP --labels labels.json`. Then build the controls
   (`kokopelli/wm/controls/controls.py --clip CLIP --out CLIP/controls`).
2. **Calibrate the checker** on about 50 crops sorted by hand into `out/labels/calibration/<class>/`, through the queue:
   `.venv/bin/python -m kokopelli.wm.label_check calibrate out/labels/calibration`. Above 10% error, fix the checker first.
3. **Write your prediction** (plan, section 9, question 4) before the first paint.
4. **Paint**, one queued job per run, from the repo root (`P` is the caption, as in the `paint-clip` skill):

   ```
   K=/Users/jaycewalzer/Desktop/kokopelli; CLIP=$K/out/labels/regression/clip; NAME=labels_<run>
   python3 kokopelli/ops/gpu.py run --name $NAME --priority 25 --max-hours 1 --cwd $K \
     --about "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, 8-bit), seg control only (not the 4-control default: label experiment), 832x480, 149 frames of the label regression clip: <run>" \
     --output out/labels/regression/$NAME -- \
     python3 kokopelli/ops/ram_share.py hold --name $NAME --gb 20 -- env PYTHONPATH=$K:$HOME/cosmos3/cosmos3-mlx $HOME/cosmos3/cosmos3-mlx/.venv/bin/python \
     -m kokopelli.wm.world_transfer "$P" --hint seg --control $CLIP/controls/832x480/seg.mp4 \
     --output out/labels/regression/$NAME/$NAME.mp4 --size 832x480 --frames 149 --seed 2025 --quantize 8 \
     --extra '{"controls_note": "seg only, label experiment"}' \
     <label flags>
   ```

   | Run | Label flags |
   |---|---|
   | `none` (no labels) | none |
   | `tier_a` (caption only) | `--labels labels.json --label-frames $CLIP/labels --label-steps 0` |
   | `b_s1_hard`, `b_s2_hard` | `... --label-steps 1` or `2` |
   | `b_s1_soft5`, `b_s2_soft5` | `... --label-steps 1` or `2 --label-mode soft --label-beta 5` |
   | the store-pass half of the slice | the same four plus `--label-store` |

   That is the plan's first slice at tau 0.25. The paint's sidecar has a `labels` block: what the caption named, each
   label's token span and tokens per latent frame, and seconds per latent.
5. **Check** each paint, after it, through the queue (Qwen, about 18 GB):
   `.venv/bin/python -m kokopelli.wm.label_check out/labels/regression/$NAME/$NAME.mp4 --labels labels.json --clip $CLIP --baseline out/labels/regression/labels_none/labels_none.mp4`
   writes `<video>.labels.json`. Mosaic and drift: `python -m kokopelli.wm.video_check <video> --control $CLIP/controls/832x480/blur.mp4`.

Tests: `tests/wm/test_labels.py`, `tests/wm/test_label_paint.py`, `tests/wm/test_label_check.py`, and the mask-colour
test in `tests/loop/test_simworld_adapter.py`, through `make test-all`.

## Results

| Run | Hero accuracy | Labeled accuracy | Flips | Neighbor leak | Change outside | Mosaic | s / latent |
|---|---|---|---|---|---|---|---|
| (none yet) | | | | | | | |
