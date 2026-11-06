# Notes

## Variant A deviations / assumptions (`world_transfer_multi.py`)

- **Untrained combination.** Sim-Transfer was distilled on one control per clip. Weighted per-branch attention is borrowed
  from the base model's `multi_control_two_way_attention`; whether the causal 4-step student tolerates it can only be judged by eye.
- **Causal, not bidirectional.** Upstream lets ctrl_i attend to `[text | ctrl_i | noisy]`. Here a control pass is world_transfer's
  unchanged causal pass (text + its own history + itself, never R_f), so C_f^i K/V don't depend on the weights or other hints.
- **Branch i's context is `[text | C_0^i, R_0, ..., C_f^i | R_f]`.** Every branch shares one R stream: R_f's K/V are computed once
  through the weighted path and cached in every branch (same objects, no copies). Window/sink eviction is `world_transfer.History`'s,
  one History per branch (`MultiHistory`).
- **Mixing point.** `o = sum_i w_i * SDPA_i` in bf16, before `to_add_out`. Q/K/V, `o` and the MLP are shared, as upstream.
  Accumulation order follows control order (`o_1*w_1 + o_2*w_2 + ...`), like upstream's loop.
- **Weights.** Non-negative, positive finite sum, normalised to 1 (upstream `transfer.py:251-259`). A weight of 0 is allowed, but the
  branch is still computed (it costs time and contributes 0). Missing or extra hints are errors (upstream would assert on a length mismatch).
- **One control per hint type.** `controls` is `{hint: path}`, so two blur variants can't be mixed in one call.
- **Controls must have equal length** after `--frames` (error otherwise). fps is taken from the first control.
- **Seeding.** Same as world_transfer (`seed+f` initial noise, `seed + f*1000003 + (step+1)*9176` SDE noise), so N=1 at weight 1 is
  bit-identical to `world_transfer.run`. Checked on a tiny fake model (36 layers, hidden 64) in `tests/test_wm_multicontrol_a.py`,
  with and without window eviction. Two identical controls at .5/.5 also came out bit-identical to one there (0.5*o is exact in bf16).
- **No hooks needed in world_transfer.py.** The target forward duplicates `Generator.__call__`'s layer body (about 30 lines). If that
  file changes, the N=1 test fails. It reads helpers as `world_transfer.<name>` at call time, so tests can patch the IO.

### Memory / runtime estimate, 832x480, 17 frames (5 latents), N=3 (inferred, not measured)
- Gen half ~14 GB bf16 (as N=1). KV cache: one entry is 36 layers x K,V x 8 heads x 390 tokens x 128 x 2 B, about 57 MB. 5 latents x
  3 controls + 4 R entries = 19 entries, about 1.1 GB, plus text K/V (~530 tokens) of about 0.15 GB. Per-branch attention temporaries are under 0.3 GB.
- The N=1 runs measured here peaked at 13.8 GB (320x320x9) and 19.9 GB (640x640x121, mostly VAE). Expected peak for this run is ~15-18 GB,
  so **hold 20 GB** (world_transfer's default). Use 22 GB if the first run's `peak_gb` comes out above 18.
- Runtime: N=1 at ~400 tokens/latent measured ~9 s/latent (640x640). N=3 adds 2 control forwards and 2 extra attention sets per target
  pass, so roughly 1.7-2x: ~15 s/latent, about 1.5-2.5 min total with load and decode.

## Variant B: deviations from NVIDIA reference (`world_multicontrol_base.py`)

Reference = cosmos-framework `inference/transfer.py` (bidirectional chunk path, `build_transfer_batch`,
`build_control_cfg_postprocess`), `model/generator/mot/attention.py` `multi_control_two_way_attention`, `args.py`
`_TRANSFER_SAMPLE_DEFAULTS` / `_TRANSFER_DEFAULTS`. Confirmed from that code: text attends only to text (causal), so its K/V
are cached once per prompt; controls get no timestep embedding (only `mse_loss_indexes` tokens are stamped); N=1 is routed to
plain two-way attention; the no-control branch is the target alone with the positive prompt.

| # | Deviation | Why | Expected effect |
| - | --------- | --- | --------------- |
| 1 | MLX RNG, one `mx.random.normal` of the latent shape after `mx.random.seed(seed)`; reference uses a torch generator seeded `seed + chunk_id` | No torch on the Mac path | Same distribution, different sample |
| 2 | Controls resized with ffmpeg straight to the canvas (`bilinear`, `neighbor` for seg) from 8-bit mp4 (world_transfer.read_video). Reference default `transfer_resize_mode` is `center_crop` via torchvision, on a resolution/aspect bucket | Reuse; the bridge controls are 832x480 -> 448x256 (1% aspect change) | Sub-pixel differences; 448x256 is not a canvas I could confirm NVIDIA trains at |
| 3 | bf16 weights and activations, RoPE in fp32, sampler state fp32, weighted sum in bf16 (as upstream) | n/a | Kernel-level differences only |
| 4 | One window only (`--max-frames`, default 93, errors beyond it). No chunking in time, no conditional frames | Scope for the first runs | B1 is 17 frames, one window either way |
| 5 | Sampler: cosmos3_mlx `UniPCScheduler(use_karras_sigmas=False, flow_shift=10)`: sigmas `linspace(1, 1/1000, 51)[:-1]`, shifted `10s/(1+9s)`, first minus 1e-6, then 0. Upstream says "UniPC, shift 10" but its sampler code wasn't in the copies, so the exact grid (e.g. diffusers' flipped `1 - linspace(1, 1/1000)` variant) is unconfirmed. `--shift 0` gives cosmos3_mlx's default Karras schedule (sigma_min 0.147, max 200: the base model's T2V scheduler_config.json), which ignores shift | Match the transfer spec | Small schedule differences if the grids differ |
| 6 | Text CFG `uncond + g*(cond - uncond)` with no `normalize_cfg`, no guidance interval, no control-guidance interval (upstream defaults I couldn't see; the transfer spec sets none) | Spec | None if the defaults are off, as I believe |
| 7 | Negative prompt = `assets/negative_prompt.json` serialized with `json.dumps`, no metadata (recipe.md: "Matched serialized negative caption. No negative metadata" for the bidirectional model). Upstream's `negative_metadata_mode` default lives in a defaults file not in the copies | Recipe | If upstream does add inverse metadata, our negative differs by one sentence |
| 8 | Positive prompt: world_transfer.format_prompt (JSON fields `duration` = `int(frames/fps)` s, `fps`, `resolution`, `aspect_ratio`), then the Framework's default `emphasize_control_in_prompt` sentence naming the hints in `--control` order. At 17 frames / 30 fps the duration is "0s", which is what `int()` gives upstream too. `--no-emphasize` turns the sentence off (the Diffusers/TRT examples set it off) | Framework defaults | Matches the Framework if format_prompt is right for the base model; it was ported for Sim-Transfer from the shared `_get_prompt_sample_data` |
| 9 | Positions: text 0..L-1; vision time `L + 15000 + f*24/fps` (fps from the control, 30 here: stride 0.8), row, column; every control repeats the target's ids. cosmos3_mlx `_build_position_ids` and world_filter hardcode fps 24 (stride 1) | Upstream enables fps modulation | Correct per upstream; differs from world_filter |
| 10 | Attention: dense MLX SDPA per pass, ctrl_i's and the target's queries in one call (upstream: two calls, same KV), query-chunked (`--query-chunk`, blocks >= 32, short tails folded in). Chunked == unchunked bit for bit in tests | Memory | None |
| 11 | Only the target's velocity is computed at the output (`proj_out` on target rows). Upstream computes all rows and masks the controls' | Saves work | None |
| 12 | VAE decode via world_transfer.decode_chunked (one chunk at 5 latents); output clipped to [0, 1] and written with ffmpeg libx264 crf 14 at the control's fps | Reuse | None at this size |
| 13 | Text K/V from the understanding half run once per prompt, layer by layer; the 2846-token negative caption is never truncated (limit 4096) | 36 GB | None |
| 14 | Not checked against a CUDA run of the reference. Equivalences are tested only on tiny random tensors: N=1 attention == two-way attention (bit-exact), N=2 identical controls == N=1 (bit-exact in attention; within bf16 GEMM noise across the whole forward, because MLX picks matmul kernels by row count), zero-weight control leaves no trace | No CUDA box | Unknown residual risk |

**Finding about world_filter.py (not fixed there, owned elsewhere):** its `guided()` mixes `v_nc + control_guidance * (full - nc)`
and then applies text CFG, so the control increment ends up `guidance * control_guidance` = 4.5 x (full - nc) at 3 / 1.5.
Upstream first shrinks the control scale to `1 + (g_c - 1)/g`, so the final increment is `(g + g_c - 1)` = 3.5 x (full - nc).
world_filter therefore over-applies control guidance by 1.0 x (full - nc) at the default settings. It also uses the Karras
schedule (ignores shift 10), fps-24 positions regardless of the input's fps, and `_prepare_noise_latents(frames)` gives
`frames // 4` latents (4 for 17 frames, where the VAE makes 5).

### Variant B memory / runtime estimate, 448x256, 17 frames, N=2 (inferred, not measured)
- Tokens: 8 x 14 patches x 5 latents = 560 per item, 1680 for [blur | seg | target]; text 552, negative 2846.
- Memory: understanding half while caching text ~15 GB (released), generation half ~14 GB, activations and text K/V < 1 GB.
  Peak ~15-17 GB. Hold 20 GB.
- Compute: per step cond + uncond (1680 tokens each) + no-control (560) = ~3900 token-passes x ~14 GFLOP = ~55 TFLOP, about
  5-8 s at 7-10 TFLOPS; x50 = 4-7 min, plus ~2-3 min loading/encoding/decoding. About 10 min; `--max-hours 1` leaves room.
