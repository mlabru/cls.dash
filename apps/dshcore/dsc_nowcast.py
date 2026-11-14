# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsc_nowcast
a regra das páginas de nowcast, comum aos dois dashboards.

uma entrada {"type": "nowcast", "name", "duration", "radars": [[id, nome]]}
do config.json vira uma página por radar, com duas linhas ("layout":
"rows"), uma por origem (CT_NOWCAST_SOURCES): o mosaico <R>_400_now_mosaico.gif
do 25.oflow (os 3 métodos de fluxo óptico lado a lado) e, embaixo, o de mesmo
nome do 25.u-net (os 3 backends de deep learning).
  - mosaico ausente ou mais velho que dsc_env.CI_NOWCAST_MAX_AGE_HOURS: a
    linha fica "indisponível" (título "...: sem atualização há mais de N h");
  - radar com as duas linhas assim fica oculto (log a cada mudança do
    conjunto de ocultos; com vários processos, como os workers do gunicorn,
    ver set_hidden_state_file);
  - todos ocultos: uma página só, com um tile "indisponível";
  - nome da página com "(k/n)" quando há mais de uma;
  - os ocultos vão no "notice" de cada página gerada.

quem formata os tiles é cada app (build_pages recebe a função): o web faz
um dict com a URL /media/nowcast/<origem>/<gif>, o desktop (título, caminho).

2026.nov  mlabru  set_hidden_state_file: a mudança dos radares ocultos é
                  logada uma vez só entre processos (cada worker do
                  gunicorn logava a mesma mudança)
2026.nov  mlabru  initial version: regra que estava duplicada em
                  apps/be/app.py e apps/dash/dsh_nowcast.py
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import fcntl
import logging
import os
import re
import threading

# locals
from dshcore import dsc_env
from dshcore.dsc_config import CS_NOWCAST_PAGE_TYPE  # noqa: F401  (reexportado)

# < constants >────────────────────────────────────────────────────────────────────────

# só os mosaicos deste alcance são exibidos
CI_NOWCAST_RANGE_KM = 400

# origens dos mosaicos, na ordem das linhas da página: (chave, rótulo no título)
CT_NOWCAST_SOURCES = (("oflow", "Fluxo óptico"),
                      ("unet", "U-Net"))

# nome de mosaico atual (os diretórios de saída têm outros GIFs e .jsonl)
CS_MOSAIC_PATTERN = re.compile(r"^[A-Z0-9]+_\d+_now_mosaico\.gif$")

# título do tile da página única mostrada quando nenhum radar tem mosaico recente
CS_NO_RADAR_TITLE = "Nenhum radar com nowcast recente"

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < global state >─────────────────────────────────────────────────────────────────────

# radares ocultos na última expansão: só loga quando o conjunto muda
G_HIDDEN_RADARS = set()
G_HIDDEN_RADARS_LOCK = threading.Lock()

# estado compartilhado entre processos (ver set_hidden_state_file); None = só
# o estado do processo (desktop)
G_HIDDEN_STATE_FILE = None
G_HIDDEN_STATE_TOKEN = None

# ─────────────────────────────────────────────────────────────────────────────────────
def set_hidden_state_file(fs_path, fs_token: str) -> None:
    """
    faz o log dos radares ocultos ser único entre os processos que usam o
    mesmo arquivo: cada worker do gunicorn é um processo com o próprio
    G_HIDDEN_RADARS e logava a mesma mudança (4 vezes com -w 4).

    o arquivo guarda "<token> <siglas>"; quem vê a mudança primeiro grava e
    loga, os outros acham o mesmo conteúdo e se calam. Um token diferente (o
    do arquivo é de uma execução anterior) conta como estado desconhecido:
    depois de reiniciar, o estado atual vai de novo para o log novo.

    :param fs_path: arquivo de estado (None desliga, volta ao só-processo)
    :param fs_token: identifica a execução, igual em todos os processos dela
                     (o backend usa o PID do mestre do gunicorn)
    """
    global G_HIDDEN_STATE_FILE, G_HIDDEN_STATE_TOKEN

    G_HIDDEN_STATE_FILE = fs_path
    G_HIDDEN_STATE_TOKEN = str(fs_token)

# ─────────────────────────────────────────────────────────────────────────────────────
def build_pages(fdct_entry: dict, ff_now: float, ff_make_tile) -> list:
    """
    as páginas de uma entrada de nowcast (ver o topo do módulo).

    :param fdct_entry: {"type": "nowcast", "name", "duration", "radars"}
    :param ff_now: instante de referência (time.time()) para a idade dos mosaicos
    :param ff_make_tile: função(linha) -> tile do app; "linha" é um dict de
                         radar_rows (ou o da página "nenhum radar", com
                         "available": False e "source": None)
    :returns: lista com pelo menos uma página {"name", "duration", "notice",
              "tiles", "layout"?}; "notice" é "" se não houver ocultos
    """
    llst_visible, llst_hidden, _ = radar_rows(fdct_entry, ff_now)

    _log_hidden_radars_change({ls_radar_id for ls_radar_id, _ in llst_hidden})

    ls_notice = hidden_radars_notice(llst_hidden)

    if not llst_visible:
        ldct_row = {"source": None, "title": CS_NO_RADAR_TITLE, "available": False,
                    "file_name": None, "path": None, "mtime": None}

        return [{"name": fdct_entry["name"], "duration": fdct_entry["duration"],
                 "notice": ls_notice, "tiles": [ff_make_tile(ldct_row)]}]

    li_page_count = len(llst_visible)
    llst_pages = []

    for li_page, llst_rows in enumerate(llst_visible):
        ls_name = fdct_entry["name"]

        if li_page_count > 1:
            ls_name = f"{ls_name} ({li_page + 1}/{li_page_count})"

        llst_pages.append({"name": ls_name, "duration": fdct_entry["duration"],
                           "notice": ls_notice, "layout": "rows",
                           "tiles": [ff_make_tile(ldct_row) for ldct_row in llst_rows]})

    return llst_pages

# ─────────────────────────────────────────────────────────────────────────────────────
def radar_rows(fdct_entry: dict, ff_now: float):
    """
    o estado de cada radar de uma entrada de nowcast. Usada por build_pages
    e pelo /health do web.

    :param fdct_entry: {"type": "nowcast", "radars": [[sigla, nome]], ...}
    :param ff_now: instante de referência
    :returns: ([linhas de cada radar visível], [(sigla, nome)] dos ocultos,
              ["SIGLA/origem"] das linhas indisponíveis de radares visíveis).
              Cada linha é {"source", "title", "available", "file_name",
              "path", "mtime"}; "mtime" é None se indisponível
    """
    llst_visible = []
    llst_hidden = []
    llst_unavailable = []

    for ls_radar_id, ls_radar_name in fdct_entry["radars"]:
        llst_rows = [_source_row(ls_radar_id, ls_radar_name, ls_source, ls_label, ff_now)
                     for ls_source, ls_label in CT_NOWCAST_SOURCES]

        if not any(ldct_row["available"] for ldct_row in llst_rows):
            llst_hidden.append((ls_radar_id, ls_radar_name))
            continue

        llst_visible.append(llst_rows)
        llst_unavailable.extend(f"{ls_radar_id}/{ldct_row['source']}"
                                for ldct_row in llst_rows if not ldct_row["available"])

    return llst_visible, llst_hidden, llst_unavailable

# ─────────────────────────────────────────────────────────────────────────────────────
def _source_row(fs_radar_id: str, fs_radar_name: str, fs_source: str, fs_label: str,
                ff_now: float) -> dict:
    """
    :returns: a linha de uma origem de um radar (ver radar_rows)
    """
    ls_title = f"{fs_radar_name} ({fs_radar_id}) - {fs_label}"
    ls_file_name = mosaic_name(fs_radar_id)
    ls_path = os.path.join(source_output_dir(fs_source), ls_file_name)

    lf_mtime = _get_mtime_or_none(ls_path)

    if not is_mosaic_fresh(lf_mtime, ff_now):
        return {"source": fs_source, "available": False, "file_name": ls_file_name,
                "path": ls_path, "mtime": None,
                "title": f"{ls_title}: sem atualização há mais de "
                         f"{dsc_env.CI_NOWCAST_MAX_AGE_HOURS} h"}

    return {"source": fs_source, "available": True, "file_name": ls_file_name,
            "path": ls_path, "mtime": lf_mtime, "title": ls_title}

# ─────────────────────────────────────────────────────────────────────────────────────
def source_output_dir(fs_source: str):
    """
    lido a cada chamada para os testes poderem trocar dsc_env.

    :param fs_source: chave da origem ("oflow" ou "unet")
    :returns: diretório dos mosaicos da origem, ou None se ela não existir
    """
    ls_root = {"oflow": dsc_env.CS_OFLOW_DATA, "unet": dsc_env.CS_UNET_DATA}.get(fs_source)

    return None if ls_root is None else os.path.join(ls_root, "output")

# ─────────────────────────────────────────────────────────────────────────────────────
def mosaic_name(fs_radar_id: str) -> str:
    """
    :param fs_radar_id: sigla do radar (ex.: "CGU")
    :returns: nome do mosaico atual, ex.: "CGU_400_now_mosaico.gif"
    """
    return f"{fs_radar_id}_{CI_NOWCAST_RANGE_KM}_now_mosaico.gif"

# ─────────────────────────────────────────────────────────────────────────────────────
def is_mosaic_fresh(ff_mtime, ff_now: float) -> bool:
    """
    :param ff_mtime: mtime do mosaico, ou None se ele não existir
    :param ff_now: instante de referência
    :returns: True se existe e não passou de dsc_env.CI_NOWCAST_MAX_AGE_HOURS
    """
    if ff_mtime is None:
        return False

    return ff_now - ff_mtime <= dsc_env.CI_NOWCAST_MAX_AGE_HOURS * 3600

# ─────────────────────────────────────────────────────────────────────────────────────
def hidden_radars_notice(flst_hidden: list) -> str:
    """
    :param flst_hidden: [(sigla, nome)] dos radares ocultos
    :returns: ex.: "Sem atualização há mais de 2 h: Santiago (STI)", ou ""
    """
    if not flst_hidden:
        return ""

    ls_radars = ", ".join(f"{ls_name} ({ls_id})" for ls_id, ls_name in flst_hidden)

    return f"Sem atualização há mais de {dsc_env.CI_NOWCAST_MAX_AGE_HOURS} h: {ls_radars}"

# ─────────────────────────────────────────────────────────────────────────────────────
def _get_mtime_or_none(fs_path: str):
    """
    :returns: mtime do arquivo, ou None se ele não existir (os pipelines
              regravam os produtos, ele pode sumir a qualquer momento)
    """
    try:
        return os.path.getmtime(fs_path)

    except OSError:
        return None

# ─────────────────────────────────────────────────────────────────────────────────────
def _log_hidden_radars_change(fset_hidden: set) -> None:
    """
    registra no log quando o conjunto de radares ocultos muda: ocultar é
    discreto na tela, o log é o rastro de que um radar saiu do ar.

    :param fset_hidden: siglas dos radares ocultos agora
    """
    with G_HIDDEN_RADARS_LOCK:
        if fset_hidden == G_HIDDEN_RADARS:
            return

        G_HIDDEN_RADARS.clear()
        G_HIDDEN_RADARS.update(fset_hidden)

        if not _claim_hidden_change(fset_hidden):
            return

    if fset_hidden:
        M_LOG.warning("nowcast: radares ocultos (sem mosaico ou mais velho que %dh): %s",
                      dsc_env.CI_NOWCAST_MAX_AGE_HOURS, ", ".join(sorted(fset_hidden)))

    else:
        M_LOG.info("nowcast: todos os radares com mosaico recente")

# ─────────────────────────────────────────────────────────────────────────────────────
def _claim_hidden_change(fset_hidden: set) -> bool:
    """
    registra a mudança no arquivo de estado (se houver, ver
    set_hidden_state_file), com flock para dois workers não lerem o mesmo
    conteúdo antigo ao mesmo tempo.

    :param fset_hidden: siglas dos radares ocultos agora
    :returns: True se este processo deve logar a mudança (sem arquivo, ou
              outro processo ainda não a gravou); em erro de E/S também
              True: um log repetido é melhor que nenhum
    """
    if G_HIDDEN_STATE_FILE is None:
        return True

    ls_state = f"{G_HIDDEN_STATE_TOKEN} {','.join(sorted(fset_hidden))}"

    try:
        with open(G_HIDDEN_STATE_FILE, "a+", encoding="utf-8") as l_file:
            fcntl.flock(l_file, fcntl.LOCK_EX)

            l_file.seek(0)

            if l_file.read() == ls_state:
                return False

            l_file.seek(0)
            l_file.truncate()
            l_file.write(ls_state)

            return True

    except OSError as l_error:
        M_LOG.warning("nowcast: estado dos radares ocultos (%s) inacessível: %s",
                      G_HIDDEN_STATE_FILE, l_error)

        return True

# < the end >──────────────────────────────────────────────────────────────────────────
