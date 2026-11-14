# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_nowcast
páginas do dashboard desktop a partir do config.json comum com o web
(apps/be/config.json): lê a configuração (load_config) e monta as páginas
que de fato vão para a tela ("páginas de execução", build_runtime_pages).

  - páginas comuns: cada tile vira (título, caminho absoluto), com o caminho
    montado pela raiz do config.json (dshcore.dsc_config.tile_path);
  - entradas de nowcast: a regra é a de dshcore.dsc_nowcast (a mesma do web);
    aqui só a linha vira (título, caminho do mosaico) ou (título,
    gc.CS_NO_CAST_IMAGE) se indisponível.

cada página de execução leva "source_index", o índice da entrada de origem
no config.json: os botões GOTO do control pad indexam a configuração, não as
páginas de execução (que mudam com a idade dos arquivos).

config.json inválido depois de já ter sido lido: o desktop continua com a
última versão válida (e registra o erro); o videowall não pode cair por um
erro de digitação na config.

2026.nov  mlabru  config.json e regra de nowcast comuns com o web (apps/dshcore):
                  sai a cópia da regra que existia aqui; load_config e
                  page_names
2026.out  mlabru  uma página por radar: mosaico do 25.oflow na 1ª linha e do
                  25.u-net na 2ª (sai gc.CI_NOWCAST_RADARS_PER_PAGE)
2026.out  mlabru  "notice" com os radares ocultos
2026.out  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging

# locals
import dash.dsh_config as gc
from dshcore import dsc_config as dc
from dshcore import dsc_env as de
from dshcore import dsc_nowcast as dn

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < global state >─────────────────────────────────────────────────────────────────────

# cache do config.json (relido só quando muda)
G_CONFIG_CACHE = dc.CConfigCache()

# último erro de config registrado: só loga quando muda (load_config roda a
# cada troca de página)
G_LAST_CONFIG_ERROR = None

# ─────────────────────────────────────────────────────────────────────────────────────
def load_config():
    """
    a configuração atual; se o config.json estiver ausente ou inválido, a
    última versão válida.

    :returns: dict da configuração, ou None se ela nunca pôde ser lida
    """
    global G_LAST_CONFIG_ERROR

    try:
        ldct_config = G_CONFIG_CACHE.load(de.CS_CONFIG_FILE)

    except dc.CT_CONFIG_ERRORS as l_error:
        if str(l_error) != G_LAST_CONFIG_ERROR:
            G_LAST_CONFIG_ERROR = str(l_error)
            M_LOG.error("config.json (%s) inválido, usando a última versão válida: %s",
                        de.CS_CONFIG_FILE, l_error)

        return G_CONFIG_CACHE.last_good

    G_LAST_CONFIG_ERROR = None

    return ldct_config

# ─────────────────────────────────────────────────────────────────────────────────────
def page_names() -> list:
    """
    :returns: o nome de cada entrada do config.json, na ordem (os botões
              "IR PARA PÁGINA" do control pad); [] se não houver config
    """
    ldct_config = load_config()

    if ldct_config is None:
        return []

    return [ldct_page["name"] for ldct_page in ldct_config["pages"]]

# ─────────────────────────────────────────────────────────────────────────────────────
def build_runtime_pages(fdct_config: dict, ff_now: float) -> list:
    """
    páginas de execução a partir da configuração (ver o topo do módulo).

    :param fdct_config: configuração de load_config (não é alterada)
    :param ff_now: instante de referência (time.time()) para a idade dos mosaicos
    :returns: lista de páginas {"name", "duration", "notice", "tiles":
              [(título, caminho)], "layout"?, "source_index"}
    """
    llst_pages = []

    for li_source_index, ldct_page in enumerate(fdct_config["pages"]):
        if ldct_page.get("type") == dc.CS_NOWCAST_PAGE_TYPE:
            llst_expanded = dn.build_pages(ldct_page, ff_now, _nowcast_tile)

        else:
            llst_expanded = [_regular_page(fdct_config, ldct_page)]

        for ldct_expanded in llst_expanded:
            ldct_expanded["source_index"] = li_source_index
            llst_pages.append(ldct_expanded)

    return llst_pages

# ─────────────────────────────────────────────────────────────────────────────────────
def _regular_page(fdct_config: dict, fdct_page: dict) -> dict:
    """
    :param fdct_config: configuração (raízes)
    :param fdct_page: página comum do config.json
    :returns: página de execução (cópia; a config não é alterada)
    """
    ldct_page = {"name": fdct_page["name"],
                 "duration": fdct_page["duration"],
                 "notice": fdct_page.get("notice", ""),
                 "tiles": [(ldct_tile.get("title", ""), dc.tile_path(fdct_config, ldct_tile))
                           for ldct_tile in fdct_page["tiles"]]}

    if "layout" in fdct_page:
        ldct_page["layout"] = fdct_page["layout"]

    return ldct_page

# ─────────────────────────────────────────────────────────────────────────────────────
def _nowcast_tile(fdct_row: dict) -> tuple:
    """
    :param fdct_row: linha de dsc_nowcast.radar_rows
    :returns: (título, caminho do mosaico), ou (título, imagem de
              "indisponível") se a linha estiver indisponível
    """
    if not fdct_row["available"]:
        return fdct_row["title"], gc.CS_NO_CAST_IMAGE

    return fdct_row["title"], fdct_row["path"]

# < the end >──────────────────────────────────────────────────────────────────────────
