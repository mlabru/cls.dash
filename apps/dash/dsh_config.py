# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_config
configuração do dashboard desktop (dashViewQt) e do control pad (dashCtrlPad).
Só constantes.

o que fica aqui:
  - rede: IP e porta UDP pelos quais o control pad comanda o dashboard;
  - aparência do cabeçalho;
  - arquivo de alerta e imagem de "indisponível" (vindos de dshcore.dsc_env);
  - temporização.

as páginas NÃO ficam mais aqui: vêm do config.json comum com o dashboard
web (apps/be/config.json, lido por dsh_nowcast via dshcore.dsc_config).

2026.nov  mlabru  páginas, caminhos dos dados e nowcast saem daqui: config.json
                  e regra de nowcast comuns com o web (apps/dshcore); saem
                  CLST_PAGES, CLST_PAGE_NAMES, CLST_NOWCAST_RADARS e os
                  CS_*_DATA
2026.nov  mlabru  DASH_LISTEN_ADDRESS e DASH_ALLOWED_IPS: interface de escuta e
                  IPs autorizados do servidor UDP
2026.nov  mlabru  monitor de recepção lê $RSM_PATH/data/output/rsm_out.png (o
                  nome que o 21.mrad gera e o dash_sync.sh traz), não mais
                  $DASH_DATA/output/monrad.png; CS_RSM_PATH
2026.out  mlabru  nowcast: uma página por radar (oflow + u-net), sai
                  CI_NOWCAST_RADARS_PER_PAGE; UNET_DATA com o padrão do
                  25.u-net (unet/data, não unet/data)
2026.out  mlabru  entrada de nowcast (mosaicos do 25.oflow, uma linha por
                  radar) no lugar das 3 páginas de optical flow, que usavam
                  nomes que o pipeline nunca gerou (CGU-400_ocv.gif, ...)
                  e tinham Pico do Couto duplicado; CS_NO_CAST_IMAGE
2026.out  mlabru  refatoração para legibilidade: CI_PAGE_TIME renomeado para
                  CI_UPDATE_INTERVAL_MS (o nome antigo sugeria a duração da
                  página); estilo do cabeçalho sem continuação com "\\"
                  movido para apps/dash/ (importado como dash.dsh_config)
2026.jan  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import os

# locals
from dshcore import dsc_env

# < rede >─────────────────────────────────────────────────────────────────────────────

# IP padrão do computador onde o dashboard (dashViewQt) roda; o control pad
# mostra este valor num campo editável
CS_DASHBOARD_IP = "127.0.0.1"

# porta UDP em que o dashboard escuta os comandos do control pad
CI_DASHBOARD_PORT = 5005

# interface em que o dashboard escuta: "0.0.0.0" (padrão) aceita o pad de
# outra máquina; "127.0.0.1" só o pad local (o alerta, que é por arquivo, já
# exige o pad no mesmo disco)
CS_DASHBOARD_LISTEN_ADDRESS = os.getenv("DASH_LISTEN_ADDRESS", "0.0.0.0")

# IPs de onde o dashboard aceita comandos (DASH_ALLOWED_IPS, separados por
# vírgula); vazio = qualquer um. O protocolo não tem autenticação: sem esta
# lista, qualquer máquina que alcance a porta navega o videowall
CSET_DASHBOARD_ALLOWED_IPS = frozenset(ls_ip.strip()
                                       for ls_ip in os.getenv("DASH_ALLOWED_IPS", "").split(",")
                                       if ls_ip.strip())

# < aparência >────────────────────────────────────────────────────────────────────────

# texto do cabeçalho em operação normal
CS_HEADER = "Monitoramento de Tempo Severo"

# stylesheet (QSS) do cabeçalho em operação normal
CS_HEADER_STYLE = ("color: white; "
                   "background-color: transparent; "
                   "font-size: 30px; "
                   "font-weight: bold; "
                   "padding: 10px;")

# < arquivos >──────────────────────────────────────────────────────────────────────────

# enquanto este arquivo existir, o dashboard fica em modo de alerta
# prioritário (preso na página 0). O control pad cria/apaga o arquivo, então
# os dois programas precisam enxergar o mesmo disco
CS_ALERT_TRIGGER = dsc_env.CS_ALERT_TRIGGER

# imagem de "indisponível" dos tiles (a mesma do dashboard web)
CS_NO_CAST_IMAGE = dsc_env.CS_NO_CAST_IMAGE

# < temporização >─────────────────────────────────────────────────────────────────────

# intervalo (ms) do timer do dashboard: a cada disparo ele confere o arquivo
# de alerta, avança a barra de progresso e troca de página se o tempo acabou
CI_UPDATE_INTERVAL_MS = 100

# < the end >──────────────────────────────────────────────────────────────────────────
