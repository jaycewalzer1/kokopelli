# Brief: combined (multi-control) Cosmos transfer on the Mac, two variants, tested through the GPU queue

You are a separate Claude Code instance. The user asked for this work. Other sessions work in parallel: the Unreal
realism session (`city/realism/`) and the world-model session (`jaycewalzer-00`, which runs the city agent and plans
the bridge sim-to-real run). Read `CLAUDE.md` (the user is learning: explain why, ask before design decisions) and
`AGENTS.md` first.

## Goal
Let the bridge clip be rendered from several controls at once (blur + seg + depth + edge, weighted), instead of the
single control the current port allows, and compare against blur alone. Build **both** variants below, each by its
own subagent (they touch different files, so they can run in parallel), then queue a short test of each.

## What is already known (read `wm_multicontrol/RESEARCH.md`; upstream file copies in `wm_multicontrol/upstream/`)
- Current port: `world_transfer.py` runs `models/Cosmos3-Nano-Sim-Transfer` (causal, DMD-distilled, 4 steps, no CFG,
  exactly one control; `docs/SIM_TRANSFER_MLX.md`). Sim-Transfer is single-control by training.
- NVIDIA's multi-control: base `models/Cosmos3-Nano` (already on disk, ungated, OpenMDW-1.1). One scalar weight per
  control, normalised to sum 1; in every attention layer, one pass per control with K/V `[text | ctrl_i | noisy]`, and
  the target output is the weighted sum (`upstream/attention.py`, `upstream/transfer.py`). Reference spec: 50 steps,
  guidance 3, control_guidance 1.5.
- This Mac is an M4 Max with **36 GB**. Runtime numbers in RESEARCH.md are estimates, never measured here.

## Variant A: weighted controls on Sim-Transfer (untrained combination, cheap)
- New file `world_transfer_multi.py` that reuses `world_transfer.py` by import. **Do not edit `world_transfer.py`**
  (owned by the "Sim-Transfer on the Mac" session, see AGENTS.md); if a hook is unavoidable, propose it in
  `wm_multicontrol/HANDOFF.md` instead.
- One history stream per control, one attention pass per control, weighted sum, as in NVIDIA's base-model path.
- Hard check: with one control at weight 1, output must match `world_transfer.transfer_video` exactly (same seed).

## Variant B: base Cosmos3-Nano multi-control (NVIDIA's supported path, slow)
- New runner `world_multicontrol_base.py`, in the style of `world_filter.py` but not editing it. 50 steps, text CFG 3,
  control CFG 1.5, per-control weights. Needs query-chunked attention (or similar) to fit 36 GB.
- Check against NVIDIA's reference semantics in `upstream/`; note every deviation in `wm_multicontrol/NOTES.md`.

## Tests
- Unit tests under `tests/test_wm_multicontrol*.py` that run without the GPU (shapes, weight normalisation, the
  weight-1 equivalence on a tiny fake model if possible).
- Inputs: controls in `out/city_wm/bridge/controls/832x480/` (`blur.mp4`, `seg.mp4`, `depth.mp4`, `edge.mp4`), prompt
  from `city/wm/prompts/bridge.json` (variant "light" first: under 512 tokens). Same seed for every run.
- First runs are SHORT: 17 frames (1 + 4n) at 448x256 for B, 832x480 for A. Planned comparisons:
  A1 blur alone (baseline via world_transfer.py), A2 blur 0.5 + seg 0.5, A3 blur 0.4 + seg 0.3 + depth 0.3;
  B1 blur 0.5 + seg 0.5. Only scale up after the user has seen these.
- Queue every model run through the GPU queue (see AGENTS.md "Overnight coordination"):
  `python3 ops/gpu.py run --name wmmc_<x> --priority 25 --max-hours H --cwd ... --about "..." --output ... -- CMD`
  with `ram_share.py hold --name wmmc_<x> --gb N` inside it. Never run a model outside the queue. Outputs to
  `out/wm_multicontrol/<run>/` with a JSON sidecar (model, controls, weights, steps, seed, runtime, peak memory).
- Measure and record runtime and peak memory; they replace the estimates in RESEARCH.md.

## Rules
- Prefix everything you launch with `wmmc_`. Don't touch Unreal, ports 9001-9003, `mac_server/`, `city/realism/`.
- No downloads beyond small files, no system-wide installs, no git commits. Stop an approach after two failures and
  write down why.
- Add an entry to `AGENTS.md` for what you own (`wm_multicontrol/`, the two new runner files, their tests,
  `out/wm_multicontrol/`).
- When the runs are queued, and again when they finish, message the world-model session (`jaycewalzer-00`) with
  where the outputs are. Write a short `wm_multicontrol/REPORT.md` at the end.
