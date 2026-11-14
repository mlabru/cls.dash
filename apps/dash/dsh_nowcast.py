# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_nowcast
expande as entradas de nowcast de gc.CLST_PAGES nas páginas que de fato vão
para a tela ("páginas de execução").

uma entrada {"type": "nowcast", "name", "duration", "radars": [(sigla, nome)]}
vira uma página por radar, com duas linhas ("layout": "rows"): o mosaico
<R>_400_now_mosaico.gif do 25.oflow (os 3 métodos de fluxo óptico lado a
lado) e, embaixo, o mosaico de mesmo nome do 25.u-net (os 3 backends de deep
learning), para comparar os dois no mesmo radar. Mosaico ausente, ou mais
velho que gc.CI_NOWCAST_MAX_AGE_HOURS, vira a imagem de "indisponível"
(gc.CS_NO_CAST_IMAGE) na sua linha; radar com os dois assim fica oculto. Se
todos ficarem, sai uma página única com a imagem de "indisponível". Os
ocultos são listados no "notice" de cada página (o dashboard o mostra sob o
cabeçalho), para a ausência não passar despercebida.

cada página de execução leva "source_index", o índice da entrada de origem
em gc.CLST_PAGES: os botões GOTO do control pad indexam a configuração (fixa),
não as páginas de execução (que mudam com a idade dos arquivos).

a mesma regra existe no backend web (apps/be/app.py, _build_nowcast_pages):
os dois dashboards não compartilham código.

2026.out  mlabru  uma página por radar: mosaico do 25.oflow na 1ª linha e do
                  25.u-net na 2ª (sai gc.CI_NOWCAST_RADARS_PER_PAGE)
2026.out  mlabru  "notice" com os radares ocultos
2026.out  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging
import math
import os

# locals
import dash.dsh_config as gc

# < constants >────────────────────────────────────────────────────────────────────────

# valor de "type" da entrada de CLST_PAGES que vira páginas de nowcast
CS_NOWCAST_PAGE_TYPE = "nowcast"

# título do tile da página única mostrada quando nenhum radar tem mosaico recente
CS_NO_RADAR_TITLE = "Nenhum radar com nowcast recente"

# origens dos mosaicos, na ordem das linhas da página: (chave, rótulo no
# título do tile). O diretório de cada uma sai de _nowcast_source_dir
CT_NOWCAST_SOURCES = (("oflow", "Fluxo óptico"),
                      ("unet", "U-Net"))

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < global state >─────────────────────────────────────────────────────────────────────

# radares ocultos na última expansão: só loga quando o conjunto muda (a
# expansão roda a cada troca de página)
G_HIDDEN_RADARS = set()

# ─────────────────────────────────────────────────────────────────────────────────────
def build_runtime_pages(flst_config_pages: list, ff_now: float) -> list:
    """
    páginas de execução a partir da configuração (ver o topo do módulo).

    :param flst_config_pages: gc.CLST_PAGES (ou equivalente)
    :param ff_now: instante de referência (time.time()) para a idade dos mosaicos
    :returns: lista de páginas, cada uma com "source_index"
    """
    llst_pages = []

    for li_source_index, ldct_page in enumerate(flst_config_pages):
        if ldct_page.get("type") == CS_NOWCAST_PAGE_TYPE:
            llst_expanded = _build_nowcast_pages(ldct_page, ff_now)

        else:
            llst_expanded = [dict(ldct_page)]

        for ldct_expanded in llst_expanded:
            ldct_expanded["source_index"] = li_source_index
            llst_pages.append(ldct_expanded)

    return llst_pages

# ─────────────────────────────────────────────────────────────────────────────────────
def _build_nowcast_pages(fdct_entry: dict, ff_now: float) -> list:
    """
    gera as páginas de uma entrada de nowcast.

    :param fdct_entry: {"type": "nowcast", "name", "duration", "radars"}
    :param ff_now: instante de referência para a idade dos mosaicos
    :returns: lista com pelo menos uma página
    """
    llst_radar_tiles = []
    llst_hidden = []

    for ls_radar_id, ls_radar_name in fdct_entry["radars"]:
        llst_tiles = _radar_tiles(ls_radar_id, ls_radar_name, ff_now)

        if llst_tiles is None:
            llst_hidden.append((ls_radar_id, ls_radar_name))
            continue

        llst_radar_tiles.append(llst_tiles)

    _log_hidden_radars_change({ls_radar_id for ls_radar_id, _ in llst_hidden})

    ls_notice = _hidden_radars_notice(llst_hidden)

    if not llst_radar_tiles:
        return [{"duration": fdct_entry["duration"],
                 "name": fdct_entry["name"],
                 "notice": ls_notice,
                 "tiles": [(CS_NO_RADAR_TITLE, gc.CS_NO_CAST_IMAGE)]}]

    li_page_count = len(llst_radar_tiles)

    llst_pages = []

    for li_page, llst_tiles in enumerate(llst_radar_tiles):
        ls_name = fdct_entry["name"]

        if li_page_count > 1:
            ls_name = f"{ls_name} ({li_page + 1}/{li_page_count})"

        llst_pages.append({"duration": fdct_entry["duration"],
                           "name": ls_name,
                           "notice": ls_notice,
                           "layout": "rows",
                           "tiles": llst_tiles})

    return llst_pages

# ─────────────────────────────────────────────────────────────────────────────────────
def _radar_tiles(fs_radar_id: str, fs_radar_name: str, ff_now: float):
    """
    tiles da página de um radar: um por origem (CT_NOWCAST_SOURCES), com a
    imagem de "indisponível" no lugar de mosaico ausente ou velho.

    :param fs_radar_id: sigla do radar
    :param fs_radar_name: nome do radar
    :param ff_now: instante de referência para a idade dos mosaicos
    :returns: [(título, caminho)], ou None se nenhuma origem tiver mosaico
              recente (radar oculto)
    """
    llst_tiles = []
    lb_any_fresh = False

    for ls_source, ls_label in CT_NOWCAST_SOURCES:
        ls_title = f"{fs_radar_name} ({fs_radar_id}) - {ls_label}"
        ls_file = nowcast_mosaic_path(fs_radar_id, ls_source)

        if _is_mosaic_fresh(ls_file, ff_now):
            lb_any_fresh = True
            llst_tiles.append((ls_title, ls_file))

        else:
            llst_tiles.append((f"{ls_title}: sem atualização há mais de "
                               f"{gc.CI_NOWCAST_MAX_AGE_HOURS} h", gc.CS_NO_CAST_IMAGE))

    return llst_tiles if lb_any_fresh else None

# ─────────────────────────────────────────────────────────────────────────────────────
def _hidden_radars_notice(flst_hidden: list) -> str:
    """
    :param flst_hidden: [(sigla, nome)] dos radares ocultos
    :returns: texto do aviso, ex.: "Sem atualização há mais de 2 h: Santiago
              (STI)", ou "" se não houver ocultos
    """
    if not flst_hidden:
        return ""

    ls_radars = ", ".join(f"{ls_name} ({ls_id})" for ls_id, ls_name in flst_hidden)

    return f"Sem atualização há mais de {gc.CI_NOWCAST_MAX_AGE_HOURS} h: {ls_radars}"

# ─────────────────────────────────────────────────────────────────────────────────────
def nowcast_mosaic_path(fs_radar_id: str, fs_source: str) -> str:
    """
    :param fs_radar_id: sigla do radar (ex.: "CGU")
    :param fs_source: chave da origem ("oflow" ou "unet", CT_NOWCAST_SOURCES)
    :returns: caminho do mosaico atual do radar, ex.:
              "<OFLOW_DATA>/output/CGU_400_now_mosaico.gif"
    """
    return os.path.join(_nowcast_source_dir(fs_source), "output",
                        f"{fs_radar_id}_{gc.CI_NOWCAST_RANGE_KM}_now_mosaico.gif")

# ─────────────────────────────────────────────────────────────────────────────────────
def _nowcast_source_dir(fs_source: str) -> str:
    """
    lido a cada chamada (e não guardado em CT_NOWCAST_SOURCES) para os
    testes poderem trocar os diretórios.

    :param fs_source: chave da origem ("oflow" ou "unet", CT_NOWCAST_SOURCES)
    :returns: raiz dos dados da origem (os mosaicos ficam em output/)
    """
    if fs_source == "unet":
        return gc.CS_UNET_DATA

    return gc.CS_OFLOW_DATA

# ─────────────────────────────────────────────────────────────────────────────────────
def _is_mosaic_fresh(fs_file: str, ff_now: float) -> bool:
    """
    :param fs_file: caminho do mosaico
    :param ff_now: instante de referência
    :returns: True se o mosaico existe e não passou de gc.CI_NOWCAST_MAX_AGE_HOURS
    """
    try:
        lf_mtime = os.path.getmtime(fs_file)

    except OSError:
        return False

    return ff_now - lf_mtime <= gc.CI_NOWCAST_MAX_AGE_HOURS * 3600

# ─────────────────────────────────────────────────────────────────────────────────────
def _log_hidden_radars_change(fset_hidden: set):
    """
    registra no log quando o conjunto de radares ocultos muda. Ocultar é
    silencioso na tela, então o log é o rastro de que um radar saiu do ar.

    :param fset_hidden: siglas dos radares ocultos agora
    """
    if fset_hidden == G_HIDDEN_RADARS:
        return

    if fset_hidden:
        M_LOG.warning(f"nowcast: radares ocultos (sem mosaico ou mais velho que "
                      f"{gc.CI_NOWCAST_MAX_AGE_HOURS}h): {', '.join(sorted(fset_hidden))}")

    else:
        M_LOG.info("nowcast: todos os radares com mosaico recente")

    G_HIDDEN_RADARS.clear()
    G_HIDDEN_RADARS.update(fset_hidden)

# < the end >──────────────────────────────────────────────────────────────────────────
