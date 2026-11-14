#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# dash_sync.sh
# script cron-driven (a cada 1 min) do host de exibição: puxa do host de
# cálculo (GPU) os produtos prontos que os dashboards e o rsmGUI mostram.
#
# Divisão em dois hosts (2026.nov): o host de cálculo roda 21.mvol,
# 27.nowcast, 25.oflow, 25.u-net e o rsm_run.sh (tudo o que abre o
# catalog.db, que é SQLite e não pode ser compartilhado por rede); este host
# só exibe.  A interface é só de arquivos finais, num sentido só:
# - GIFs de saída do 25.oflow e do 25.u-net -> OFLOW_DATA/output, UNET_DATA/output
# - no_cast.* do 25.oflow -> OFLOW_DATA/assets (imagem de "indisponível")
# - JSON e PNG do monrad -> RSM_PATH/data/{temp,output}
#
# workflow:
# - lock de instância (flock); ocupado -> sai com 0
# - um rsync por par (origem remota -> destino local), com:
#   - -a: preserva o mtime, então a regra "sem atualização há > N h" dos
#     dashboards mede a idade da geração, não da cópia (exige NTP nos dois
#     hosts);
#   - --delay-updates: os arquivos do par só trocam de nome no fim, então o
#     dashboard nunca vê um GIF pela metade;
#   - --exclude='.*': ignora os temporários de grava_gif_atomico;
#   - só o padrão do par (o output também tem .jsonl, monitor.json, ...).
# - a falha de um par é [warn] e não impede os outros; o rc final é 1 se
#   algum par falhou.  Uma queda do host de cálculo não precisa de lógica
#   aqui: os GIFs envelhecem e os dashboards mostram "indisponível".
#
# 2026.nov  mlabru  initial version (divisão host de cálculo × host de exibição)

# depends on: bash, rsync, ssh, flock, dsh_common.sh, cls_common.sh

set -euo pipefail

# < configuração >---------------------------------------------------------------------

# diretório deste script
LS_SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# REPO_ROOT, RUN_DIR, LOG_DIR (dsh_common.sh) e check_log_size/met_log
# (cls_common.sh, symlink compartilhado pelos projetos met)
source "${LS_SCRIPT_DIR}/dsh_common.sh"
source "${LS_SCRIPT_DIR}/cls_common.sh"

# host de cálculo ([usuário@]host); obrigatório
DASH_SYNC_HOST="${DASH_SYNC_HOST:-}"

# chave ssh (opcional; vazio = a padrão do ssh).  No host de cálculo, a
# entrada dela no authorized_keys deve ser restrita com rrsync -ro
DASH_SYNC_SSH_KEY="${DASH_SYNC_SSH_KEY:-}"

# raiz remota dos produtos: relativa ao home remoto (padrão Public, onde
# ficam oflw/, unet/ e mrad/) ou absoluta.  Com rrsync -ro restrito a essa
# raiz, defina como vazio
DASH_SYNC_REMOTE_ROOT="${DASH_SYNC_REMOTE_ROOT-Public}"

# limite de inatividade de cada rsync (s), para um host travado não segurar
# o lock além do próximo ciclo
DASH_SYNC_TIMEOUT_S="${DASH_SYNC_TIMEOUT_S:-50}"

# destinos locais: os mesmos padrões dos dashboards (dsh_config.py,
# apps/be/app.py) e do rsm_cfg.sh
STSC_DATA="${STSC_DATA:-/home/${USER:-$(id -un)}/Public}"
OFLOW_DATA="${OFLOW_DATA:-${STSC_DATA}/oflw/data}"
UNET_DATA="${UNET_DATA:-${STSC_DATA}/unet/data}"
RSM_PATH="${RSM_PATH:-/home/${USER:-$(id -un)}/Public/mrad}"

# pares "origem remota (relativa à raiz)|destino local|padrão de arquivo"
DASH_SYNC_PAIRS=(
    "oflw/data/output/|${OFLOW_DATA}/output/|*.gif"
    "oflw/data/assets/|${OFLOW_DATA}/assets/|no_cast.*"
    "unet/data/output/|${UNET_DATA}/output/|*.gif"
    "mrad/data/temp/|${RSM_PATH}/data/temp/|rsm_temp.json"
    "mrad/data/output/|${RSM_PATH}/data/output/|rsm_out.png"
)

# lock de instância
DASH_SYNC_LOCK="${RUN_DIR}/.dash_sync.lock"

# log do shell; o stderr do rsync vai para o .err
DASH_SYNC_LOG_APP="${LOG_DIR}/dash_sync.log"
DASH_SYNC_LOG_ERR="${LOG_DIR}/dash_sync.err"

# -------------------------------------------------------------------------------------
# logger do script (cls_common.sh)
#
log()
{
    met_log "${DASH_SYNC_LOG_APP}" "${DASH_SYNC_LOG_ERR}" "$@"

} # log

# -------------------------------------------------------------------------------------
# adquire o lock de instância (fd 205, mantido aberto até o fim do script).
# se outra instância já estiver rodando, sai com 0
#
acquire_instance_lock()
{
    exec 205>"${DASH_SYNC_LOCK}"

    if ! flock -n 205; then
        log "[info]: dash_sync já em execução; saindo."
        exit 0
    fi

} # acquire_instance_lock

# -------------------------------------------------------------------------------------
# comando ssh do rsync (-e): BatchMode para nunca pedir senha no cron
#
ssh_command()
{
    local ls_cmd="ssh -o BatchMode=yes"

    if [ -n "${DASH_SYNC_SSH_KEY}" ]; then
        ls_cmd="${ls_cmd} -i ${DASH_SYNC_SSH_KEY}"
    fi

    echo "${ls_cmd}"

} # ssh_command

# -------------------------------------------------------------------------------------
# sincroniza um par
#
# uso: sync_pair <origem relativa à raiz remota> <destino local> <padrão>
# retorno: o código de saída do rsync (0 = sucesso)
#
sync_pair()
{
    local ls_src="${DASH_SYNC_REMOTE_ROOT:+${DASH_SYNC_REMOTE_ROOT}/}$1"
    local ls_dst="$2" ls_pattern="$3"
    local li_rc=0

    mkdir -p "${ls_dst}"

    rsync -a --delay-updates --timeout="${DASH_SYNC_TIMEOUT_S}" \
          -e "$(ssh_command)" \
          --exclude='.*' --include="${ls_pattern}" --exclude='*' \
          "${DASH_SYNC_HOST}:${ls_src}" "${ls_dst}" \
          2>> "${DASH_SYNC_LOG_ERR}" || li_rc=$?

    return "${li_rc}"

} # sync_pair

# -------------------------------------------------------------------------------------
# fluxo principal:
#
main()
{
    local ls_pair ls_src ls_dst ls_pattern
    local li_rc li_failed=0

    mkdir -p "${RUN_DIR}" "${LOG_DIR}"

    # 1. host de cálculo configurado ?
    if [ -z "${DASH_SYNC_HOST}" ]; then
        log "[error]: DASH_SYNC_HOST não definido; nada a sincronizar."
        exit 1
    fi

    # 2. uma instância por vez
    acquire_instance_lock

    # 3. um rsync por par; a falha de um não impede os outros
    for ls_pair in "${DASH_SYNC_PAIRS[@]}"; do
        IFS='|' read -r ls_src ls_dst ls_pattern <<< "${ls_pair}"

        li_rc=0
        sync_pair "${ls_src}" "${ls_dst}" "${ls_pattern}" || li_rc=$?

        if [ "${li_rc}" -ne 0 ]; then
            log "[warn]: rsync ${DASH_SYNC_HOST}:${ls_src} (${ls_pattern}) falhou (rc=${li_rc}); veja ${DASH_SYNC_LOG_ERR}"
            li_failed=1
        fi
    done

    # 4. rc: 1 se algum par falhou (o cron registra; o próximo ciclo retenta)
    if [ "${li_failed}" -ne 0 ]; then
        exit 1
    fi

} # main

# < main >-----------------------------------------------------------------------------

# permite carregar a configuração e as funções sem executar o main (testes)
[ "${DASH_SYNC_NO_MAIN:-false}" = true ] && return 0

main

# < the end >--------------------------------------------------------------------------
