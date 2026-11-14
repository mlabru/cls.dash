#!/usr/bin/env bash
#
# dash_dsk.sh
#
# Sobe em background o dashboard desktop PyQt5 (videowall): dashViewQt.py.
#
# Uso:
#   ./dash_dsk.sh
#
# Variáveis de ambiente opcionais:
#   DASHBOARD_SCREEN  índice da tela para dashViewQt.py (0=monitor, 1=TV)
#
# PIDs ficam em data/run/<componente>.pid, logs em logs/<componente>.log.
# Use ./dash_off.sh desktop para parar o que este script iniciar.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/dsh_common.sh"

DASHBOARD_SCREEN="${DASHBOARD_SCREEN:-}"

if [ -n "$DASHBOARD_SCREEN" ]; then
    start_one desktop "$APPS_DIR" python3 dashViewQt.py "$DASHBOARD_SCREEN"
else
    start_one desktop "$APPS_DIR" python3 dashViewQt.py
fi
status=$?

echo
echo "logs em:          ${LOG_DIR#$REPO_ROOT/}/"
echo "para parar:       ./dash_off.sh desktop"

exit "$status"
