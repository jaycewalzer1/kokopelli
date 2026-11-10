# From a finished training run to the 30-minute loop and the benchmarks

`homeostatic.experiment` does the automatic part after each homeostatic run. To do it by hand, through the GPU queue, since it loads Qwen:

```sh
python -m experiments.homeostatic.export out/homeostatic/runs/homeostatic-0 --seed 0
```

It refuses a run that didn't beat both the untrained model and idling on validation lives, using only checks where at least 95% of replies were valid. Refusal writes nothing, so `handoff.json` always describes a run that earned it.

## What it writes

| Path | What it is | Who uses it |
|---|---|---|
| `<run>/fused/` | Full Qwen weights with the adapter merged in, about 18 GB | `--agent-weights` in `runtime.run` |
| `out/adapters/homeostatic/seed<N>/` | The adapter, its config and the states it trained on | A benchmark arm, and its leakage check |
| `out/homeostatic/handoff.json` | Which run, its validation score and adapter hash, plus the commands and arm settings below | Anyone picking this up |

`--agent-weights` takes a folder of full weights, not an adapter, because `MlxQwenAgent` points `llm_model.LLM_MODEL_WEIGHTS` at it. That's why fusing is needed.

## Into the agent loop

Run from a checkout that has `kokopelli/loop/`, through the queue, using the commands in `handoff.json`:

1. **`agent_loop.smoke`:** three ticks with mock sim and world model. Check the decisions in the run's `events.jsonl` before anything longer.
2. **`agent_loop.half_hour_this_mac`:** the 60 ticks on the mock sim. Cosmos makes this take days here, so it's only the fallback.
3. **The real half hour** uses `--backend real` on PACE, where SimWorld and a Cosmos server run. There the agent is a server (`--agent-url`) and `--agent-weights` is ignored, so serve `fused/` with vLLM instead. Nothing has been submitted; that's for the user.

`kokopelli.loop.run_mind` builds its own Qwen agent and has no weights option yet, so the feel-then-decide agent can't use a trained model until that's added.

`--low-memory` won't use these weights in 4 bits. It only sets a default, so these full-size weights win. A 4-bit version would need its own conversion.

## Into the benchmarks' before and after

`benchmark_arm` in `handoff.json` is the arm config for `base` to be compared with. These steps belong to the benchmarks owner or the user:

1. **Add the arm:** copy it to `experiments/benchmarks/configs/arms/homeostatic.yaml`.
2. **Add it to `PREREG.md` and lock it.** It's a draft, and only the user can approve it. `--real` refuses adapters until then, and `--exploratory` always refuses them.
3. **Use a backend that takes adapters.** `llm_model` refuses them, because `ask()` always loads the base. Either serve the adapter with `vllm` on a GPU node, or add a weights setting to `llm_model` so it can use `fused/` on this Mac.
4. **Train at least 3 seeds.** The pre-registration's rule needs 3.

## Known gaps

- **Reply format:** the adapter trains on replying with one action word to `experiments/homeostatic/world.py`'s prompt. The loop asks for a JSON decision with different actions (`kokopelli/mind/actions.py`). Training could damage that, which is what the smoke run is for. No adapter has been through it yet.
- **Transfer:** nothing shows that keeping four numbers in range changes how the model acts in the loop, where it never sees them. The loop has no such variables to reward, and `kokopelli/mind/` feelings are deliberately never a score. Training on the loop itself would need a decision on that, and the Perspectives notes' external judge.
- **The worktree's copy:** `.claude/worktrees/wm-agent-loop` holds a snapshot of `experiments/homeostatic/` and `kokopelli/life/` that can lag this checkout. The handoff only uses paths, so it doesn't depend on that copy.
- **Real weights:** fusing is tested on a tiny model, including that outputs match before and after. It hasn't yet run on real Qwen, because no run has passed the gate.
