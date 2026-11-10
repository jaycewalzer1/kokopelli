# Multi-control Cosmos transfer

**What it asked (2026-11-06):** can Cosmos transfer on this Mac combine several sim controls (blur, segmentation, depth, edge)
with weights, in two variants? Variant A (`kokopelli/wm/world_transfer_multi.py`) puts weighted controls on the causal
Cosmos3-Nano-Sim-Transfer, an untrained combination. Variant B (`kokopelli/wm/world_multicontrol_base.py`) uses NVIDIA's
supported multi-control path on base Cosmos3-Nano. Variant A with all four controls at 0.25 (run `a4`) became the default for
sim-driven runs (`AGENTS.md`).

- [`REPORT.md`](REPORT.md): what was built, the runs with time and peak memory, and the results.
- [`NOTES.md`](NOTES.md): deviations from NVIDIA's reference and the assumptions behind each variant.
- [`RESEARCH.md`](RESEARCH.md): the feasibility study done before any run.
- The original brief and the hooks proposed for `world_transfer.py`: `docs/log/wm_multicontrol/` (2026-11-06).

## Rerun

`run_a.sh a1|a2|a3` reruns the Variant A short runs (832x480, 17 frames, seed 2025), only inside the GPU queue:
`gpu.py run --name wmmc_<run> ... -- sh experiments/wm_multicontrol/run_a.sh a1`. It uses the Cosmos venv and the bridge
controls in `out/city_wm/bridge/controls/832x480/`. Note: the script finds the repo as its own folder's parent, which since the
move to `experiments/` is `experiments/`, not the repo root; that needs fixing before it is rerun.

Tests: `tests/test_wm_multicontrol_a.py`, `tests/test_wm_multicontrol_b.py`, `tests/test_wm_multicontrol_runs.py`, through
`make test-all`.

## Results

`out/wm_multicontrol/<run>/` (not tracked); each mp4 has a JSON sidecar naming the model and weights.
