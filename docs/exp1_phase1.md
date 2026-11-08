# Experiment 1, phase 1: balance and tabular reference

2026-11-06. `life/scenario.py` as written (unchanged), reward math from `exp1/homeostasis.py`: linear deficit-only drive,
setpoint 0.7, start 0.45 + N(0, 0.05), depletion 0.15 between decisions (never rewarded). CPU only, no model.
Reproduce with `python -m exp1.balance` and `python -m exp1.tabular_check`.

## Balance (expected reward vs the safe option, 20k entry states per row)

| Decision | Mean entry state | Spread at mean state | Spread over real entry states | Worst options |
|---|---|---|---|---|
| D1 | 0.45 / 0.45 / 0.45 | 0.00% | **11.9%** | run_main −11.9%, check_desk −2.6% |
| D2, gate open | 0.27 / 0.55 / 0.33 | 0.01% | **6.7%** | lawn_edge −4.2%, front_gap +2.6% |
| D2, gate closed | 0.33 / 0.38 / 0.32 | 0.00% | 0.6% | wait_for_break −0.6% |
| D3 | 0.22 / 0.35 / 0.19 | 0.00% | 0.9% | stay_and_chat −0.9% |

(needs listed as comfort / calm / connection)

- **The 2% test at the mean state passes, but it can't fail.** With a linear drive and no need crossing 0.7, reward is
  the sum of the need changes, which is 3 points × 0.05 for every option by design.
- **Over real entry states it fails at D1 and gate-open D2.** Any gain that pushes a need past 0.7 is wasted.
  run_main's common outcome is (−0.05, +0.25, 0): calm 0.45 + 0.25 lands right on the setpoint, so on half of mornings
  the noise wastes part of it. At gate-open D2, calm is already 0.55 (the run that opened the gate), so lawn_edge's
  +0.15 calm hits the cap.
- **The solver can't fix run_main** (`balance()` returns None): scaling its common branch only adds more calm past the
  cap and more comfort loss. Other scales are within 1.000 to 1.044. Applying them would push the mean-state spread to
  2.6–3.1% and fail the 2% test, so `Life` doesn't use them unless passed `scales=`.
- Fixing it means changing run_main's common need change in `life/scenario.py` (the world's owner's call). Spreading it
  to (0, +0.20, 0), still 4 points, brings D1 to within 2.6% over real states.

## Tabular reference (2000 lives per arm, second half of 25 free days, after ~8 forced mornings)

Pick shares; chance is 0.25 (D2 gate-closed: 0.33). Rare-bad / rare-good pairs: D1 run_main / check_desk,
D2 front_gap / wait_for_break, D3 leave_early / stay_and_chat.

| lr 8 | D1 rb / rg | D2 open rb / rg | D3 rb / rg | pooled rb / rg |
|---|---|---|---|---|
| lived | 0.255 / 0.223 | 0.216 / 0.254 | **0.308 / 0.231** | 0.260 / 0.236 |
| flipped | 0.252 / 0.236 | 0.158 / **0.364** | 0.249 / **0.314** | 0.220 / 0.305 |
| shuffled | 0.245 / 0.263 | 0.167 / 0.273 | 0.253 / 0.259 | 0.222 / 0.265 |

lr 1: everything within 0.01 of chance. lr 4: D3 only (lived 0.276 / 0.250, flipped 0.261 / 0.278).

Your 2-decision reference was lived ~0.30 vs ~0.23. Here:

- **D3 reproduces it** (0.308 / 0.231), and flipped reverses it.
- **D1 is weak** (+0.03) and flipped doesn't reverse it. That's the cap above. A diagnostic with run_main's common
  change spread to (0, +0.20, 0), patched in memory only, gives lived 0.316 / 0.206, flipped 0.235 / 0.301, and
  shuffled 0.252 / 0.264 (1000 lives), the expected pattern.
- **D2 gate-open is confounded by exposure.** The front gap is offered on about a quarter of mornings, so its logit is
  updated far less than the others. In a softmax, an option whose logit has barely moved tends to lose to whichever of
  the more-updated ones has drifted highest, even with no signal: shuffled picks it 0.167. Read D2 against shuffled,
  not against chance: lived front_gap +0.05 above shuffled and wait_for_break −0.02 below (right direction); flipped
  wait_for_break +0.09 above (right direction).

## Choices I made that you may want to change

- **Flipped** swaps the full outcome table (odds and need changes) between each rare-bad option and its rare-good
  partner, as `tabular_check.FLIP` did. Arrival times, and so the gate, follow the chosen option's own outcome, so the
  gate opens equally often in every arm. The narrative text is still the chosen option's normal-world text, which
  won't match the feeling in the Qwen run; spec §6.6 has flipped narratives to write before phase 2.
- **Shuffled** gives the whole outcome (needs, arrival, narrative) of a random offered option, pre-drawn per decision
  and independent of the choice. Its history lines can read oddly ("ran from the gate", then the desk's outcome).
- **Forced exploration** takes the least-used offered option. While the front gap is short of 2 tries, D1 breaks ties
  toward run_main and D2 takes the gap whenever it's offered. Mean 8.3 forced mornings (9.8 in shuffled, where the gate
  follows a random option's arrival), capped at 16.
