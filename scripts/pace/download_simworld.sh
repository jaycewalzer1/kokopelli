#!/usr/bin/env bash
# Download the SimWorld Linux package. Prints the size first, and only downloads with --yes.
#
#   scripts/pace/download_simworld.sh           # size and free disk, nothing downloaded
#   scripts/pace/download_simworld.sh --yes     # download and unzip into WMLOOP_SIMWORLD_DIR
#
# Run this on a data-transfer or login node, whichever PACE recommends for large downloads.
# Never run on the Mac: the package only runs on Linux or Windows with a dedicated GPU.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pace/env.sh
source "$HERE/env.sh"
wmloop_require WMLOOP_SIMWORLD_DIR

# simworld/README.md:263 links the /blob/ page. /resolve/ is the same path as a direct file.
# installation.rst:63 gives an older path, Base/Linux.zip. Use it if this one has gone.
URL="${WMLOOP_SIMWORLD_URL:-https://huggingface.co/datasets/SimWorld-AI/SimWorld/resolve/main/Base20260201/Linux.zip}"
ZIP="$WMLOOP_SIMWORLD_DIR/Linux.zip"

mkdir -p "$WMLOOP_SIMWORLD_DIR"
echo "URL: $URL"

# -I asks for headers only, and -L follows the redirect to the file host. The last length wins.
BYTES="$(curl -sIL "$URL" | tr -d '\r' | awk 'tolower($1)=="content-length:" {n=$2} END {print n}')"
if [ -n "$BYTES" ] && [ "$BYTES" -gt 0 ] 2>/dev/null; then
    echo "Package size: $BYTES bytes ($((BYTES / 1024 / 1024 / 1024)) GiB)"
else
    echo "WARNING: the server did not report a size. Check the URL in a browser before downloading."
fi
echo "Free space at $WMLOOP_SIMWORLD_DIR:"
df -h "$WMLOOP_SIMWORLD_DIR"

if [ "${1:-}" != "--yes" ]; then
    echo "Nothing downloaded. Re-run with --yes when the size and free space look right."
    echo "The zip and the extracted package both have to fit at once."
    exit 0
fi

# -C - resumes a partial download, so re-running after a dropped connection is safe.
curl -L -C - --fail --retry 5 -o "$ZIP" "$URL"
sha256sum "$ZIP" | tee "$ZIP.sha256"
unzip -q -o "$ZIP" -d "$WMLOOP_SIMWORLD_DIR"

SCRIPT="$(find "$WMLOOP_SIMWORLD_DIR" -maxdepth 4 -name SimWorld.sh -print -quit)"
if [ -z "$SCRIPT" ]; then
    echo "ERROR: no SimWorld.sh found after unzipping. Look inside $WMLOOP_SIMWORLD_DIR." >&2
    exit 1
fi
chmod +x "$SCRIPT"
echo "Ready: $SCRIPT"
echo "You can delete $ZIP once a job has passed."
