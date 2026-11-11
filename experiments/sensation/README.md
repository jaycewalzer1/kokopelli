# Sensation sweeps

**What it asks:** when an agent's body state changes, do its choices follow the curve real people's do, or the curve
people *predict*? First sweep: the egg scene (`kokopelli/body/egg.py`) at three levels of hunger. People asked to share
when hungry give about as much as when full (Hausser et al. 2019), but most people predict they'd give less. A model
that gets stingier with hunger is acting on what it read about people, not on how people act.

Spec, limits and open questions: [`docs/M1_HUNGER_BENCHMARK.md`](../../docs/M1_HUNGER_BENCHMARK.md).

| File | What it holds |
|---|---|
| `sweep.py` | The paired sweep (levels x delivery arms x wordings x samples), the analysis and the report |
| `anchors.yaml` | What people do and what people predict, per sweep, with the source and its limits. Reports only |
| `arms/` | This experiment's own arm configs (which weights answer), looked up before the benchmarks'. `base_4bit` is the weights the egg videos decide with |
| `tests/` | The sweep end to end on the mock backend: a planted lay belief is caught, no effect reads as flat |

## Rerun

```sh
# Dry run on the mock backend: seconds, no model. Its report says "Not a real model."
.venv/bin/python -m experiments.sensation.sweep run --sweep hunger_egg --backend mock --samples 30 --out out/sensation/try
.venv/bin/python -m experiments.sensation.sweep report out/sensation/try
```

A real model only through the GPU queue (prefix `evals_`, priority 40); the command is at the top of `sweep.py`. Results
go to `out/sensation/<run>/` (`results.jsonl`, `run.json` naming the model and weights, `report.md`, `report.json`) and
show on the panel's `/sensations` page. It uses the benchmarks' backends and arm configs (`experiments/benchmarks/`).
