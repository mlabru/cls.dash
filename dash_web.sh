#!/usr/bin/env bash
#
# dash_web.sh
#
# Sobe em background o dashboard web: backend Flask (apps/be, servido pelo
# gunicorn) + frontend estático (apps/fe, servido pelo apps/fe/fe_server.py:
# o http.server com "Cache-Control: no-cache", para o navegador pegar o
# app.js/style.css novos logo após um deploy, sem "?v=" no index.html).
#
# O backend roda no gunicorn, e não com "python3 app.py": o servidor de
# desenvolvimento do Flask, com FLASK_DEBUG=true e HOST=0.0.0.0, expõe na rede
# o debugger do Werkzeug (execução remota de código). O gunicorn ignora
# FLASK_DEBUG. Para depurar, rode "python3 app.py" à mão, em apps/be.
#
# Uso:
#   ./dash_web.sh
#
# Variáveis de ambiente opcionais:
#   FRONTEND_PORT     porta do servidor estático do frontend (padrão 8080,
#                     precisa bater com CORS_ORIGINS em apps/be/.env)
#   BACKEND_WORKERS   processos do gunicorn (padrão 4)
#
# HOST e PORT do backend vêm de apps/be/.env (padrão 0.0.0.0:8000): o
# gunicorn precisa deles antes de importar o app, que é quem lê o .env.
#
# PIDs ficam em data/run/<componente>.pid, logs em logs/<componente>.log.
# Use ./dash_off.sh web para parar o que este script iniciar (o gunicorn e
# seus workers estão no mesmo grupo de processos).
#
# 2026.nov  mlabru  frontend no fe_server.py (no-cache) em vez de
#                   "python3 -m http.server"
# 2026.nov  mlabru  backend no gunicorn em vez do servidor de desenvolvimento

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/dsh_common.sh"

FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BACKEND_WORKERS="${BACKEND_WORKERS:-4}"

# ---------------------------------------------------------------------------
# env_value <chave> <padrão>
#
# valor de uma chave do apps/be/.env (lido como texto, sem executar o
# arquivo); o ambiente tem precedência, como no load_dotenv do app.py
# ---------------------------------------------------------------------------

env_value() {
    local key="$1" default="$2" value

    if [ -n "${!key:-}" ]; then
        echo "${!key}"
        return
    fi

    value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" \
             "$APPS_DIR/be/.env" 2>/dev/null | tail -n 1 | tr -d "\"'\r")"

    echo "${value:-$default}"
}

BACKEND_HOST="$(env_value HOST 0.0.0.0)"
BACKEND_PORT="$(env_value PORT 8000)"

if ! command -v gunicorn >/dev/null 2>&1; then
    echo "[backend] gunicorn não encontrado (pip install -r apps/be/requirements.txt)"
    exit 1
fi

status=0
start_one backend  "$APPS_DIR/be" gunicorn -w "$BACKEND_WORKERS" \
                   -b "${BACKEND_HOST}:${BACKEND_PORT}" app:app || status=1
start_one frontend "$APPS_DIR/fe" python3 fe_server.py "$FRONTEND_PORT" || status=1

echo
echo "dashboard web:    http://localhost:${FRONTEND_PORT} (frontend) / http://localhost:${BACKEND_PORT}/api/config (backend)"
echo "logs em:          ${LOG_DIR#$REPO_ROOT/}/"
echo "para parar:       ./dash_off.sh web"

exit "$status"
