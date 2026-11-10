# Running queue jobs on PACE

The GPU queue (`kokopelli/ops/gpu.py`) can run a job on PACE instead of this Mac. You choose per job, in the panel at `/queue` or with `--where pace`. The switch at the top of that page sets where new jobs go.

Nothing goes to PACE until the setup below is done. A job sent there before then fails with a clear message and never falls back to the Mac.

## What a job needs to run on PACE

The Mac runs Cosmos and Qwen with MLX, which only works on Apple chips. PACE has NVIDIA GPUs, so a job needs a second command that works there, given with `--pace-command`:

```
python3 kokopelli/ops/gpu.py run --name mind_x --priority 45 --cwd ~/Desktop/kokopelli \
  --pace-command "python -m kokopelli.loop.run_mind --agent qwen --ticks 90 --out out/mind/x" --pull out/mind/x \
  -- .venv/bin/python -m kokopelli.loop.run_mind --agent qwen --ticks 90 --out out/mind/x
```

A job with no `--pace-command` always stays on the Mac, and the panel greys out its PACE switch. No job in this repo has a CUDA version yet, so writing one, such as Qwen through `transformers`, is the next step before PACE does real work.

## What happens to a PACE job

1. Its `--cwd` folder is copied to `remote_root` with rsync. Environments, weights, outputs and `.git` are left out.
2. A Slurm batch script is submitted with `sbatch`. Its `#SBATCH` lines come from `pace.json`.
3. `sacct` is checked every `poll_seconds`, and the panel shows the state: pending, running, completed or failed.
4. Each `--pull` path is copied back into the same place here, and so is the Slurm log.
5. The ledger records it like a Mac job, with `where: pace`, the Slurm job id and an exit code. Slurm states map to the Mac's codes: TIMEOUT is 124, CANCELLED is 130 and OUT_OF_MEMORY is 137.

A PACE job doesn't take a turn on the Mac, so it never holds up the local line.

## Setup, once

1. **Pick a cluster.** Phoenix or ICE; the hostnames below are for Phoenix. Check whether your account is charged for GPU hours before running anything long, because spending is your call.
2. **Keep one SSH connection open.** PACE logs in with Duo, so the queue can't log in by itself. It reuses a connection you open. Add this to `~/.ssh/config`:
   ```
   Host pace
     HostName login-phoenix.pace.gatech.edu
     User YOUR_GT_USERNAME
     ControlMaster auto
     ControlPath ~/.ssh/cm-%r@%h:%p
     ControlPersist 12h
   ```
   Then run `ssh pace` once and approve Duo. For the next 12 hours, `ssh -O check pace` says the connection is up, and so does the panel.
3. **Build the environment on PACE.** Create a Python environment with CUDA builds of what the PACE commands need, in your scratch space, not home.
4. **Fill in the settings.** Copy `kokopelli/ops/cloud/pace.example.json` to `kokopelli/ops/cloud/pace.json` and replace every `CHANGE_ME`:
   - `remote_root`: where code is copied, such as `~/scratch/kokopelli`
   - `setup`: shell lines run before the command, such as `module load anaconda3` and activating your environment
   - `sbatch`: your account (`-A`), queue (`-q`) and GPU request (`--gres=gpu:1`), from the PACE docs for your cluster
   `pace.json` holds your account names, so keep it out of git.

## Checking it

- Panel: the dot next to the Mac/PACE switch turns green when PACE is set up and connected.
- Terminal: `python3 -c "from cloud.pace import connection_state; print(connection_state())"` from the repo root.
- Tests use a fake Slurm and never connect: `.venv/bin/python -m unittest tests.test_cloud_pace`.
