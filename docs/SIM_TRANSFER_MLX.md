# Cosmos3-Nano-Sim-Transfer on the Mac (MLX)

`world_transfer.py` runs `models/Cosmos3-Nano-Sim-Transfer` (checkpoint
`causal_8b_sf_dmd_transfer_480p_direct_resize_caption_mix_from_stage2_iter2250@iter_000001500`) on Apple silicon with MLX.
It's a port of NVIDIA's own causal transfer inference, not of the base-model control hack in `world_filter.py`.

## What the reference does

Sources read: cosmos-framework `main` (`model/generator/omni_mot_causal_model.py` `iter_samples_from_batch_autoregressive`,
`_seed_frame_into_kv_cache` and `_run_distilled_ar_sampler`; `data/generator/sequence_packing/{autoregressive,packers,mrope}.py`;
`utils/kv_cache.py` `ARMemoryState.read_for_layer`; `inference/transfer.py`; `inference/inference.py` prompt formatting; and the
`cosmos3-nano-sim-transfer` skill docs). Also SGLang `multimodal_gen/.../cosmos_dreams.py` for the text limit, and diffusers 0.42's
distilled blocks for the SDE step.

- **Architecture:** the same weights as Cosmos3-Nano: a Qwen3-VL-8B "understanding" half for text and a "generation" half for
  vision latents (`*_moe_gen`, `add_*_proj`), with three-way attention. The keys match the base checkpoint one for one, except
  that the audio and action heads are removed. The VAE (Wan2.2, 16x spatial, 4x temporal, 48 channels) is byte-identical to the base model's.
- **Causal loop, one latent frame f at a time** (the first latent is 1 video frame, each later one is 4):
  1. The clean control latent C_f (no timestep embedding) goes through the generation pathway. Its queries see the text, the
     cached history and itself, and its per-layer K/V are cached. At f = 0 this pass also carries the text, whose K/V are cached once.
  2. The target R_f starts from noise and takes the 4 fixed steps `t = [1, 15/16, 5/6, 5/8]` and then 0. Each step uses the SDE
     update `x0 = x - t·v`, then `x = (1 - t_next)·x0 + t_next·ε`, with fresh noise every step and `x = x0` on the last one. Its queries see
     the text, the history, C_f and itself.
  3. The clean R_f goes through again to cache its K/V; the last frame is skipped.
- **Positions:** text uses 0..L-1 on all three mRoPE axes. Vision uses time `L + 15000 + f·(24 / fps)` and height/width
  0..hp-1 and 0..wp-1. Control and target share the same positions.
- **History window:** `kv_cache_inference_size = W` latents with `attention_sink_size = S`. The pass for C_f sees the first 2S entries
  plus the last 2(W-S-1). The pass for R_f sees one more, C_f. The config defaults are W = 51 and S = 1; NVIDIA's 600-frame quick
  start uses 30/3.
- **Prompt:** a system prompt (`_SYSTEM_PROMPT_TRANSFER`), then a Qwen chat template, then `<|im_end|>` and `<|vision_start|>`.
  For a JSON caption, the reference overwrites `duration` (`int(frames/fps)` + "s"), `fps`, `resolution {H, W}` and `aspect_ratio`.
  A plain caption gets "The video is X seconds long and is of N FPS. This video is of HxW resolution." appended.
  Guidance is 1 and there's no negative branch.
- **Text length:** training cut the chat ids at 4096 tokens. The config's `text_cache_max_len = 512` is the size of the
  paged/static-compile engine's fixed text buffer, not a training limit. The framework only checks it in its
  static-compile mode, where it raises an error rather than truncating, and SGLang just logs a warning. So prompts up to 4096 tokens are fine.
- **Frames:** the control is padded to 1 + 4n frames by time reflection (`pad_temporal_frames`), and the output keeps the
  requested count. The vLLM and SGLang servers instead trim to whole chunks, so 150 frames would become 149.

## Deviations in the MLX port

| # | Deviation | Why | Expected effect |
| - | --------- | --- | --------------- |
| 1 | Random numbers come from MLX's RNG. The seeding formula is the same (`seed + f` for the initial noise, `seed + f·1000003 + (step+1)·9176` for the SDE noise), but the streams differ from torch's | There's no torch on the Mac path | Same distribution, different sample. A given seed won't reproduce NVIDIA's video pixel for pixel |
| 2 | The control is resized with ffmpeg (`bilinear`, or `neighbor` for seg) from the 8-bit mp4. The reference uses torchvision bilinear with antialiasing and keeps depth as float32 until encoding | Simpler input path | Sub-pixel resampling differences, and depth is quantized to 8 bits before the VAE. Small |
| 3 | The VAE decode runs in chunks of 6 latents, with 3 earlier latents as causal warm-up whose frames are dropped. The reference decodes causally with a full feature cache | The port's decoder decodes a whole clip at once, which doesn't fit at 480p × 150 frames | Measured below. Near-identical |
| 4 | bf16 everywhere. RoPE is applied in fp32 and cast back. The sampler state is fp32, as in the reference | n/a | Matches the reference's BF16 runtime within normal kernel differences |
| 5 | Text K/V come from the understanding half, run once one layer at a time; then only the generation half (~14 GB) stays in memory | 16B parameters at bf16 (32 GB) don't fit in 36 GB | None: the text half is never used again after frame 0 |
| 6 | Attention is dense MLX SDPA over [text, selected history, current]. The reference uses varlen/flex kernels and a ring buffer | Kernels | Numerically equivalent attention pattern |
| 7 | Only one control per call | Same as the reference ("Causal transfer AR inference requires exactly one control hint") | None |

## Using it

```python
from world_transfer import transfer_video
transfer_video(prompt, {"depth": "out/city_wm/bridge/controls/832x480/depth_inverse.mp4"},
               "out/sim_transfer/bridge_depth_832x480.mp4", size="832x480", frames=150, seed=2025)
```

It runs in `~/cosmos3/cosmos3-mlx/.venv` under `ram_share.py hold --name sim_transfer --gb 20` and writes `<output>.json`
with the model name, prompt, the prompt as formatted, controls, size, frames, fps, seed, steps, seconds and peak GB.
`raw_prompt=True` skips the metadata injection described above.
