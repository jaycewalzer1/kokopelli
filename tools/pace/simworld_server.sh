#!/usr/bin/env bash
# Functions to start and stop one headless SimWorld server. Meant to be sourced by the job script.
#
# Flags and where they come from:
#   -RenderOffScreen, -graphicsadapter=N  unrealcv/launcher.py:189,193, real rendering with no display
#   --cvport N                            simworld minimal_example.rst:10, UnrealCV's port
#   -nosound, -unattended                 standard Unreal flags, not from SimWorld. No dialogs or audio device.
# Do not use -nullrhi: it turns off rendering, so there would be no images (launcher.py:191).

WMLOOP_UE_PID=""

# A free port from the kernel. Another job can take it before UE binds it, which the
# retry loop in wmloop_start_server handles. Binding port 0 means no two jobs pick by formula.
wmloop_pick_port() {
    python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

wmloop_find_launcher() {
    find "$WMLOOP_SIMWORLD_DIR" -maxdepth 4 -name SimWorld.sh -print -quit
}

# Fills WMLOOP_UE_ARGS for this port.
wmloop_build_args() {
    WMLOOP_UE_ARGS=("$WMLOOP_MAP" -RenderOffScreen "-graphicsadapter=$WMLOOP_GPU_INDEX" -nosound -unattended "--cvport" "$1")
}

# Starts UE in its own process group, so we can stop it and its children without touching
# anything else on the node. Usage: wmloop_launch native|apptainer PORT LOGFILE
wmloop_launch() {
    local kind="$1" port="$2" log="$3" launcher
    launcher="$(wmloop_find_launcher)"
    wmloop_build_args "$port"
    if [ "${WMLOOP_PORT_VIA_INI:-0}" = "1" ]; then
        # The fallback if --cvport is ignored. Edits the shared package, so only one job at a time.
        local ini
        ini="$(find "$WMLOOP_SIMWORLD_DIR" -name unrealcv.ini -print -quit)"
        if [ -n "$ini" ]; then
            sed -i.wmloop_bak "s/^Port=.*/Port=$port/" "$ini"
            echo "Set Port=$port in $ini"
        else
            echo "WARNING: WMLOOP_PORT_VIA_INI is set, but there is no unrealcv.ini under $WMLOOP_SIMWORLD_DIR" >&2
        fi
    fi
    local command=("$launcher" "${WMLOOP_UE_ARGS[@]}")
    if [ "$kind" = "apptainer" ]; then
        # --nv exposes the NVIDIA driver inside the container. The package dir is bound at the
        # same path, so the launcher path stays valid.
        command=(apptainer exec --nv --bind "$WMLOOP_SIMWORLD_DIR" "$WMLOOP_APPTAINER_IMAGE" "${command[@]}")
    fi
    echo "Launching ($kind): ${command[*]}"
    if [ "${WMLOOP_DRY_RUN:-0}" = "1" ]; then
        WMLOOP_UE_PID=""
        return 0
    fi
    setsid "${command[@]}" >"$log" 2>&1 &
    WMLOOP_UE_PID=$!
}

wmloop_server_alive() {
    [ -n "$WMLOOP_UE_PID" ] && kill -0 "$WMLOOP_UE_PID" 2>/dev/null
}

# Waits for the UnrealCV hello in short slices, so we notice at once if UE has died.
# Returns 0 ready, 1 process died, 2 timed out.
wmloop_wait_ready() {
    local port="$1" deadline=$((SECONDS + WMLOOP_READY_TIMEOUT_S))
    while [ "$SECONDS" -lt "$deadline" ]; do
        wmloop_server_alive || return 1
        if PYTHONPATH="$WMLOOP_REPO${PYTHONPATH:+:$PYTHONPATH}" "$WMLOOP_VENV/bin/python" "$WMLOOP_REPO/tools/pace/wmloop_wait_server.py" \
                --port "$port" --timeout 20 --quiet; then
            return 0
        fi
    done
    return 2
}

# Tries runtimes and fresh ports until one answers. Sets WMLOOP_PORT, or returns non-zero.
wmloop_start_server() {
    local kinds=("$WMLOOP_RUNTIME") attempt kind status log
    [ "$WMLOOP_RUNTIME" = "auto" ] && kinds=(native apptainer)
    [ "$WMLOOP_RUNTIME" = "auto" ] && [[ "$WMLOOP_APPTAINER_IMAGE" == CHANGE_ME* ]] && kinds=(native)

    for kind in "${kinds[@]}"; do
        for attempt in 1 2 3; do
            WMLOOP_PORT="$(wmloop_pick_port)"
            log="$WMLOOP_OUT/ue_${kind}_attempt${attempt}.log"
            wmloop_launch "$kind" "$WMLOOP_PORT" "$log"
            if [ "${WMLOOP_DRY_RUN:-0}" = "1" ]; then
                return 0
            fi
            wmloop_wait_ready "$WMLOOP_PORT"
            status=$?
            if [ "$status" -eq 0 ]; then
                echo "Server ready on port $WMLOOP_PORT after ${SECONDS}s of job time ($kind)."
                return 0
            fi
            if [ "$status" -eq 2 ]; then
                echo "Server still not ready after ${WMLOOP_READY_TIMEOUT_S}s. Last log lines:" >&2
                tail -n 30 "$log" >&2
                # UnrealCV may have ignored --cvport and stayed on 9000. Worth saying plainly.
                if PYTHONPATH="$WMLOOP_REPO${PYTHONPATH:+:$PYTHONPATH}" "$WMLOOP_VENV/bin/python" "$WMLOOP_REPO/tools/pace/wmloop_wait_server.py" --port 9000 --timeout 5 --quiet; then
                    echo "It IS answering on 9000, so --cvport was ignored. See 'Port' in kokopelli/loop/SIMWORLD.md." >&2
                fi
                wmloop_stop_server
                return 1
            fi
            echo "$kind server died during startup (attempt $attempt). Last log lines:" >&2
            tail -n 30 "$log" >&2
            wmloop_stop_server
        done
    done
    return 1
}

# Stops only the process group we started.
wmloop_stop_server() {
    [ -n "$WMLOOP_UE_PID" ] || return 0
    kill -TERM -- "-$WMLOOP_UE_PID" 2>/dev/null || true
    local waited=0
    while wmloop_server_alive && [ "$waited" -lt 20 ]; do
        sleep 1
        waited=$((waited + 1))
    done
    kill -KILL -- "-$WMLOOP_UE_PID" 2>/dev/null || true
    WMLOOP_UE_PID=""
}
