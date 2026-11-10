# Homeostatic post-training

**What it asks:** can reinforcement learning post-train the LLM on a reward for keeping internal variables in a healthy range,
instead of for scoring higher, and does the trained adapter beat the untrained model and simple baselines on held-out lives?
It trains a LoRA adapter locally with the training loop from mlx-vlm's GRPO, using its own groups and loss.

## Rerun

```sh
make homeostatic-test    # the tests, on a tiny random model, in under a minute
make homeostatic         # the full comparison, in out/homeostatic/; SEEDS="0 1" runs more
make homeostatic-report  # rewrite report.md from whatever has finished
make panel               # then Homeostatic training in the sidebar, to watch a run
```

The full comparison loads Qwen, so it belongs in the GPU queue (queue priority 50, see `AGENTS.md`).

## Results

`out/homeostatic/` (not tracked): one folder per run, `report.md`, and `handoff.json` once a run passes the export gate. When
[`HANDOFF.md`](HANDOFF.md) was last updated, no run had passed it ("Real weights"). [`HANDOFF.md`](HANDOFF.md) also says how a run that passes goes on
to the agent loop and the benchmarks, and lists the known gaps.

The panel only reads what a run writes to `out/homeostatic/`, so it can be opened, closed or restarted during training. It follows whichever run is training until you pick one. It plots the validation score against the untrained model and the baselines, flags a run choosing the same action in every state, and lists the latest states: every action's score and which one the model chose.

| File | What it holds |
|---|---|
| `world.py` | The simulated life: variables, delayed effects, the drive and the reward |
| `grpo.py` | What replaces mlx-vlm's sampled groups and loss: every action scored by branching the simulator, and the first token trained toward those scores |
| `benchmark.py` | Scores any policy on the same lives, plus the non-model baselines and paired comparisons |
| `train.py`, `evaluate.py` | One training run; one policy on the held-out lives |
| `experiment.py`, `report.py` | Everything in order, resuming after a crash; `report.md` |
| `kokopelli/life/watch.py` | What the dev panel reads from a run's folder |
| `export.py`, [`HANDOFF.md`](HANDOFF.md) | Passes a run that beat the baselines on to the agent loop and benchmarks |

A map of this code, with line numbers as of 2026-11-06: [`docs/homeostatic_rl_map.md`](../../docs/homeostatic_rl_map.md).

## Method

The reward is `r = d(x_t) - d(x_t+1)` from Laurençon et al. 2021, where the drive `d` is the length of how far the variables sit outside their healthy ranges. The discount has to stay below 1: undiscounted, the rewards add up to `d(x_0) - d(x_T)`, so only the last turn would matter and leaving the range on purpose to come back would cost nothing.

Stock GRPO samples replies and normalizes their rewards. On Qwen that collapsed every time: the model settled on a habit, replies stopped disagreeing, and with no disagreement there was nothing left to learn from. So every action is scored from each state, and the first token of the reply is trained toward `softmax(score / temperature)`. This relies on being able to branch a simulator; a real life with an outside judge can't try every action from the same moment.

The simulator also picks the states and plays out the turns after each action, so an update needs no model replies and one forward pass per state. That's far more updates per hour, at a cost: the model is taught what the reward says about each state and never sees where its own choices lead, so this is closer to learning from a reward-derived teacher than to strict reinforcement learning. Validation still plays whole lives with the model's own choices.

The model sees its variables, their ranges and its last action, but not what actions do, and some effects land a turn late. Only the parsed action word reaches the world, so wording can't earn reward. The world and training settings are in `kokopelli/settings.py`.

The report compares each trained adapter on held-out lives with the untrained model, the same model told every effect in its prompt, and controls trained with the same code: `maximize` rewards more of everything, and `shuffled` gives each state's real scores to the wrong actions. It also has a split with healthy ranges never trained on.

The simulator stands in for the external LLM evaluator in the Perspectives notes. Its numbers can't be flattered, so this tests whether the training works without testing reward hacking against a judge.
