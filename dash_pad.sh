#!/usr/bin/env bash
#
# dash_pad.sh
#
# Sobe em background o control pad PyQt5 (dashCtrlPad.py), que comanda o
# dashboard desktop por UDP.
#
# Uso:
#   ./dash_pad.sh
#
# PIDs ficam em data/run/<componente>.pid, logs em logs/<componente>.log.
# Use ./dash_off.sh ctrlpad para parar o que este script iniciar.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/dsh_common.sh"

start_one ctrlpad "$APPS_DIR" python3 dashCtrlPad.py
status=$?

echo
echo "logs em:          ${LOG_DIR#$REPO_ROOT/}/"
echo "para parar:       ./dash_off.sh ctrlpad"

exit "$status"
