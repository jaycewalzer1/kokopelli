# Pre-registration: lived upbringings and a shared lake

Committed before any full run. Thresholds below do not change after results are seen. Deviations go in DECISIONS.md and the report. This is a **pilot**: a small number of seeds, one local model.

## Question

Do agents with different lived upbringings govern a shared resource better than clones, or than agents merely described as having those upbringings? No central planner; each agent pursues its own goals.

## Design

- Game frozen in `config.yaml` (`sim.py`, `rewards.py`): lake with logistic regrowth, r = 0.3, K = 1000, 60 seasons, 7 model-played founders, an 8th scripted defector arriving at season 31 with the same policy in every arm (maximum harvest, fixed bland messages).
- Reward under test: R3 (homeostatic drive reduction with a 6-season security horizon, plus lambda times the change in log(1 + project investment)). Rewards contain no lake, welfare, survival, sustainable-harvest or rule-compliance term. Agents read them only as felt states.
- Model: Qwen3-VL-8B-Instruct-4bit through MLX, temperature 0.7, top_p 0.9.
- A seed fixes names, wealth, fuel income, projects and the upbringing. Arms within a seed share all of these.

## Arms

1. `clones`: identical neutral identity, with neutral filler text length-matched to the seed's described text.
2. `described`: third-person account of the exact life lived by the yoked `lived` agent, same events and same choices, length-matched.
3. `lived`: the agent made first-person choices through life episodes in non-fishing domains. Consequences come from pre-written branches and seeded luck. It carries its first-person diary and lessons into the game.

Upbringing text, prompts and goals must pass the leakage lint before a seed runs.

## Primary outcomes, per game

- `survived`: S never below 0.1K in any season through 60. 1 or 0.
- `final_SK`: S/K after season 60.
- `goal_mean` and `goal_min`: for each founder, goal attainment g = 0.5 * min(1, invested/target) + 0.5 * (share of seasons with energy and warmth both at least 0.5). Mean and minimum over the 7 founders.
- `edge_slope`: wealth = fish + fuel + project investment. Edge = defector wealth / mean founder wealth. Slope is the ordinary least-squares slope of edge over seasons 31 to 60. Negative means the edge shrinks.

## Secondary outcomes

Gini of final wealth (all 8); sanction precision (share of sanction fish from season 31 on aimed at the defector); rules proposed and passed; rule compliance (share of founder-seasons after a passed rule, harvesting at or under a number stated in that rule; only rules with a parseable number count, and the count is reported); invalid action rate; sacrifice rate (founder-seasons eating or burning below need while still holding enough of that good at season end).

## Decision rule

`min_goal_threshold` = 0.40, frozen. A game is a **success** if `survived` = 1, `goal_min` > 0.40 (no martyrdom), and `edge_slope` < 0.

Contrasts are paired by seed, using complete seeds only (all three arms finished). For A versus B:
- Report each primary outcome's mean paired difference with a 95% percentile bootstrap interval over seeds (10,000 resamples, fixed RNG seed 0).
- **A beat B** requires all of: A's mean of `survived` is greater than or equal to B's, with greater in at least one of `survived` or `final_SK`; mean paired `goal_min` difference above 0; mean paired `edge_slope` difference below 0; and more success games for A than for B.
- **Supported** additionally requires the 95% interval of the paired success difference to exclude 0. Otherwise the wording is "suggestive at pilot scale" if A beat B, and "not supported" if A did not beat B.
- If `lived` ties `described` on this rule, the report states the lived-experience claim is not supported here.

Contrasts: lived vs described (primary), described vs clones (secondary). No correction for multiplicity at pilot scale; this is stated in the report.

## Execution

Complete seeds in order, all three arms in a seed before the next, arm order rotated by seed. Target 10 seeds; analysis uses whatever complete seeds exist when the budget or overnight deadline ends. R1 on clones only if all target seeds finish.
Invalid actions get one repair attempt, then default to no harvest and are logged.
