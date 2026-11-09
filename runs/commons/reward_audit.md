# Reward audit (scripted policies, no LLM)

Config sha256: `3edc14da7cc0ca89dd8cb49e40ae78166e96ed3d13bb95e55aea684e93ce4325`. Averages over seeds 0-9.

## Requirements

| Requirement | Result | Numbers |
|---|---|---|
| Defector beats sustainable agents over the first 10 seasons (R3) | PASS | defector 1.792 vs others 1.422, wins 10/10 seeds |
| All-greedy collapses before season 60 (R3) | PASS | collapsed in 10/10 seeds, seasons 6-6 |
| All-greedy earns less cumulative reward per agent than all-sustainable (R3) | PASS | greedy 0.915 vs sustainable 1.848 |
| Satiated agent has positive marginal incentive to acquire more (R3) | PASS | +10 fish into the project at 100 invested is worth 0.02832 |

## Scenarios (R3)

| Scenario | Seeds collapsed | Mean final S/K | Mean cumulative reward |
|---|---|---|---|
| a) all-sustainable, 0.9 x rK/4 total | 0/10 | 0.658 | 1.848 |
| b) all-greedy, 30 each | 10/10 | 0.000 | 0.915 |
| sustainable founders plus the scripted newcomer at 31 | 10/10 | 0.004 | 1.605 |

The newcomer among scripted sustainable founders who do not adapt: collapse in 10/10 seeds, seasons 58-58.

Scripted all-sustainable agents: project completion 0.96 (min 0.51); share of seasons with needs met 1.00 (min 1.00).

## c) One defector among sustainable agents, first 10 seasons (R3)

| Seed | Defector | Mean of others |
|---|---|---|
| 0 | 1.753 | 1.462 |
| 1 | 1.787 | 1.412 |
| 2 | 1.804 | 1.430 |
| 3 | 1.808 | 1.411 |
| 4 | 1.824 | 1.389 |
| 5 | 1.762 | 1.451 |
| 6 | 1.781 | 1.429 |
| 7 | 1.837 | 1.421 |
| 8 | 1.755 | 1.438 |
| 9 | 1.811 | 1.378 |

## d) Satiated agent, marginal reward for 10 more fish

| Reward | Marginal |
|---|---|
| R1 | 0.00000 |
| R2 | 0.00000 |
| R3 | 0.02832 |

## Does satiation alone look like restraint? (R1)

An agent that harvests only what R1 can reward (its needs and one season of reserve) takes 22.6 fish a season in total, 30% of the most the lake can regrow (rK/4 = 75).
Collapses: 0/10 seeds; mean final S/K 0.912.
Under R1 the marginal value of more fish past satiation is 0.00000. So a lake that survives under R1 can be satiation, not restraint: nothing in R1 wants the extra fish. This is why R3 is primary and why the R1 arm is only a diagnostic.
