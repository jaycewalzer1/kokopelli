# kokopelli.agents: the city agents

Qwen agents living in the SimWorld city (`data/city/world.json`), either seeing the sim directly or seeing only what
Cosmos3-Nano-Sim-Transfer paints from it. Moved here from `city/agents/` in the reorganization.

| File | What it holds |
|---|---|
| `live.py` | One local Qwen in the city: it sees, decides, walks, talks and carries things |
| `live_wm.py`, `run_wm_life.sh` | The same life, but the agent sees only the world model's painting, never the sim. The script starts the packaged server on 9001 if nothing is listening, then `live_wm.py` |
| `lunch_wm.py`, `run_wm_lunch.sh` | Two people meet for lunch inside the world model, each with their own view |
| `lunch_parts.py`, `lunch_sim.py`, `lunch_text.py` | The lunch's pieces: bodies, minds and writers; the two-body sim; the personas and prompts |
| `lunch_fixes.py` | Behavior fixes for the lunch, each behind a switch that is off by default (measured in [`docs/log/fable/2026-11-10-P5.md`](../../docs/log/fable/2026-11-10-P5.md)) |
| `lunch_life.py` | A generated past for the two people through the life generator, behind `--life` |
| `bodies_client.py` | The SetBody/GetBody helper the live agent uses (moved from `tools/bodies/client.py`) |
| `navmap.py` | A walkable 2 m grid of the city and routes between named places |
| `npcs.json` | The scripted residents: where they stand or walk, and what they answer when spoken to |

## Running

Real runs use port 9001 (the packaged server, one client at a time) and load Qwen and Cosmos, so they go through the GPU queue
and take a memory claim: `kokopelli/agents/run_wm_lunch.sh --minutes 5`, queued as `AGENTS.md` describes
(`ram_share.py hold --name wmlunch_agents --gb 24`). Every sim-driven world-model run uses Variant A with all four controls
at 8-bit unless the owner says otherwise. `python -m kokopelli.agents.live --help` lists the options; outputs go to
`out/city_agents/` (shown on the panel's `/city-live` page).

Bodies come from `tools/bodies/` ([plan](../../tools/bodies/PLAN.md)). The lunch bench (toy world, no SimWorld or Cosmos) is `tools/fable/lunch_bench.py`. Tests: `tests/test_city_lunch.py`,
`tests/test_lunch_fixes.py`, `tests/test_golden_lunch.py`, `tests/test_city_bodies*.py`, through `make test-all`.
