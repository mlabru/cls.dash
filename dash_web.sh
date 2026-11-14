#!/usr/bin/env bash
#
# dash_web.sh
#
# Sobe em background o dashboard web: backend Flask (apps/be) + frontend
# estático (apps/fe).
#
# Uso:
#   ./dash_web.sh
#
# Variáveis de ambiente opcionais:
#   FRONTEND_PORT     porta do servidor estático do frontend (padrão 8080,
#                     precisa bater com CORS_ORIGINS em apps/be/.env)
#
# PIDs ficam em data/run/<componente>.pid, logs em logs/<componente>.log.
# Use ./dash_off.sh web para parar o que este script iniciar.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/dsh_common.sh"

FRONTEND_PORT="${FRONTEND_PORT:-8080}"

status=0
start_one backend  "$APPS_DIR/be" python3 app.py || status=1
start_one frontend "$APPS_DIR/fe" python3 -m http.server "$FRONTEND_PORT" || status=1

echo
echo "dashboard web:    http://localhost:${FRONTEND_PORT} (frontend) / http://localhost:8000/api/config (backend)"
echo "logs em:          ${LOG_DIR#$REPO_ROOT/}/"
echo "para parar:       ./dash_off.sh web"

exit "$status"
