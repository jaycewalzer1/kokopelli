#!/usr/bin/env bash
# Create the client virtualenv. Run once, on a login node, from the repo root.
#
# Installs only what the adapter imports. The full simworld package also wants PyQt5,
# sentence-transformers and faiss, and the adapter does not import it at all.
# Tested on the Mac: this set was enough to pass the fake checklist. Not yet tried on PACE.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pace/env.sh
source "$HERE/env.sh"
wmloop_require WMLOOP_MODULES WMLOOP_VENV
wmloop_load_modules

python3 -m venv "$WMLOOP_VENV"
"$WMLOOP_VENV/bin/pip" install --upgrade pip
"$WMLOOP_VENV/bin/pip" install "unrealcv==1.3.2" "pydantic>=2" numpy pillow
"$WMLOOP_VENV/bin/python" -c "import unrealcv, pydantic, numpy, PIL; print('client env ok, unrealcv', unrealcv.__version__)"

echo "Checking the client against the fake server (no GPU needed):"
"$WMLOOP_VENV/bin/python" "$HERE/wmloop_one_tick.py" --fake --checklist
