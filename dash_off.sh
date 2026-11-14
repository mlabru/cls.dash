#!/usr/bin/env bash
#
# dash_off.sh
#
# Para os programas iniciados por ./dash_web.sh, ./dash_dsk.sh ou
# ./dash_pad.sh, usando os PIDs
# gravados em data/run/<componente>.pid. Cada processo foi lançado com setsid
# (sessão/grupo de processos próprios), então o PID gravado também é o
# PGID do grupo — isso permite matar de uma vez o processo principal e
# quaisquer filhos que ele tenha criado (ex.: o processo de reload do
# Werkzeug quando o backend Flask roda com FLASK_DEBUG=true), que não
# morreriam só com um "kill" no PID isolado.
#
# Uso:
#   ./dash_off.sh [all|web|desktop|ctrlpad]
#
#   all       backend + frontend + desktop + ctrlpad (padrão)
#   web       backend + frontend (dashboard web)
#   desktop   dashViewQt.py (videowall PyQt5)
#   ctrlpad   dashCtrlPad.py (control pad PyQt5)

set -u -o pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$REPO_ROOT/data/run"

ALL_COMPONENTS="backend frontend desktop ctrlpad"

resolve_group() {
    case "$1" in
        all|"")   echo "$ALL_COMPONENTS" ;;
        web)      echo "backend frontend" ;;
        desktop)  echo "desktop" ;;
        ctrlpad)  echo "ctrlpad" ;;
        *)
            echo "grupo desconhecido: '$1' (use all, web, desktop ou ctrlpad)" >&2
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# stop_one <nome>
# ---------------------------------------------------------------------------

stop_one() {
    local name="$1"
    local pidfile="$RUN_DIR/$name.pid"
    local pid

    if [ ! -s "$pidfile" ]; then
        echo "[$name] não está rodando (sem pidfile)"
        return 0
    fi

    pid="$(cat "$pidfile")"

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "[$name] pidfile órfão (processo $pid não existe mais) — removendo"
        rm -f "$pidfile"
        return 0
    fi

    echo "[$name] parando (PID $pid)..."

    # -$pid = todo o grupo de processos (setsid fez o PID coincidir com o PGID);
    # se o grupo já não existir mais por algum motivo, cai para matar só o PID
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

    local i
    for i in $(seq 1 25); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.2
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "[$name] não respondeu a SIGTERM em 5s, forçando com SIGKILL"
        kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        sleep 0.3
    fi

    rm -f "$pidfile"
    echo "[$name] parado"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

components="$(resolve_group "${1:-all}")" || exit 1

for name in $components; do
    stop_one "$name"
done
