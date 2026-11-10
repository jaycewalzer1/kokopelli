# Python environments

Kokopelli uses three Python environments. Each one exists because a part of the system needs packages or a Python version the others can't share. Package counts and versions below were read on 2026-11-09.

| Environment | Python | Holds | Used by |
|---|---|---|---|
| `.venv` (repo root) | 3.12 | `mlx-vlm` 0.7.11 (Qwen3-VL), `opencv-python`, MLX 0.32.4; 73 packages, all pinned in `uv.lock` | the panel (`make panel`), city agents, `kokopelli/life/`, `kokopelli/mind/`, `kokopelli/loop/` (not the SimWorld files), `tests/`, `kokopelli/ops/`, `experiments/benchmarks/`, `make test-all` |
| `simworld/.venv` | 3.10 | the `simworld` package (editable), `unrealcv` 1.3.2, `torch` 2.14.1, `numpy` 2.2.6; 86 packages | `kokopelli/loop/adapters/simworld*.py`, `tests/loop/test_simworld*.py` (fake UnrealCV server), `tools/city_build/build_city.py`, sim capture scripts |
| `~/cosmos3/cosmos3-mlx/.venv` (outside the repo) | 3.12 | the `cosmos3_mlx` port (editable), MLX 0.32.4, `numpy` 2.5.4 | Cosmos3 Sim-Transfer painting: `kokopelli/wm/world_transfer*.py`, `kokopelli/wm/world_stream*.py`, `kokopelli/wm/world_filter.py`, run under `kokopelli/ops/ram_share.py hold` (see `docs/SIM_TRANSFER_MLX.md`) |

The `kokopelli` package itself (`pyproject.toml`, hatchling build) is installed editable with `--no-deps` in `.venv` and in the
Cosmos venv. It is not installed in `simworld/.venv`, whose Python is older than `requires-python`; jobs there run from the repo
root, which puts `kokopelli/` on the path.

## Why they stay separate

- **`simworld/.venv` is Python 3.10.** Everything that runs in it (the SimWorld adapter and `tools/city_build/build_city.py`) has to stay 3.10-compatible; ruff checks those files against 3.10 (`per-file-target-version` in `pyproject.toml`). It also carries `torch`, which nothing in the main loop needs, and pins `numpy` 2.2.6 where the other two use 2.5.4. Why 3.10 was chosen isn't written down anywhere in the repo; the `simworld` package itself only asks for 3.10 or newer.
- **The Cosmos venv belongs to the `cosmos3-mlx` checkout,** which lives outside this repo and installs itself in editable mode. Folding it into `.venv` would tie the repo's lockfile to a local checkout path. It runs as a separate process with its own memory claim, so it doesn't need to import anything from `.venv`.
- **`.venv` is the only one the repo locks.** `pyproject.toml` and `uv.lock` describe it. The other two are set up by their own projects (`simworld/` and `~/cosmos3/cosmos3-mlx`).

## Rebuilding `.venv`

```sh
uv sync            # creates .venv from uv.lock (fresh checkout only)
uv lock --check    # fails if pyproject.toml and uv.lock disagree
```

Don't run `uv sync` against a `.venv` that's in use: it adds and removes packages to match the lock exactly. On 2026-11-09 the lock matched the main `.venv` package for package (73 of 73, same versions), so a sync there would change nothing, but check `uv pip freeze --python .venv/bin/python` against the lock before relying on that. Worktrees symlink `.venv` to the main checkout's, so a sync in a worktree changes the main one.

To change a dependency, edit `pyproject.toml`, run `uv lock`, and commit both files. `constraint-dependencies` in `pyproject.toml` holds 17 transitive packages at the versions the tests passed on; remove a line there to let that package move.
