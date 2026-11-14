# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_config
configuração do dashboard desktop (dashViewQt) e do control pad (dashCtrlPad).
Só constantes: nenhum código roda aqui além da montagem dos caminhos.

o que fica aqui:
  - rede: IP e porta UDP pelos quais o control pad comanda o dashboard;
  - aparência do cabeçalho;
  - caminhos dos dados (vêm dos pipelines vizinhos, fora deste repositório);
  - nowcast: radares, alcance e idade máxima dos mosaicos do 25.oflow e
    do 25.u-net (a expansão em páginas fica em dsh_nowcast);
  - CLST_PAGES: as páginas que o dashboard roda em ciclo.

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
import getpass
import os

# < rede >─────────────────────────────────────────────────────────────────────────────

# IP padrão do computador onde o dashboard (dashViewQt) roda; o control pad
# mostra este valor num campo editável
CS_DASHBOARD_IP = "127.0.0.1"

# porta UDP em que o dashboard escuta os comandos do control pad
CI_DASHBOARD_PORT = 5005

# < aparência >────────────────────────────────────────────────────────────────────────

# texto do cabeçalho em operação normal
CS_HEADER = "Monitoramento de Tempo Severo"

# stylesheet (QSS) do cabeçalho em operação normal
CS_HEADER_STYLE = ("color: white; "
                   "background-color: transparent; "
                   "font-size: 30px; "
                   "font-weight: bold; "
                   "padding: 10px;")

# < caminhos dos dados >───────────────────────────────────────────────────────────────

# usuário atual: USER pode não existir em alguns ambientes de serviço, e
# getpass.getuser() cobre LOGNAME/USERNAME e cai para o pwd do SO
CS_USER = os.environ.get("USER") or getpass.getuser()

# raiz dos dados do STSC; cada produto abaixo pode ser sobrescrito pela
# própria variável de ambiente
CS_STSC_DATA = os.getenv("STSC_DATA", f"/home/{CS_USER}/Public")

CS_BLITZ_DATA = os.getenv("BLITZ_DATA", f"{CS_STSC_DATA}/bltz/data")
CS_DASH_DATA = os.getenv("DASH_DATA", f"{CS_STSC_DATA}/dash/data")
CS_GOES_DATA = os.getenv("GOES_DATA", f"{CS_STSC_DATA}/goes/data")
CS_OFLOW_DATA = os.getenv("OFLOW_DATA", f"{CS_STSC_DATA}/oflw/data")
# padrão = UNT_PATH do 25.u-net (/home/$USER/Public/unet) + data
CS_UNET_DATA = os.getenv("UNET_DATA", f"{CS_STSC_DATA}/unet/data")
# raiz do monitor de recepção (21.mrad): mesma variável e mesmo padrão do
# rsm_cfg.sh dele e do dash_sync.sh, que traz o rsm_out.png para cá
CS_RSM_PATH = os.getenv("RSM_PATH", f"/home/{CS_USER}/Public/mrad")

# enquanto este arquivo existir, o dashboard fica em modo de alerta
# prioritário (preso na página 0). O control pad cria/apaga o arquivo, então
# os dois programas precisam enxergar o mesmo disco
CS_ALERT_TRIGGER = os.path.join(CS_STSC_DATA, "ALERTA_ATIVO.txt")

# imagem de "indisponível" dos tiles: a mesma que o 25.oflow põe no lugar de
# uma previsão que falhou (o dashboard web usa a mesma variável)
CS_NO_CAST_IMAGE = os.getenv("OFL_NO_CAST_IMAGE", f"{CS_OFLOW_DATA}/assets/no_cast.png")

# < nowcast >──────────────────────────────────────────────────────────────────────────

# radares das páginas de nowcast, na ordem de exibição: (sigla, nome). Lista
# fixa: o número de botões do control pad não depende do que há no disco
CLST_NOWCAST_RADARS = [
    ("BEL", "Belém"),
    ("BVA", "Boa Vista"),
    ("CGU", "Canguçu"),
    ("MDI", "Morro da Igreja"),
    ("PCO", "Pico do Couto"),
    ("SRO", "São Roque"),
    ("STI", "Santiago"),
]

# só os mosaicos deste alcance são exibidos
CI_NOWCAST_RANGE_KM = 400

# mosaico mais velho que isso = fora do ar: vira "indisponível" na sua linha
# (e o radar some se os dois mosaicos estiverem assim)
CI_NOWCAST_MAX_AGE_HOURS = int(os.getenv("NOWCAST_MAX_AGE_HOURS", "2"))

# < páginas >──────────────────────────────────────────────────────────────────────────

# cada página tem:
#   "duration": segundos que a página fica na tela;
#   "name":     texto do cabeçalho e do botão de atalho no control pad;
#   "tiles":    lista de tuplas (título, caminho_do_arquivo), no máximo 3.
#
# uma entrada com "type": "nowcast" (e "radars" no lugar de "tiles") vira, em
# tempo de execução, quantas páginas forem necessárias (dsh_nowcast); no
# control pad ela é um botão só.
#
# o tipo de mídia (imagem, GIF ou vídeo) sai da extensão do arquivo; se o
# arquivo não existir, o tile tenta a mesma base com .mp4/.gif/.png/.jpg
# (ver wid_tile.CT_FALLBACK_EXTENSIONS).
#
# atenção: este formato NÃO é o do dashboard web (apps/be/config.json, onde
# cada tile é um dict com "type" explícito). São independentes.
CLST_PAGES = [
    { "duration": 15, "name": "Monitor de Recepção de Dados",
      "tiles": [ ("Dados Radar",
                 f"{CS_RSM_PATH}/data/output/rsm_out.png") ]
    },
    { "duration": 15, "name": "Monitoramento de Raios",
      "tiles": [ ("Incidência de Raios (STSC)",
                 f"{CS_BLITZ_DATA}/output/slm_now.png"),
                 ("Incidência de Raios (STSC)",
                 f"{CS_BLITZ_DATA}/output/slm_out.gif") ]
    },
    { "duration": 15, "name": "GOES-19",
      "tiles": [ ("Satélite GOES-19 (ch.13)",
                 f"{CS_GOES_DATA}/goes19/13/output/goes1913.gif") ]
    },
    { "type": "nowcast", "duration": 20, "name": "Nowcast Radar 400 km",
      "radars": CLST_NOWCAST_RADARS
    },
]

# nomes das páginas, na mesma ordem: viram os botões "IR PARA PÁGINA" do pad
CLST_PAGE_NAMES = [ldct_page["name"] for ldct_page in CLST_PAGES]

# < temporização >─────────────────────────────────────────────────────────────────────

# intervalo (ms) do timer do dashboard: a cada disparo ele confere o arquivo
# de alerta, avança a barra de progresso e troca de página se o tempo acabou
CI_UPDATE_INTERVAL_MS = 100

# < the end >──────────────────────────────────────────────────────────────────────────
