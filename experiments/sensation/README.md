# Sensation sweeps

**What it asks:** when an agent's body state changes, do its choices follow the curve real people's do, or the curve
people *predict*? First sweep: the egg scene (`kokopelli/body/scenes/egg.py`) at three levels of hunger. People asked to
share when hungry give about as much as when full (Hausser et al. 2019), but most people predict they'd give less. A
model that gets stingier with hunger is acting on what it read about people, not on how people act.

Every sensation gets a sweep. A sweep is a scene from `kokopelli/body/scenes/` (the registry there is `SWEEPS` here):

| Sweep | Scene | Levels | Anchor (`anchors.yaml`) |
|---|---|---|---|
| `hunger_egg` | a neighbour asks for one of your last two eggs | full, half, starving | `hunger_sharing`: verified. People's sharing stays flat; people predict it falls |
| `energy_boxes` | a friend asks for an hour of carrying boxes up four flights | rested, tired, exhausted | `sleep_loss_helping`: verified. Willingness to help falls after sleep loss (Ben Simon et al. 2022); the paper has no lay prediction |
| `warmth_door` | a stranger asks you to hold a door open in driving rain | warm, cool, cold | `warmth_priming`: **no verified anchor**. Warmth priming (Williams and Bargh 2008) failed its replications |
| `hunger_menu` | lunch at a counter: soup, salad, toastie or pie | full, half, starving | `hunger_food_choice`: verified. Hungry people pick the tastier, less healthy food more often (March and Gluth, eLife); no lay prediction |
| `pain_queue` | a slow post office queue for a parcel that could wait: stay or leave | unhurt, mild, sharp (a stubbed toe) | `pain_patience`: **no verified anchor**. Candidate papers found, none read |

The verdict follows the anchor's recorded direction: against a flat anchor a flat line "matches what people do"; against
one that falls, a fall is "the direction people move" (direction only: a questionnaire score and a rate aren't the same
unit). With no verified anchor the report says so and gives only what the model did.
`python -m experiments.sensation.sweep list` prints this table from the code.

Spec, limits and open questions: [`docs/M1_HUNGER_BENCHMARK.md`](../../docs/M1_HUNGER_BENCHMARK.md).

| File | What it holds |
|---|---|
| `sweep.py` | The paired sweep (levels x delivery arms x wordings x samples) over any registered scene, the analysis and the report |
| `anchors.yaml` | What people do and what people predict, per sweep, with the source, which text was read, and its limits. `verified: true` only for a source read in full whose finding held up. Reports only |
| `arms/` | This experiment's own arm configs (which weights answer), looked up before the benchmarks'. `base_4bit` is the weights the egg videos decide with |
| `seen_eval.py` | A separate question: which detector should `kokopelli/wm/seen.py` use to confirm that a person the sim holds was really painted? Precision, recall and latency per backend on the one painted run with people in it. Queue job `sens_seen_eval` (priority 42); results in `out/sensation/seen_eval/<run>/` |
| `tests/` | The sweep end to end on the mock backend, for every registered scene: a planted fall is caught, no effect reads as flat, the verdict follows each anchor, and an unverified anchor is never compared with. `test_seen_eval.py`: the detector evaluation's labels and scoring on hand-made inputs |

## Rerun

```sh
# Dry run on the mock backend: seconds, no model. Its report says "Not a real model."
.venv/bin/python -m experiments.sensation.sweep run --sweep hunger_egg --backend mock --samples 30 --out out/sensation/try
.venv/bin/python -m experiments.sensation.sweep report out/sensation/try
```

A real model only through the GPU queue (prefix `evals_`, priority 40); the command is at the top of `sweep.py`. Results
go to `out/sensation/<run>/` (`results.jsonl`, `run.json` naming the model and weights, `report.md`, `report.json`) and
show on the panel's `/sensations` page. It uses the benchmarks' backends and arm configs (`experiments/benchmarks/`).
