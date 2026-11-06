# Multi-control Cosmos transfer on this Mac: feasibility

Read-only study, 2026-11-06. No weights downloaded, no model run. Upstream = github.com/NVIDIA/cosmos-framework `main`
(fetched with `gh api`, copies in `scratchpad/up/`). Line numbers below are for those copies.

## Verdict

**Feasible without sign-ups, and the multi-control checkpoint is already on disk (`models/Cosmos3-Nano`).** But the cost is
large: NVIDIA's multi-control path is the bidirectional base model at **50 steps with text CFG 3 and control CFG 1.5**, against 4
steps with no CFG for Sim-Transfer. By my rough estimate (an inference, not measured) that is about 50-100x the compute of the
current single-control run: hours per 150-frame 832x480 clip instead of minutes. It also means a new MLX code path, because neither
`world_transfer.py` nor `world_filter.py` does weighted multi-control attention today.

**Important correction:** this Mac is an **M4 Max with 36 GB** (`sysctl hw.memsize` = 38654705664), not 128 GB. Memory figures
below assume 36 GB. `docs/SIM_TRANSFER_MLX.md` row 5 already says the full 16B model at bf16 (32 GB) does not fit in 36 GB.

## 1. Which checkpoints support multi-control (verified)

| Repo | Multi-control | On disk | Licence | Gated (HF API `gated`) |
|---|---|---|---|---|
| `nvidia/Cosmos3-Nano` (base, bidirectional) | **yes**, weighted (Cosmos Framework) or unweighted (vLLM-Omni, TRT-LLM, Diffusers) | local, 33 GB (transformer/ 28 GB) | OpenMDW-1.1 | `False` |
| `nvidia/Cosmos3-Super` (32B, multi-GPU) | yes | not local | OpenMDW-1.1 | `False` (but far too big for 36 GB) |
| `nvidia/Cosmos3-Nano-Sim-Transfer` (causal, 4-step DMD) | **no**, exactly one | local, 30 GB | OpenMDW-1.1 | `False` |
| `nvidia/Cosmos3-Nano-Transfer-Auto` (34.5 GB) | WSM + LiDAR driving controls only, multiview | not local | OpenMDW-1.1 | `False` (not relevant) |

Sources:
- Cookbook `.agents/skills/cookbooks/cosmos3/generator/transfer/README.md:17-22`: "Multi-control — two or more hints; Cosmos
  Framework also supports per-hint weights ... Per-hint weighting is supported only by Cosmos Framework; the serving backends accept
  multiple unweighted controls." `:54-55`: the same specs work for Nano and Super, chosen by `--checkpoint-path`; `:408`: "§19
  multi-control (Nano)".
- `specs/multi_control.json`: `num_steps 50`, `guidance 3.0`, `control_guidance 1.5`, `shift 10`, 720p, 93 frames @16 fps,
  `edge {weight 0.5}` + `blur {weight 0.5}`.
- HF API `https://huggingface.co/api/models/nvidia/<repo>` returns `gated: false` and `license_name: openmdw1.1-license` for all
  four. The cookbook notebook asks for an `HF_TOKEN` (README:126-129) but that is a convenience; an ungated repo downloads
  anonymously, and the base model is already local anyway. OpenMDW-1.1 (https://openmdw.ai/license/1-1/) is a permissive open licence.
- The non-distilled Sim-Transfer teachers (Stage 0 bidirectional, Stage 1 causal) are **not published**: an HF search of
  author `nvidia` for "Cosmos3" lists no such repo. The "Transfer teacher" in `city/wm/controls.py:265` therefore means the base
  `Cosmos3-Nano` transfer mode in practice. Sim-Transfer's own lineage is `..._from_stage2_iter2250@iter_1500`
  (`models/Cosmos3-Nano-Sim-Transfer/checkpoint.json`), Stage 0 starting "from compatible base regular weights"
  (`cosmos3-nano-sim-transfer/post-training/references/canonical-recipe.md:31`).

## 2. How multi-control works (verified from code)

- Batch layout `[text | ctrl_1 ... ctrl_N | target]`, every control a clean (no-timestep) vision item at the same temporal
  positions as the target (`inference/transfer.py:230-292`, `share_vision_temporal_positions`).
- Weights are **one scalar per control**, non-negative, normalised to sum 1 (`transfer.py:251-259`; `inference/args.py:323-331`
  `weight: float = 1.0`). **No spatiotemporal weight maps** in Cosmos3 (unlike Cosmos-Transfer 2.5, as far as I know; not checked).
- No separate control branches/ControlNets. It's done **inside every attention layer**: `model/generator/mot/attention.py:584-750`
  `multi_control_two_way_attention` runs N independent attention passes. In pass i, `ctrl_i` and the noisy target attend to
  KV = `[text | ctrl_i | noisy]`. Each control's output comes from its own pass, and the target's output is
  `w_1*out_1 + ... + w_N*out_N` (`attention.py:720-742`). With N=1 this is exactly the normal two-way attention. Routing is in
  `model/generator/mot/cosmos3_vfm_network.py:1816-1846, 1901-1949`.
- Control CFG (`transfer.py:376-479`): one extra forward with all controls dropped, mixed as `v_nc + g_c*(v_full - v_nc)`, folded
  under text CFG. So each step = conditional (all controls) + negative-prompt (all controls) + no-control target pass.
- Steps: 50 in NVIDIA's spec (the Transfer-Auto card measures with 35 + CFG = 70 NFEs). Sim-Transfer is 4 fixed SDE steps,
  guidance 1, with `control_guidance` forced to 1.0 (`transfer.py:510-511`).

### Runtime / memory estimate (inferred, not measured)

Grounding: the cosmos3-mlx runner README (`~/cosmos3/cosmos3-mlx/README.md:20-27`) reports Cosmos3-Nano T2V 832x480 x 16 frames in
~252 s on an M4 Max **128 GB**. That works out to roughly 9 TFLOPS effective, assuming 35 steps x 2 CFG passes. The only measured
Sim-Transfer run here is a 320x320, 9-frame smoke test (`out/sim_transfer/dev/smoke_320.mp4.json`: 18 s, 13.8 GB peak). It's
too small to scale from.

At 832x480 there are 390 tokens per latent, and 150 frames make 38 latents, so the target is ~14.8k tokens.
- Sim-Transfer, 1 control (current): ~6 gen-tower passes x 390 tokens per latent plus attention over <=40k cached keys. That's
  roughly 60 TFLOP per latent, **~4-6 min per clip**.
- Base, 1 control, 50 steps, CFG + control CFG: ~2.4 PFLOP per step, **~3-4 h**.
- Base, 4 controls in one 150-frame window: ~74k gen tokens, 4 attention passes over ~30k keys each. That's ~7 PFLOP per
  step, **~8-11 h at 50 steps** (~6-8 h at 35). Two controls (e.g. blur + seg) is about half that.
- Memory: gen tower ~14 GB bf16 (the port already keeps only the gen half, `SIM_TRANSFER_MLX.md` row 5), hidden states ~0.6 GB,
  MLP intermediates ~2-4 GB at 74k tokens. It fits in 36 GB **only if** the attention never materialises the 15k x 30k score
  matrix (that would be ~29 GB per layer). Plan on query-chunked SDPA. Chunking time as NVIDIA does (93-121-frame chunks) lowers the
  peak further.

## 3. Could the distilled Sim-Transfer take more than one control? (verified facts + inference)

Verified:
- It was trained on `[control, target]` pairs only. `transfer.py:500-504`: "requires exactly one control hint because the
  checkpoint was trained with [control, target]". `model-contract.md:14-24` is headed "One control and one target". The recipe
  (`canonical-recipe.md:49-50`) says "Each example contains one control video ... Select edge, blurred RGB, depth or segmentation
  with equal weights", so one hint per training clip and **no mixed hints in the history**.
- The control is injected in-context as clean latent tokens. Each latent C_f is cached per layer next to R_f
  (`world_transfer.py:289-311` `History`, C_0,R_0,C_1,R_1...).

Inferred:
- **Plain concatenation** of two control latents into the same KV at the same positions is out of distribution. The target would
  see two token sets with identical RoPE positions, which no training example had. Expect muddled structure.
- **NVIDIA's weighted-attention trick does carry over in principle.** Pass i would be `[text | history_i | C_i,f | R_f]`, and each pass
  on its own is in-distribution. The weighted sum of attention outputs is the same untrained composition the base model uses at
  inference, so it is no more out of distribution here than there. It is unsupported and untested for the causal student,
  which was distilled on single-control trajectories, so quality has to be judged by eye. Cost: about 1.5x the linear work
  (N control passes per latent instead of 1) and N times the attention for the 4 target steps, so roughly 2.5-3x the current
  run for N=4: **~12-15 min per clip**, still about 30x cheaper than the base model. The KV cache grows from 2 streams to N+1
  (~0.6 GB at window 51, so ~1.5 GB for N=4): no memory problem.
- **Switching control per chunk/latent** is mechanically trivial in the causal loop. The control is just the C_f tokens, so you
  can pick the hint per f. But the history would then hold mixed hint types, which training never had. Mild drift is possible. It
  is the cheapest "combination" (no extra compute).
- **Composite control image** (e.g. seg colours with edges drawn over, or blur with edge overlay): not documented by NVIDIA.
  It falls outside all four trained hint distributions (`model-contract.md:16-21` warns that even "an arbitrary Gaussian blur is a
  different input distribution"). Not recommended.
- Running the 4 single-control outputs and blending them in pixel space is a further fallback. It's cheap (4 x ~5 min), but
  the outputs won't agree on texture, so blending ghosts. Only useful for picking the best single control.

## 4. Porting effort (inferred)

Option A: weighted multi-control on Sim-Transfer, inside `world_transfer.py`. ~80-150 changed lines:
- `transfer_video` (`world_transfer.py:38-69`): accept N controls plus weights and pass `--hint/--control/--weight` lists.
- `run` (`:368-470`): encode N control videos. Positions are unchanged, since all controls share the target's positions.
- `History` (`:289-311`): one control stream per hint, plus the shared R stream, and a per-branch `view(i, for_target)`.
- `Generator.__call__` (`:252-287`): give the attention a list of per-branch contexts. Each control pass uses only its own
  context. For the target, run N SDPA calls (one per branch context plus its own K/V), weighted-sum the outputs, and only then
  apply `o`/MLP. QKV projections and the MLP stay shared, which is the point.
- The step loop calls the N control passes per latent, then the 4 target steps and the clean-R_f cache pass, both through the
  weighted-attention path. Only R_f's attention output depends on the branch; its own K/V at layer 0 do not. At deeper layers
  they do, through the weighted hidden state, but that is still one R stream. So the cache holds a single R stream plus N
  control streams.
- Tests: N=1 with w=1 must reproduce the current output bit for bit.

Option B: NVIDIA-supported weighted multi-control on base `Cosmos3-Nano`. ~250-400 lines, a new runner in the style of
`world_filter.py` (which already does base-model single-control transfer, CFG 3 / control CFG 1.5, UniPC, chunking):
- Replace the cosmos3_mlx fused attention with the per-control pass split above. Either reuse `world_transfer.py`'s
  explicit `Generator`, or patch cosmos3_mlx's attention.
- Add a text-K/V cache for both the positive and negative prompts, the no-control branch, chunk conditioning, and query-chunked SDPA to stay inside 36 GB.
- Check parity against upstream on a tiny case. That needs a CUDA box, or trust the N=1 identity.

## What I'd suggest testing first (inference)

The planned blur control (stronger than medium) is the main structure driver, with seg as backup. Option A with 2 controls
(blur 0.7 + seg 0.3) is the cheapest real experiment: ~2x the current runtime, and no new checkpoint. Run base-model
multi-control only if Option A's output is visibly broken, since each clip costs hours.
