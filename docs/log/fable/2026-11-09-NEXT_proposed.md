## Read this first

*Proposed replacement for `out/ops/NEXT.md` (Fable P1-A, 2026-11-09). The old file was an interim note from about 03:55 on Nov 5; its run results are now history and live in `mind/MEASUREMENTS.md`, `runtime/THIRTY_MIN.md` and the ledger. This keeps only what still needs the owner.*

**Current work:** the Fable optimization pass (`docs/log/fable/2026-11-09-BRIEF.md`, `docs/log/fable/2026-11-09-PLAN.md`), on `integration/fable` and per-package branches. Per-package results: `docs/log/fable/`. Queue state: `python3 ops/gpu.py status`. Overnight results: `out/ops/MORNING.md`.

**Decisions only you can make** (carried over; check each is still open):
1. **Low Power Mode** was on (`powermode 1`) on Nov 5 and may slow every model job. Check `pmset -g`; to turn it off, `sudo pmset -a powermode 0`.
2. **How the agent's notes should work** (changes what the agent is): options in `runtime/THIRTY_MIN.md`.
3. **How to unstick the appraisal,** so feelings follow events: evidence in `mind/MEASUREMENTS.md`; other open questions in `mind/OPEN_DECISIONS.md`.
4. **`benchmarks/PREREG.md`** is a draft with no homeostatic arm; approving it and adding the arm are yours.
5. **PACE or cloud GPU launches:** nothing submitted, no money spent. Needs `cloud/pace.json` and SSH (`cloud/README.md`).
6. **Fable owner decisions:** the list at the end of `docs/log/fable/2026-11-09-PLAN.md`.

**Standing caveats:**
- Fake world-model runs and mock-frame runs are not quality results. Quality tests are closed-loop on real painted frames.
- Painted films have broken into a mosaic after about 52 s (`out/bodies/demo/README.md`); the cause is under study (Fable phase 3).
- Trained homeostatic adapters pass `homeostatic/export.py` only if they beat untrained Qwen and idling; none has (`homeostatic/HANDOFF.md`).
