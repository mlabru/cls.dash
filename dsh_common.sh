#!/usr/bin/env bash
#
# dsh_common.sh
#
# Funções e variáveis compartilhadas por dash_web.sh, dash_dsk.sh e
# dash_pad.sh. Não é executável sozinho — deve ser "sourced" a partir de um
# script que já tenha feito 'set -u -o pipefail'.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ambiente da instalação (cls.env: CLS_LIB e sobreposições), carregado
# antes dos padrões abaixo; "set -a" exporta para os programas Python.
# Precedência: ambiente do processo > cls.env > padrões deste arquivo (ver
# cls.common/etc/cls.env.example)
CLS_ENV_FILE="${CLS_ENV_FILE:-${HOME:-}/.config/cls/cls.env}"
if [ -r "${CLS_ENV_FILE}" ]; then set -a; source "${CLS_ENV_FILE}"; set +a; fi

RUN_DIR="$REPO_ROOT/data/run"
LOG_DIR="$REPO_ROOT/logs"
APPS_DIR="$REPO_ROOT/apps"

mkdir -p "$RUN_DIR" "$LOG_DIR"

# ---------------------------------------------------------------------------
# is_running <pidfile>
# ---------------------------------------------------------------------------

is_running() {
    local pidfile="$1"
    [ -s "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

# ---------------------------------------------------------------------------
# start_one <nome> <workdir> <comando...>
#
# lança o comando com setsid, em sua própria sessão/grupo de processos, e
# grava o PID real (de dentro do próprio processo, antes do exec) no
# pidfile — evita o descompasso entre o PID que o bash vê com "$!" e o PID
# de fato usado pelo comando final quando setsid precisa fazer fork interno.
# ---------------------------------------------------------------------------

start_one() {
    local name="$1" workdir="$2"
    shift 2

    local pidfile="$RUN_DIR/$name.pid"
    local logfile="$LOG_DIR/$name.log"

    if is_running "$pidfile"; then
        echo "[$name] já está rodando (PID $(cat "$pidfile"))"
        return 0
    fi

    rm -f "$pidfile"

    ( cd "$workdir" && setsid bash -c 'echo $$ > "$0"; exec "$@"' "$pidfile" "$@" ) \
        > "$logfile" 2>&1 &
    disown 2>/dev/null || true

    # espera o pidfile ser escrito pelo processo real (até ~2s)
    local i
    for i in $(seq 1 20); do
        [ -s "$pidfile" ] && break
        sleep 0.1
    done

    if [ -s "$pidfile" ]; then
        echo "[$name] iniciado (PID $(cat "$pidfile")) — log em ${logfile#$REPO_ROOT/}"
    else
        echo "[$name] falhou ao iniciar — veja ${logfile#$REPO_ROOT/}"
        return 1
    fi
}
