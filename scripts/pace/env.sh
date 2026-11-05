#!/usr/bin/env bash
# Everything site-specific lives here. Fill in every CHANGE_ME before submitting a job.
# None of these values were checked against PACE: look them up in the PACE docs or `module avail`.
# You can also set any of them in your shell, which wins over this file.

# Modules to load, separated by spaces. A Python 3.10+ module, and Apptainer if you need it.
export WMLOOP_MODULES="${WMLOOP_MODULES:-CHANGE_ME_MODULES}"

# Holds the extracted Unreal package. Needs 50 GB or more (simworld README). Use scratch, not home.
export WMLOOP_SIMWORLD_DIR="${WMLOOP_SIMWORLD_DIR:-CHANGE_ME_PATH_TO_SIMWORLD_PACKAGE_DIR}"

# Client virtualenv, created by setup_client.sh.
export WMLOOP_VENV="${WMLOOP_VENV:-CHANGE_ME_PATH_TO_VENV}"

# Where reports and renders go.
export WMLOOP_OUT="${WMLOOP_OUT:-CHANGE_ME_PATH_TO_OUTPUT_DIR}"

# native: run SimWorld.sh directly. apptainer: run it in the image below.
# auto: try native, then apptainer if native dies at startup.
export WMLOOP_RUNTIME="${WMLOOP_RUNTIME:-auto}"

# Only needed for apptainer or auto. A .sif file or a docker:// URI with Vulkan and NVIDIA support.
# unrealcv/launcher.py:336 uses docker://zfw1226/unreal:latest, which has not been tried with this package.
export WMLOOP_APPTAINER_IMAGE="${WMLOOP_APPTAINER_IMAGE:-CHANGE_ME_APPTAINER_IMAGE}"

# Safe defaults, change if you want.
export WMLOOP_MAP="${WMLOOP_MAP:-/Game/Maps/demo_1}"           # base_environments.rst:12
export WMLOOP_GPU_INDEX="${WMLOOP_GPU_INDEX:-0}"               # -graphicsadapter index, launcher.py:189
export WMLOOP_READY_TIMEOUT_S="${WMLOOP_READY_TIMEOUT_S:-900}" # first shader compile can be slow
export WMLOOP_TICK_INTERVAL="${WMLOOP_TICK_INTERVAL:-0.1}"
export WMLOOP_RESOLUTION="${WMLOOP_RESOLUTION:-320x240}"

# Stops with a list of what is unfilled. Pass the names of the variables this script needs.
wmloop_require() {
    local missing=0 name
    for name in "$@"; do
        case "${!name:-}" in
            ""|CHANGE_ME*) echo "ERROR: $name is not set. Fill it in scripts/pace/env.sh." >&2; missing=1 ;;
        esac
    done
    [ "$missing" -eq 0 ] || exit 2
}

# Loads the modules, unless this is a dry run on a machine without them.
wmloop_load_modules() {
    if [ "${WMLOOP_DRY_RUN:-0}" = "1" ]; then
        echo "DRY RUN: would run: module load $WMLOOP_MODULES"
        return 0
    fi
    # shellcheck disable=SC2086  # the list is meant to split into separate module names
    module load $WMLOOP_MODULES
}
