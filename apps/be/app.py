# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

app
backend do dashboard web: API JSON em Flask que serve a configuração das
páginas e os arquivos de mídia para o frontend (apps/fe).

rotas:
  GET /api/config              configuração das páginas (sem o media_dir),
                               com data e versão (mtime) de cada arquivo de
                               mídia e as páginas de nowcast já expandidas
  GET /api/state               {"alert": bool}: o arquivo de alerta
                               prioritário (CS_ALERT_TRIGGER) existe?
  GET /media/<arquivo>         o arquivo de mídia, lido de media_dir
  GET /media/nowcast/<origem>/<gif>
                               um mosaico do 25.oflow (origem "oflow", lido
                               de $OFLOW_DATA/output) ou do 25.u-net (origem
                               "unet", de $UNET_DATA/output); só nomes de
                               mosaico
  GET /media/_unavailable      a imagem de "indisponível" (OFL_NO_CAST_IMAGE)
  GET /health                  sempre HTTP 200 (sonda de vida); o corpo diz
                               se há produtos ausentes/velhos ("status":
                               "ok" ou "degraded", ver _collect_product_health)

como a configuração é carregada (load_config):
  o config.json é lido de novo só quando muda (compara caminho + mtime com a
  última leitura). Dá para editar o arquivo com o servidor no ar: a próxima
  requisição já usa a versão nova. Toda rota que precisa da configuração
  chama load_config() antes, porque no gunicorn cada worker é um processo
  com a própria cópia de G_CONFIG.

uso:
    python app.py                               # desenvolvimento (lê o .env)
    gunicorn -w 4 -b 0.0.0.0:8000 app:app       # produção

páginas de nowcast (_expand_pages, a cada /api/config):
  uma entrada {"type": "nowcast", "name", "duration", "radars": [[id, nome]]}
  do config.json vira uma página por radar, com duas linhas ("layout":
  "rows"): o mosaico <R>_400_now_mosaico.gif do 25.oflow (os 3 métodos de
  fluxo óptico lado a lado) e, embaixo, o mosaico de mesmo nome do 25.u-net
  (os 3 backends de deep learning), para comparar os dois no mesmo radar.
  Mosaico ausente, ou mais velho que CI_NOWCAST_MAX_AGE_HOURS, vira a imagem
  de "indisponível" na sua linha; radar com os dois assim fica oculto. Se
  todos ficarem, sai uma página única com a imagem de "indisponível". Os
  ocultos são listados no "notice" de cada página (o frontend o mostra no
  cabeçalho). A expansão é por requisição (e não em load_config) porque
  depende da idade dos arquivos, não do config.json.

variáveis de ambiente (ou .env): CONFIG_FILE, HOST, PORT, CORS_ORIGINS,
FLASK_DEBUG, MEDIA_MAX_AGE_HOURS, STSC_DATA, OFLOW_DATA, UNET_DATA,
NOWCAST_MAX_AGE_HOURS, OFL_NO_CAST_IMAGE (as cinco últimas com os mesmos
nomes do dashboard desktop).

2026.out  mlabru  nowcast: uma página por radar, mosaico do 25.oflow na 1ª
                  linha e do 25.u-net na 2ª (sai NOWCAST_RADARS_PER_PAGE);
                  rota /media/nowcast/<origem>/<gif>; /health com
                  "nowcast_unavailable" (linhas indisponíveis)
2026.out  mlabru  "notice" com os radares ocultos; "file_version" (mtime) nos
                  tiles, para o frontend não baixar de novo mídia que não
                  mudou; /health com o estado dos produtos; /api/state
                  (alerta prioritário, como no dashboard desktop)
2026.out  mlabru  páginas de nowcast (mosaicos do 25.oflow, uma linha por
                  radar, radares velhos ocultos); rotas /media/nowcast e
                  /media/_unavailable (no_cast.png do oflow)
2026.out  mlabru  refatoração para legibilidade: convenções do 21.mvol /
                  27.nowcast (prefixos, M_LOG, cabeçalho); estado global com
                  prefixo G_; leitura do arquivo separada da troca do estado;
                  /media chama load_config() (num worker do gunicorn que ainda
                  não tinha atendido /api/config, G_CONFIG estava vazio e
                  /media respondia 500)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import copy
import datetime
import getpass
import json
import logging
import math
import os
import re
import threading
import time

# flask
from flask import Flask, abort, jsonify, send_file, send_from_directory
from flask_cors import CORS

# dotenv
from dotenv import load_dotenv

# < environment >----------------------------------------------------------------------

# carrega o .env (se existir) para os.environ antes de ler as variáveis abaixo
load_dotenv()

CS_CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")
CS_HOST = os.environ.get("HOST", "0.0.0.0")
CI_PORT = int(os.environ.get("PORT", "8000"))
CLST_CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost").split(",")

# produto de media_dir mais velho que isso aparece como "stale" no /health
CI_MEDIA_MAX_AGE_HOURS = int(os.environ.get("MEDIA_MAX_AGE_HOURS", "2"))

# raiz dos dados do STSC (mesma variável e mesmo padrão do dashboard desktop)
CS_STSC_DATA = os.environ.get("STSC_DATA",
                              f"/home/{os.environ.get('USER') or getpass.getuser()}/Public")

# enquanto este arquivo existir, o frontend fica em modo de alerta prioritário
# (preso na página 0). É o mesmo arquivo que o control pad do dashboard
# desktop cria/apaga: o backend precisa enxergar o mesmo disco
CS_ALERT_TRIGGER = os.path.join(CS_STSC_DATA, "ALERTA_ATIVO.txt")

# raiz dos dados do 25.oflow (mesma variável e mesmo padrão do dashboard
# desktop); os mosaicos ficam em output/
CS_OFLOW_DATA = os.environ.get("OFLOW_DATA", os.path.join(CS_STSC_DATA, "oflw", "data"))
CS_OFLOW_OUTPUT_DIR = os.path.join(CS_OFLOW_DATA, "output")

# raiz dos dados do 25.u-net (mesma variável e mesmo padrão do dashboard
# desktop; UNT_PATH do u-net); os mosaicos ficam em output/, com os mesmos
# nomes dos do oflow
CS_UNET_DATA = os.environ.get("UNET_DATA", os.path.join(CS_STSC_DATA, "unet", "data"))
CS_UNET_OUTPUT_DIR = os.path.join(CS_UNET_DATA, "output")

# imagem de "indisponível": a mesma que o 25.oflow usa no lugar de uma previsão
CS_NO_CAST_IMAGE = os.environ.get("OFL_NO_CAST_IMAGE",
                                  os.path.join(CS_OFLOW_DATA, "assets", "no_cast.png"))

# mosaico mais velho que isso = radar fora do ar: o radar some da página
CI_NOWCAST_MAX_AGE_HOURS = int(os.environ.get("NOWCAST_MAX_AGE_HOURS", "2"))

# < constants >------------------------------------------------------------------------

# chaves que o config.json precisa ter
CT_REQUIRED_KEYS = ("media_dir", "pages")

# formato da data de modificação enviada ao frontend
CS_MODIFIED_DATE_FORMAT = "%d/%m/%Y %H:%M"

# valor de "type" da entrada do config.json que vira páginas de nowcast
CS_NOWCAST_PAGE_TYPE = "nowcast"

# só os mosaicos de 400 km são exibidos
CI_NOWCAST_RANGE_KM = 400

# origens dos mosaicos, na ordem das linhas da página: (chave na URL
# /media/nowcast/<chave>/, rótulo no título do tile). O diretório de cada uma
# sai de _nowcast_output_dir
CT_NOWCAST_SOURCES = (("oflow", "Fluxo óptico"),
                      ("unet", "U-Net"))

# prefixo (em /media) dos mosaicos e nome do arquivo de "indisponível"
CS_NOWCAST_MEDIA_PREFIX = "nowcast/"
CS_UNAVAILABLE_MEDIA = "_unavailable"

# os diretórios do oflow e do u-net têm outros arquivos (GIFs por backend,
# .jsonl): a rota /media/nowcast só entrega mosaicos atuais
CS_MOSAIC_PATTERN = re.compile(r"^[A-Z0-9]+_\d+_now_mosaico\.gif$")

# título da página única mostrada quando nenhum radar tem mosaico recente
CS_NO_RADAR_TITLE = "Nenhum radar com nowcast recente"

# < logging >--------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

M_LOG = logging.getLogger(__name__)

# < global state >---------------------------------------------------------------------

# última configuração válida lida do config.json
G_CONFIG = {}

# protege G_CONFIG: com servidor multithread, uma requisição pode ler enquanto
# outra recarrega
G_CONFIG_LOCK = threading.Lock()

# (caminho, mtime) da última leitura bem-sucedida; None = nunca carregado
G_CONFIG_CACHE_KEY = None

# radares de nowcast ocultos na última expansão: só loga quando o conjunto
# muda (o /api/config é chamado a cada refresh_seconds)
G_HIDDEN_RADARS = set()

# -------------------------------------------------------------------------------------
def get_config_public() -> dict:
    """
    a configuração que o frontend recebe: tudo menos "media_dir" (caminho
    interno do servidor), com "file_modified" e "file_version" em cada tile
    que tem "file" (ver _set_file_info).

    :returns: cópia independente da configuração (pode ser alterada à vontade)
    """
    with G_CONFIG_LOCK:
        # deepcopy: o laço abaixo acrescenta dados aos tiles, e uma
        # cópia rasa alteraria os dicts dentro de G_CONFIG
        ldct_public_config = copy.deepcopy(G_CONFIG)
        ls_media_dir = G_CONFIG["media_dir"]

    del ldct_public_config["media_dir"]

    ldct_public_config["pages"] = _expand_pages(ldct_public_config.get("pages", []), time.time())

    for ldct_page in ldct_public_config["pages"]:
        for ldct_tile in ldct_page.get("tiles", []):
            # tiles de nowcast já vêm com a data (o arquivo não está em media_dir)
            if "file" in ldct_tile and "file_modified" not in ldct_tile:
                _set_file_info(ldct_tile,
                               _get_mtime_or_none(os.path.join(ls_media_dir, ldct_tile["file"])))

    return ldct_public_config

# -------------------------------------------------------------------------------------
def _set_file_info(fdct_tile: dict, ff_mtime) -> None:
    """
    põe no tile a data de modificação (para o rodapé) e a versão do arquivo.

    a versão (mtime inteiro) vai na URL da mídia (?v=): enquanto o arquivo
    não muda a URL é a mesma, e o navegador só revalida (304) em vez de
    baixar o GIF de novo a cada página. Arquivo inexistente fica sem versão.

    :param fdct_tile: tile a completar (alterado no lugar)
    :param ff_mtime: mtime do arquivo, ou None se ele não existir
    """
    fdct_tile["file_modified"] = _format_mtime(ff_mtime)

    if ff_mtime is not None:
        fdct_tile["file_version"] = int(ff_mtime)

# < nowcast >--------------------------------------------------------------------------

# -------------------------------------------------------------------------------------
def _expand_pages(flst_pages: list, ff_now: float) -> list:
    """
    troca cada entrada de nowcast pelas páginas que ela gera; as demais
    páginas passam sem mudança, na mesma ordem.

    :param flst_pages: páginas do config.json
    :param ff_now: instante de referência (time.time()) para a idade dos mosaicos
    :returns: nova lista de páginas
    """
    llst_pages = []

    for ldct_page in flst_pages:
        if ldct_page.get("type") == CS_NOWCAST_PAGE_TYPE:
            llst_pages.extend(_build_nowcast_pages(ldct_page, ff_now))

        else:
            llst_pages.append(ldct_page)

    return llst_pages

# -------------------------------------------------------------------------------------
def _build_nowcast_pages(fdct_entry: dict, ff_now: float) -> list:
    """
    gera as páginas de uma entrada de nowcast (ver o topo do módulo).

    :param fdct_entry: {"type": "nowcast", "name", "duration", "radars"}
    :param ff_now: instante de referência para a idade dos mosaicos
    :returns: lista com pelo menos uma página
    """
    llst_radar_tiles, llst_hidden, _ = _nowcast_radar_status(fdct_entry, ff_now)

    _log_hidden_radars_change({ls_radar_id for ls_radar_id, _ in llst_hidden})

    ls_notice = _hidden_radars_notice(llst_hidden)

    if not llst_radar_tiles:
        return [_with_notice({"name": fdct_entry["name"],
                              "duration": fdct_entry["duration"],
                              "tiles": [{"type": "image",
                                         "file": CS_UNAVAILABLE_MEDIA,
                                         "title": CS_NO_RADAR_TITLE,
                                         "file_modified": None}]}, ls_notice)]

    li_page_count = len(llst_radar_tiles)

    llst_pages = []

    for li_page, llst_tiles in enumerate(llst_radar_tiles):
        ls_name = fdct_entry["name"]

        if li_page_count > 1:
            ls_name = f"{ls_name} ({li_page + 1}/{li_page_count})"

        llst_pages.append(_with_notice({"name": ls_name,
                                        "duration": fdct_entry["duration"],
                                        "layout": "rows",
                                        "tiles": llst_tiles},
                                       ls_notice))

    return llst_pages

# -------------------------------------------------------------------------------------
def _nowcast_radar_status(fdct_entry: dict, ff_now: float):
    """
    monta os tiles de cada radar de uma entrada de nowcast (um por origem,
    CT_NOWCAST_SOURCES) e separa os radares ocultos. Usada pela expansão das
    páginas e pelo /health.

    :param fdct_entry: {"type": "nowcast", "radars": [[sigla, nome]], ...}
    :param ff_now: instante de referência para a idade dos mosaicos
    :returns: ([tiles de cada radar visível], [(sigla, nome)] dos ocultos,
              ["SIGLA/origem"] das linhas indisponíveis de radares visíveis)
    """
    llst_radar_tiles = []
    llst_hidden = []
    llst_unavailable = []

    for ls_radar_id, ls_radar_name in fdct_entry["radars"]:
        ls_file_name = _nowcast_mosaic_name(ls_radar_id)

        llst_tiles = []
        llst_missing = []

        for ls_source, ls_label in CT_NOWCAST_SOURCES:
            ls_title = f"{ls_radar_name} ({ls_radar_id}) - {ls_label}"
            lf_mtime = _get_mtime_or_none(os.path.join(_nowcast_output_dir(ls_source),
                                                       ls_file_name))

            if not _is_mosaic_fresh(lf_mtime, ff_now):
                llst_missing.append(f"{ls_radar_id}/{ls_source}")
                llst_tiles.append(_unavailable_mosaic_tile(ls_title))
                continue

            ldct_tile = {"type": "gif",
                         "file": f"{CS_NOWCAST_MEDIA_PREFIX}{ls_source}/{ls_file_name}",
                         "title": ls_title}
            _set_file_info(ldct_tile, lf_mtime)

            llst_tiles.append(ldct_tile)

        # sem nenhum mosaico recente, a página só teria "indisponível"
        if len(llst_missing) == len(CT_NOWCAST_SOURCES):
            llst_hidden.append((ls_radar_id, ls_radar_name))
            continue

        llst_radar_tiles.append(llst_tiles)
        llst_unavailable.extend(llst_missing)

    return llst_radar_tiles, llst_hidden, llst_unavailable

# -------------------------------------------------------------------------------------
def _unavailable_mosaic_tile(fs_title: str) -> dict:
    """
    :param fs_title: título do tile ("Nome (SIGLA) - origem")
    :returns: tile com a imagem de "indisponível" no lugar do mosaico
    """
    return {"type": "image",
            "file": CS_UNAVAILABLE_MEDIA,
            "title": f"{fs_title}: sem atualização há mais de {CI_NOWCAST_MAX_AGE_HOURS} h",
            "file_modified": None}

# -------------------------------------------------------------------------------------
def _nowcast_output_dir(fs_source: str):
    """
    lido a cada chamada (e não guardado em CT_NOWCAST_SOURCES) para os
    testes poderem trocar os diretórios.

    :param fs_source: chave da origem ("oflow" ou "unet")
    :returns: diretório dos mosaicos da origem, ou None se ela não existir
    """
    return {"oflow": CS_OFLOW_OUTPUT_DIR,
            "unet": CS_UNET_OUTPUT_DIR}.get(fs_source)

# -------------------------------------------------------------------------------------
def _hidden_radars_notice(flst_hidden: list):
    """
    :param flst_hidden: [(sigla, nome)] dos radares ocultos
    :returns: texto do aviso, ex.: "Sem atualização há mais de 2 h: Santiago
              (STI)", ou None se não houver ocultos
    """
    if not flst_hidden:
        return None

    ls_radars = ", ".join(f"{ls_name} ({ls_id})" for ls_id, ls_name in flst_hidden)

    return f"Sem atualização há mais de {CI_NOWCAST_MAX_AGE_HOURS} h: {ls_radars}"

# -------------------------------------------------------------------------------------
def _with_notice(fdct_page: dict, fs_notice) -> dict:
    """
    :param fdct_page: página gerada
    :param fs_notice: aviso dos ocultos, ou None
    :returns: a própria página, com "notice" quando houver aviso
    """
    if fs_notice:
        fdct_page["notice"] = fs_notice

    return fdct_page

# -------------------------------------------------------------------------------------
def _nowcast_mosaic_name(fs_radar_id: str) -> str:
    """
    :param fs_radar_id: sigla do radar (ex.: "CGU")
    :returns: nome do mosaico atual do radar, ex.: "CGU_400_now_mosaico.gif"
    """
    return f"{fs_radar_id}_{CI_NOWCAST_RANGE_KM}_now_mosaico.gif"

# -------------------------------------------------------------------------------------
def _is_mosaic_fresh(ff_mtime, ff_now: float) -> bool:
    """
    :param ff_mtime: mtime do mosaico, ou None se ele não existir
    :param ff_now: instante de referência
    :returns: True se o mosaico existe e não passou de CI_NOWCAST_MAX_AGE_HOURS
    """
    if ff_mtime is None:
        return False

    return ff_now - ff_mtime <= CI_NOWCAST_MAX_AGE_HOURS * 3600

# -------------------------------------------------------------------------------------
def _log_hidden_radars_change(fset_hidden: set) -> None:
    """
    registra no log quando o conjunto de radares ocultos muda. Ocultar é
    silencioso na tela, então o log é o rastro de que um radar saiu do ar.

    :param fset_hidden: siglas dos radares ocultos agora
    """
    if fset_hidden == G_HIDDEN_RADARS:
        return

    if fset_hidden:
        M_LOG.warning("Nowcast: radares ocultos (sem mosaico ou mais velho que %dh): %s",
                      CI_NOWCAST_MAX_AGE_HOURS, ", ".join(sorted(fset_hidden)))

    else:
        M_LOG.info("Nowcast: todos os radares com mosaico recente.")

    G_HIDDEN_RADARS.clear()
    G_HIDDEN_RADARS.update(fset_hidden)

# -------------------------------------------------------------------------------------
def get_file_modified(fs_media_dir: str, fs_filename: str):
    """
    data de modificação de um arquivo de mídia, já formatada para exibição.

    :param fs_media_dir: diretório de mídia
    :param fs_filename: nome do arquivo dentro de fs_media_dir

    :returns: str no formato CS_MODIFIED_DATE_FORMAT (ex.: "07/10/2026 14:30"),
              ou None se o arquivo não existir
    """
    return _format_mtime(_get_mtime_or_none(os.path.join(fs_media_dir, fs_filename)))

# -------------------------------------------------------------------------------------
def _format_mtime(ff_mtime):
    """
    :param ff_mtime: mtime de um arquivo, ou None
    :returns: str no formato CS_MODIFIED_DATE_FORMAT, ou None se ff_mtime for None
    """
    if ff_mtime is None:
        return None

    return datetime.datetime.fromtimestamp(ff_mtime).strftime(CS_MODIFIED_DATE_FORMAT)

# -------------------------------------------------------------------------------------
def _collect_product_health(ff_now: float) -> dict:
    """
    estado dos produtos para o /health.

    :param ff_now: instante de referência
    :returns: {"status": "ok" | "degraded",
               "media": {"missing": [...], "stale": [...]},  arquivos de media_dir
               "nowcast_hidden": [...],                       siglas dos radares ocultos
               "nowcast_unavailable": [...],                  "SIGLA/origem" das linhas
                                                              sem mosaico recente
               "config_error": None | "mensagem"}
              "degraded" se alguma lista não estiver vazia ou se o config.json
              não puder ser carregado
    """
    ldct_health = {"status": "ok",
                   "media": {"missing": [], "stale": []},
                   "nowcast_hidden": [],
                   "nowcast_unavailable": [],
                   "config_error": None}

    try:
        load_config()

    except (ValueError, FileNotFoundError, json.JSONDecodeError) as l_error:
        ldct_health["status"] = "degraded"
        ldct_health["config_error"] = str(l_error)
        return ldct_health

    with G_CONFIG_LOCK:
        llst_pages = copy.deepcopy(G_CONFIG["pages"])
        ls_media_dir = G_CONFIG["media_dir"]

    for ldct_page in llst_pages:
        if ldct_page.get("type") == CS_NOWCAST_PAGE_TYPE:
            _, llst_hidden, llst_unavailable = _nowcast_radar_status(ldct_page, ff_now)
            ldct_health["nowcast_hidden"].extend(ls_id for ls_id, _ in llst_hidden)
            ldct_health["nowcast_unavailable"].extend(llst_unavailable)
            continue

        for ldct_tile in ldct_page.get("tiles", []):
            if "file" in ldct_tile:
                _classify_media_file(ls_media_dir, ldct_tile["file"], ff_now, ldct_health["media"])

    if (ldct_health["media"]["missing"] or ldct_health["media"]["stale"]
            or ldct_health["nowcast_hidden"] or ldct_health["nowcast_unavailable"]):
        ldct_health["status"] = "degraded"

    return ldct_health

# -------------------------------------------------------------------------------------
def _classify_media_file(fs_media_dir: str, fs_filename: str, ff_now: float,
                         fdct_media: dict) -> None:
    """
    acrescenta o arquivo à lista "missing" ou "stale" de fdct_media, se for
    o caso (sem repetir: o mesmo arquivo pode estar em mais de um tile).

    :param fs_media_dir: diretório de mídia
    :param fs_filename: arquivo dentro de fs_media_dir
    :param ff_now: instante de referência
    :param fdct_media: {"missing": [...], "stale": [...]} (alterado no lugar)
    """
    lf_mtime = _get_mtime_or_none(os.path.join(fs_media_dir, fs_filename))

    if lf_mtime is None:
        ls_list = "missing"

    elif ff_now - lf_mtime > CI_MEDIA_MAX_AGE_HOURS * 3600:
        ls_list = "stale"

    else:
        return

    if fs_filename not in fdct_media[ls_list]:
        fdct_media[ls_list].append(fs_filename)

# -------------------------------------------------------------------------------------
def get_media_dir() -> str:
    """
    :returns: o diretório de mídia da configuração atual
    """
    with G_CONFIG_LOCK:
        return G_CONFIG["media_dir"]

# -------------------------------------------------------------------------------------
def _get_mtime_or_none(fs_path: str):
    """
    :param fs_path: caminho de um arquivo

    :returns: mtime do arquivo (float), ou None se ele não existir
    """
    try:
        return os.path.getmtime(fs_path)

    except OSError:
        return None

# -------------------------------------------------------------------------------------
def load_config() -> None:
    """
    recarrega G_CONFIG a partir do config.json, mas só se o arquivo mudou
    desde a última leitura.

    fluxo:
      1. se caminho + mtime são iguais aos da última leitura, não faz nada;
      2. lê e valida o arquivo (_read_config_file);
      3. troca o conteúdo de G_CONFIG (com o lock) e guarda a nova chave.
    Se o passo 2 falhar, G_CONFIG continua com a configuração anterior.

    :raises FileNotFoundError: se o config.json não existir
    :raises json.JSONDecodeError: se o arquivo não for JSON válido
    :raises ValueError: se a configuração for inválida (validate_config)
    """
    global G_CONFIG_CACHE_KEY

    lf_mtime = _get_mtime_or_none(CS_CONFIG_FILE)
    lt_cache_key = (CS_CONFIG_FILE, lf_mtime)

    # sem mtime (arquivo sumiu) não há como saber se mudou: lê de novo, e a
    # leitura levanta o erro real (ex.: FileNotFoundError)
    if lf_mtime is not None and lt_cache_key == G_CONFIG_CACHE_KEY:
        return

    ldct_new_config = _read_config_file(CS_CONFIG_FILE)

    with G_CONFIG_LOCK:
        G_CONFIG.clear()
        G_CONFIG.update(ldct_new_config)

    G_CONFIG_CACHE_KEY = lt_cache_key

    M_LOG.info("Config carregado com sucesso.")

# -------------------------------------------------------------------------------------
def _read_config_file(fs_path: str) -> dict:
    """
    lê e valida um config.json, sem mexer no estado global.

    :param fs_path: caminho do config.json
    :returns: a configuração como dict
    :raises FileNotFoundError, json.JSONDecodeError, ValueError: ver load_config
    """
    with open(fs_path, "r", encoding="utf-8") as l_file:
        ldct_config = json.load(l_file)

    validate_config(ldct_config)

    return ldct_config

# -------------------------------------------------------------------------------------
def validate_config(fdct_config: dict) -> None:
    """
    confere se a configuração tem o mínimo para o dashboard funcionar.

    :param fdct_config: conteúdo do config.json já convertido em dict
    :raises ValueError: se faltar chave obrigatória, se "pages" não for uma
                        lista com pelo menos uma página, ou se "media_dir" não
                        for um diretório existente
    """
    llst_missing_keys = [ls_key for ls_key in CT_REQUIRED_KEYS if ls_key not in fdct_config]

    if llst_missing_keys:
        raise ValueError(f"Chaves obrigatórias ausentes no config: {llst_missing_keys}")

    llst_pages = fdct_config["pages"]

    if not isinstance(llst_pages, list) or len(llst_pages) == 0:
        raise ValueError("'pages' deve ser uma lista não vazia.")

    ls_media_dir = fdct_config["media_dir"]

    if not os.path.isdir(ls_media_dir):
        raise ValueError(f"'media_dir' não encontrado ou não é um diretório: {ls_media_dir!r}")

    for ldct_page in llst_pages:
        if ldct_page.get("type") == CS_NOWCAST_PAGE_TYPE:
            _validate_nowcast_entry(ldct_page)

# -------------------------------------------------------------------------------------
def _validate_nowcast_entry(fdct_entry: dict) -> None:
    """
    confere uma entrada de nowcast do config.json.

    :param fdct_entry: a entrada ({"type": "nowcast", ...})
    :raises ValueError: sem "name" ou "duration", ou "radars" não é uma lista
                        não vazia de pares [sigla, nome]
    """
    for ls_key in ("name", "duration"):
        if ls_key not in fdct_entry:
            raise ValueError(f"página de nowcast sem {ls_key!r}.")

    llst_radars = fdct_entry.get("radars")

    if not isinstance(llst_radars, list) or not llst_radars:
        raise ValueError("página de nowcast: 'radars' deve ser uma lista não vazia.")

    for l_radar in llst_radars:
        if not (isinstance(l_radar, list) and len(l_radar) == 2
                and all(isinstance(ls_item, str) for ls_item in l_radar)):
            raise ValueError(f"página de nowcast: radar inválido {l_radar!r} "
                             "(esperado [sigla, nome]).")

# < app >------------------------------------------------------------------------------

app = Flask(__name__)

CORS(app, origins=CLST_CORS_ORIGINS)

# < routes >---------------------------------------------------------------------------

# -------------------------------------------------------------------------------------
@app.route("/api/config")
def api_config():
    """
    :returns: JSON da configuração pública (ver get_config_public)
    """
    load_config()

    return jsonify(get_config_public())

# -------------------------------------------------------------------------------------
@app.route("/health")
def health():
    """
    sonda de vida: responde 200 enquanto o servidor estiver no ar, mesmo com
    produtos com problema (quem monitora olha o "status" do corpo).

    :returns: JSON de _collect_product_health
    """
    return jsonify(_collect_product_health(time.time()))

# -------------------------------------------------------------------------------------
@app.route("/api/state")
def api_state():
    """
    estado que o frontend consulta a cada segundo (barato: um stat).

    :returns: JSON {"alert": bool}
    """
    return jsonify({"alert": os.path.exists(CS_ALERT_TRIGGER)})

# -------------------------------------------------------------------------------------
@app.route("/media/<path:filename>")
def media(filename):
    """
    serve um arquivo de mídia de media_dir.

    :param filename: caminho do arquivo relativo a media_dir
    :returns: o arquivo, ou 404 em JSON se ele não existir
    """
    # ver "como a configuração é carregada" no topo do módulo (gunicorn)
    load_config()

    ls_media_dir = get_media_dir()

    # esta checagem só serve para registrar no log qual arquivo faltou. A
    # proteção contra "../" (path traversal) é do send_from_directory
    ls_file_path = os.path.join(ls_media_dir, filename)

    if not os.path.isfile(ls_file_path):
        M_LOG.warning("Arquivo de mídia não encontrado: %s", ls_file_path)
        abort(404)

    return send_from_directory(ls_media_dir, filename)

# -------------------------------------------------------------------------------------
@app.route("/media/nowcast/<source>/<filename>")
def media_nowcast(source, filename):
    """
    serve um mosaico do 25.oflow ou do 25.u-net (só nomes que casam
    CS_MOSAIC_PATTERN).

    :param source: origem do mosaico ("oflow" ou "unet", CT_NOWCAST_SOURCES)
    :param filename: nome do mosaico, ex.: "CGU_400_now_mosaico.gif"
    :returns: o GIF, ou 404 em JSON
    """
    ls_output_dir = _nowcast_output_dir(source)

    if ls_output_dir is None or not CS_MOSAIC_PATTERN.match(filename):
        abort(404)

    if not os.path.isfile(os.path.join(ls_output_dir, filename)):
        M_LOG.warning("Mosaico não encontrado: %s/%s", source, filename)
        abort(404)

    return send_from_directory(ls_output_dir, filename)

# -------------------------------------------------------------------------------------
@app.route(f"/media/{CS_UNAVAILABLE_MEDIA}")
def media_unavailable():
    """
    serve a imagem de "indisponível" (OFL_NO_CAST_IMAGE), usada pelo
    frontend no lugar de qualquer mídia que não carregue.

    :returns: a imagem, ou 404 em JSON se ela não existir
    """
    if not os.path.isfile(CS_NO_CAST_IMAGE):
        M_LOG.warning("Imagem de indisponível não encontrada: %s", CS_NO_CAST_IMAGE)
        abort(404)

    return send_file(CS_NO_CAST_IMAGE)

# < error handlers >-------------------------------------------------------------------

# -------------------------------------------------------------------------------------
@app.errorhandler(500)
def internal_error(f_error):
    M_LOG.error("Erro interno: %s", f_error)
    return jsonify({"error": "erro interno do servidor"}), 500

# -------------------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "não encontrado"}), 404

# -------------------------------------------------------------------------------------
def main() -> int:
    """
    servidor de desenvolvimento (python app.py). Em produção use o gunicorn,
    que importa "app" direto e não passa por aqui.

    :returns: 1 se a configuração inicial for inválida; senão só retorna
              quando o servidor for encerrado (0)
    """
    try:
        load_config()

    except (ValueError, FileNotFoundError, json.JSONDecodeError) as l_error:
        M_LOG.critical("Falha ao carregar config na inicialização: %s", l_error)
        return 1

    lb_debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    M_LOG.info("Iniciando servidor em %s:%s (debug=%s)", CS_HOST, CI_PORT, lb_debug)

    app.run(host=CS_HOST, port=CI_PORT, debug=lb_debug)

    return 0

# -------------------------------------------------------------------------------------
# this is the bootstrap process

if "__main__" == __name__:

    raise SystemExit(main())

# < the end >--------------------------------------------------------------------------
