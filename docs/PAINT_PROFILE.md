# Paint profile (P4-A)

Variant A (Cosmos3-Nano-Sim-Transfer, four controls at 0.25, gen weights 8-bit) on this M4 Max. Written 2026-11-10.

## Why two 150-frame paints took 935 s and 1,782 s

Source: `python3 scripts/fable/p4_paint_gap.py` (read-only; job metrics every ~15 s, paint window only, sidecar timings), plus `pmset -g log` and `pmset -g custom`.

| paint | frames | paint s | denoise s | decode s | encode s | watts mean | GPU busy | temp mean | temp max | s at ≥95 °C | swap start → max GB | other RAM GB | other queue jobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a4_full_8bit (2026-11-08 18:18) | 150 | **1781.6** | 1373.0 | 265.3 | 129.5 | **12.1** | 0.9 | 71.9 | 75.2 | 0 | 1.9 → 11.0 | 11.8 | none |
| demo_flyover3 (2026-11-09 12:34) | 149 | **934.9** | 683.7 | 178.4 | 56.4 | **32.7** | 0.9 | 80.6 | 90.8 | 0 | 4.0 → 13.6 | 13.1 | none |
| fable_still_B (2026-11-10) | 150 | 819.4 | 665.4 | 94.9 | 49.9 | 32.1 | 1.0 | 85.4 | 101.6 | 121 | 1.1 → 6.0 | 11.2 | none |
| fable_still_C (2026-11-10) | 150 | 781.6 | 631.4 | 89.9 | 51.7 | 33.1 | 1.0 | 85.3 | 89.3 | 0 | 3.9 → 4.9 | 8.8 | none |

**Cause: the slow paint ran on battery.** `pmset -g log` shows the Mac on battery from 17:59:47 (lid closed, then opened at 18:17:57) until 19:19:27, when it went back on AC at 10% charge. The paint ran 18:18:45 to 18:48:27, all of it on battery. This Mac's power settings are `powermode 2` (High Power) on AC and `powermode 0` (Automatic) on battery. On battery the GPU drew 12 W on average against 32-33 W in the three AC paints, with the GPU just as busy (0.9-1.0). Same work at a lower clock: every stage slowed by about the same factor (denoise 2.0×, encode 2.3×, decode 1.5-2.8×).

Ruled out:
- **Heat:** the slow paint was the coolest (72 °C mean, 75 °C max). The fast ones ran hotter (81-85 °C mean), and still_B spent 121 s at ≥ 95 °C and was still the second fastest.
- **Swap:** both the slow paint and the 935 s paint grew swap by about 9 GB, so swap doesn't separate them. still_C swapped least (4.9 GB max) and was fastest by 5%, so swap may cost a few percent, not 2×.
- **Other work:** no other queue job overlapped any of the four paints. Memory outside the job was similar (9-13 GB).

The 935 s paint has 149 frames and different controls (flyover, not bridge), so "near-identical" holds for model, size, precision and length only. The two still paints (same bridge controls as a4_full_8bit, on AC) confirm it: 782-819 s.

What to do: paint on AC. P4-E makes `gpu.py status` warn when the Mac is on battery or in Low Power Mode.

## The closed-loop step: what the recorded logs explain

Source: `out/bodies/demo/runs/wm/events.jsonl` (2026-11-08 two-agent run, on AC; 448x256, 8-bit, four controls at 0.25, 160 frames per push, 12 steps).

| per step (mean) | seconds |
|---|---|
| step total | 1,136.9 |
| sim (SimWorld, 10 s of walking) | 107.5 |
| two pushes (Mara, Iris), one after the other | 2 × 513.7 |
| Qwen decisions (19 logged, 9.6 s mean) | not separately visible; step total ≈ sim + pushes |

| per 160-frame push (mean of 24) | seconds |
|---|---|
| push total, as the agent saw it | 513.7 |
| painting: 40 latents × `s_per_latent` | 317.4 |
| controls from the sim frames (`controls_s`) | 12.9 |
| **not recorded** | **183.3** |

The brief's "about 475 s, while the per-latent figure explains about 310 s" is the same gap, from a different run. The 183 s is the worker's encode, decode, weight reload (`weight_loads` rises by one per step: the loop drops the weights while Qwen thinks) and the `.npy` handoff. The worker already returns `encode_s`, `paint_s` and `decode_s` for every push, but `city/agents/lunch_wm.py:126` logs only `latents`, `s_per_latent`, `peak_gb` and `weight_loads`, so the recorded logs can't split it further. The profile below does.
