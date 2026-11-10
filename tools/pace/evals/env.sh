#!/usr/bin/env bash
# Everything site-specific for benchmark jobs on PACE. Fill in every CHANGE_ME before submitting.
# None of these values were checked against PACE: look them up in the PACE docs or with `module avail`.
# You can also set any of them in your shell, which wins over this file.

export EVALS_MODULES="${EVALS_MODULES:-CHANGE_ME_MODULES}"             # Modules to load, space separated
export EVALS_VENV="${EVALS_VENV:-CHANGE_ME_PATH_TO_VENV}"              # Python venv with vllm and benchmarks' needs
export EVALS_LM_EVAL="${EVALS_LM_EVAL:-CHANGE_ME_PATH_TO_LM_EVAL}"     # lm-eval command, from a venv with lm-eval[api,ifeval]
export EVALS_MODEL="${EVALS_MODEL:-Qwen/Qwen3-VL-8B-Instruct}"         # Hugging Face id, or a local path on scratch
export EVALS_ADAPTERS="${EVALS_ADAPTERS:-CHANGE_ME_PATH_TO_ADAPTERS}"  # Holds <arm>/seed<N>/ in PEFT format
export EVALS_OUT="${EVALS_OUT:-CHANGE_ME_PATH_TO_RESULTS}"             # Use scratch, not home
export EVALS_PORT="${EVALS_PORT:-18000}"                               # The vLLM server port for guardrails, on the job's node
