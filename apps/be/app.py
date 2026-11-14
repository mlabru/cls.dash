# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

app
backend do dashboard web: API JSON em Flask que serve a configuração das
páginas e os arquivos de mídia para o frontend (apps/fe).

O config.json, a validação dele e a regra de nowcast são comuns com o
dashboard desktop e ficam em apps/dshcore (dsc_config, dsc_nowcast). Aqui só
se formata o resultado para o frontend (JSON com URLs de /media).

rotas:
  GET /api/config              configuração das páginas (sem "roots", que
                               são caminhos internos), com data e versão
                               (mtime) de cada arquivo e as páginas de
                               nowcast já expandidas; o "file" de cada tile
                               vira "<raiz>/<arquivo>" (a URL em /media)
  GET /api/state               {"alert": bool}: o arquivo de alerta
                               prioritário (dsc_env.CS_ALERT_TRIGGER) existe?
  GET /media/<raiz>/<arquivo>  o arquivo, lido do diretório da raiz
  GET /media/nowcast/<origem>/<gif>
                               um mosaico do 25.oflow ("oflow") ou do 25.u-net
                               ("unet"); só nomes de mosaico
  GET /media/_unavailable      a imagem de "indisponível" (OFL_NO_CAST_IMAGE)
  GET /health                  sempre HTTP 200 (sonda de vida); o corpo diz
                               se há produtos ausentes/velhos ("status":
                               "ok" ou "degraded", ver _collect_product_health)

como a configuração é carregada (load_config):
  dsc_config.CConfigCache relê o config.json só quando ele muda (caminho +
  mtime). Toda rota que precisa da configuração chama load_config() antes,
  porque no gunicorn cada worker é um processo com o próprio cache.

uso:
    python app.py                               # desenvolvimento (lê o .env)
    gunicorn -w 4 -b 0.0.0.0:8000 app:app       # produção (dash_web.sh)

variáveis de ambiente (ou .env): HOST, PORT, CORS_ORIGINS, FLASK_DEBUG,
MEDIA_MAX_AGE_HOURS, e as comuns com o desktop (dsc_env): CONFIG_FILE,
STSC_DATA, OFLOW_DATA, UNET_DATA, NOWCAST_MAX_AGE_HOURS, OFL_NO_CAST_IMAGE,
além das usadas nas raízes do config.json (BLITZ_DATA, GOES_DATA, RSM_PATH).

2026.nov  mlabru  log dos radares de nowcast ocultos uma vez só entre os
                  workers do gunicorn (arquivo de estado em data/run,
                  ver _share_hidden_radars_state)
2026.nov  mlabru  config e regra de nowcast unificadas com o desktop
                  (apps/dshcore): "media_dir" substituído por "roots" (raízes
                  por variável de ambiente), rota /media/<raiz>/<arquivo>
2026.nov  mlabru  caminhos relativos não dependem mais do diretório atual:
                  CONFIG_FILE é relativo a apps/be, "media_dir" ao
                  diretório do config.json; .env lido de apps/be
2026.nov  mlabru  validate_config valida toda página: "duration" número > 0
                  (sem ela o frontend trocava de página a cada 0 ms) e, nas
                  páginas comuns, "tiles" lista de objetos
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
                  não tinha atendido /api/config, a config estava vazia e
                  /media respondia 500)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import copy
import datetime
import logging
import os
import sys
import time

# flask
from flask import Flask, abort, jsonify, send_file, send_from_directory
from flask_cors import CORS

# dotenv
from dotenv import load_dotenv

# < environment >----------------------------------------------------------------------

# diretório deste módulo (apps/be)
CS_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# o .env precisa estar em os.environ ANTES de importar o dshcore, que lê as
# variáveis na importação; o ambiente tem precedência
load_dotenv(os.path.join(CS_APP_DIR, ".env"))

# apps/ no sys.path: o dshcore fica em apps/, e o gunicorn/python rodam a
# partir de apps/be
sys.path.insert(0, os.path.dirname(CS_APP_DIR))

# locals
from dshcore import dsc_config as dc   # noqa: E402
from dshcore import dsc_env as de      # noqa: E402
from dshcore import dsc_nowcast as dn  # noqa: E402

CS_HOST = os.environ.get("HOST", "0.0.0.0")
CI_PORT = int(os.environ.get("PORT", "8000"))
CLST_CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost").split(",")

# produto de uma página comum mais velho que isso aparece como "stale" no /health
CI_MEDIA_MAX_AGE_HOURS = int(os.environ.get("MEDIA_MAX_AGE_HOURS", "2"))

# < constants >------------------------------------------------------------------------

# formato da data de modificação enviada ao frontend
CS_MODIFIED_DATE_FORMAT = "%d/%m/%Y %H:%M"

# prefixo (em /media) dos mosaicos e nome do arquivo de "indisponível"
CS_NOWCAST_MEDIA_PREFIX = "nowcast/"
CS_UNAVAILABLE_MEDIA = "_unavailable"

# estado dos radares de nowcast ocultos, comum aos workers (ver
# _share_hidden_radars_state); data/run é o diretório de PIDs do dsh_common.sh
CS_HIDDEN_STATE_FILE = os.path.join(os.path.dirname(de.CS_APPS_DIR), "data", "run",
                                    "nowcast_hidden.state")

# < logging >--------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

M_LOG = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------
def _share_hidden_radars_state() -> None:
    """
    no gunicorn cada worker é um processo e logava a mesma mudança dos
    radares ocultos; com o arquivo de estado comum só um loga. O token é o
    PID do pai (o mestre do gunicorn, o mesmo para todos os workers): depois
    de reiniciar, o estado atual é logado de novo (o dash_web.sh recomeça o
    log).
    """
    try:
        os.makedirs(os.path.dirname(CS_HIDDEN_STATE_FILE), exist_ok=True)

    except OSError as l_error:
        M_LOG.warning("nowcast: sem diretório para o estado dos radares ocultos (%s): %s",
                      CS_HIDDEN_STATE_FILE, l_error)
        return

    dn.set_hidden_state_file(CS_HIDDEN_STATE_FILE, str(os.getppid()))


_share_hidden_radars_state()

# < global state >---------------------------------------------------------------------

# cache do config.json (ver load_config)
G_CONFIG_CACHE = dc.CConfigCache()

# -------------------------------------------------------------------------------------
def load_config() -> dict:
    """
    :returns: a configuração atual (compartilhada: não altere, copie)
    :raises OSError, ValueError: config.json ausente ou inválido (ver
                                 dsc_config.CConfigCache.load)
    """
    return G_CONFIG_CACHE.load(de.CS_CONFIG_FILE)

# -------------------------------------------------------------------------------------
def get_config_public(fdct_config: dict) -> dict:
    """
    a configuração que o frontend recebe: sem "roots" (caminhos internos do
    servidor), com as páginas de nowcast expandidas e, em cada tile, "file"
    = "<raiz>/<arquivo>" (a URL em /media), "file_modified" e "file_version".

    :param fdct_config: configuração de load_config
    :returns: cópia independente (pode ser alterada à vontade)
    """
    ldct_public_config = copy.deepcopy(fdct_config)

    del ldct_public_config["roots"]

    ldct_public_config["pages"] = _expand_pages(fdct_config, time.time())

    return ldct_public_config

# -------------------------------------------------------------------------------------
def _expand_pages(fdct_config: dict, ff_now: float) -> list:
    """
    as páginas para o frontend: cada entrada de nowcast vira as páginas que
    ela gera (dsc_nowcast); as comuns têm os tiles formatados. Mesma ordem.

    :param fdct_config: configuração de load_config (não é alterada)
    :param ff_now: instante de referência (time.time()) para a idade dos mosaicos
    :returns: nova lista de páginas
    """
    llst_pages = []

    for ldct_page in fdct_config["pages"]:
        if ldct_page.get("type") == dc.CS_NOWCAST_PAGE_TYPE:
            llst_pages.extend(_without_empty_notice(ldct_nowcast_page)
                              for ldct_nowcast_page
                              in dn.build_pages(ldct_page, ff_now, _nowcast_tile))
            continue

        ldct_public_page = copy.deepcopy(ldct_page)
        ldct_public_page["tiles"] = [_regular_tile(fdct_config, ldct_tile)
                                     for ldct_tile in ldct_page["tiles"]]
        llst_pages.append(ldct_public_page)

    return llst_pages

# -------------------------------------------------------------------------------------
def _regular_tile(fdct_config: dict, fdct_tile: dict) -> dict:
    """
    :param fdct_config: configuração (raízes)
    :param fdct_tile: {"type", "root", "file", "title"?}
    :returns: tile para o frontend: {"type", "file": "<raiz>/<arquivo>",
              "title"?, "file_modified", "file_version"?}
    """
    ldct_tile = {ls_key: l_value for ls_key, l_value in fdct_tile.items() if ls_key != "root"}
    ldct_tile["file"] = f"{fdct_tile['root']}/{fdct_tile['file']}"

    _set_file_info(ldct_tile, _get_mtime_or_none(dc.tile_path(fdct_config, fdct_tile)))

    return ldct_tile

# -------------------------------------------------------------------------------------
def _nowcast_tile(fdct_row: dict) -> dict:
    """
    formata uma linha de dsc_nowcast para o frontend.

    :param fdct_row: linha de dsc_nowcast.radar_rows
    :returns: o GIF do mosaico (/media/nowcast/<origem>/<gif>), ou a imagem
              de "indisponível"
    """
    if not fdct_row["available"]:
        return {"type": "image", "file": CS_UNAVAILABLE_MEDIA,
                "title": fdct_row["title"], "file_modified": None}

    ldct_tile = {"type": "gif",
                 "file": f"{CS_NOWCAST_MEDIA_PREFIX}{fdct_row['source']}/{fdct_row['file_name']}",
                 "title": fdct_row["title"]}

    _set_file_info(ldct_tile, fdct_row["mtime"])

    return ldct_tile

# -------------------------------------------------------------------------------------
def _without_empty_notice(fdct_page: dict) -> dict:
    """
    :param fdct_page: página gerada por dsc_nowcast ("notice" "" = sem ocultos)
    :returns: a própria página, sem a chave "notice" se ela for vazia
    """
    if not fdct_page.get("notice"):
        fdct_page.pop("notice", None)

    return fdct_page

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
def _get_mtime_or_none(fs_path: str):
    """
    :param fs_path: caminho de um arquivo
    :returns: mtime do arquivo (float), ou None se ele não existir
    """
    try:
        return os.path.getmtime(fs_path)

    except OSError:
        return None

# < health >---------------------------------------------------------------------------

# -------------------------------------------------------------------------------------
def _collect_product_health(ff_now: float) -> dict:
    """
    estado dos produtos para o /health.

    :param ff_now: instante de referência
    :returns: {"status": "ok" | "degraded",
               "media": {"missing": [...], "stale": [...]},  "<raiz>/<arquivo>"
                                                              das páginas comuns
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
        ldct_config = load_config()

    except dc.CT_CONFIG_ERRORS as l_error:
        ldct_health["status"] = "degraded"
        ldct_health["config_error"] = str(l_error)
        return ldct_health

    for ldct_page in ldct_config["pages"]:
        if ldct_page.get("type") == dc.CS_NOWCAST_PAGE_TYPE:
            _, llst_hidden, llst_unavailable = dn.radar_rows(ldct_page, ff_now)
            ldct_health["nowcast_hidden"].extend(ls_id for ls_id, _ in llst_hidden)
            ldct_health["nowcast_unavailable"].extend(llst_unavailable)
            continue

        for ldct_tile in ldct_page["tiles"]:
            _classify_media_file(ldct_config, ldct_tile, ff_now, ldct_health["media"])

    if (ldct_health["media"]["missing"] or ldct_health["media"]["stale"]
            or ldct_health["nowcast_hidden"] or ldct_health["nowcast_unavailable"]):
        ldct_health["status"] = "degraded"

    return ldct_health

# -------------------------------------------------------------------------------------
def _classify_media_file(fdct_config: dict, fdct_tile: dict, ff_now: float,
                         fdct_media: dict) -> None:
    """
    acrescenta o arquivo do tile à lista "missing" ou "stale" de fdct_media,
    se for o caso (sem repetir: o mesmo arquivo pode estar em mais de um tile).

    :param fdct_config: configuração (raízes)
    :param fdct_tile: tile de uma página comum
    :param ff_now: instante de referência
    :param fdct_media: {"missing": [...], "stale": [...]} (alterado no lugar)
    """
    lf_mtime = _get_mtime_or_none(dc.tile_path(fdct_config, fdct_tile))

    if lf_mtime is None:
        ls_list = "missing"

    elif ff_now - lf_mtime > CI_MEDIA_MAX_AGE_HOURS * 3600:
        ls_list = "stale"

    else:
        return

    ls_name = f"{fdct_tile['root']}/{fdct_tile['file']}"

    if ls_name not in fdct_media[ls_list]:
        fdct_media[ls_list].append(ls_name)

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
    return jsonify(get_config_public(load_config()))

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
    return jsonify({"alert": os.path.exists(de.CS_ALERT_TRIGGER)})

# -------------------------------------------------------------------------------------
@app.route("/media/<root>/<path:filename>")
def media(root, filename):
    """
    serve um arquivo de uma raiz do config.json.

    :param root: nome da raiz ("roots" do config.json)
    :param filename: caminho do arquivo relativo à raiz
    :returns: o arquivo, ou 404 em JSON se a raiz ou o arquivo não existirem
    """
    # ver "como a configuração é carregada" no topo do módulo (gunicorn)
    ls_root_dir = load_config()["roots"].get(root)

    if ls_root_dir is None:
        abort(404)

    # esta checagem só serve para registrar no log qual arquivo faltou. A
    # proteção contra "../" (path traversal) é do send_from_directory
    if not os.path.isfile(os.path.join(ls_root_dir, filename)):
        M_LOG.warning("Arquivo de mídia não encontrado: %s/%s", root, filename)
        abort(404)

    return send_from_directory(ls_root_dir, filename)

# -------------------------------------------------------------------------------------
@app.route("/media/nowcast/<source>/<filename>")
def media_nowcast(source, filename):
    """
    serve um mosaico do 25.oflow ou do 25.u-net (só nomes que casam
    dsc_nowcast.CS_MOSAIC_PATTERN).

    :param source: origem do mosaico ("oflow" ou "unet")
    :param filename: nome do mosaico, ex.: "CGU_400_now_mosaico.gif"
    :returns: o GIF, ou 404 em JSON
    """
    ls_output_dir = dn.source_output_dir(source)

    if ls_output_dir is None or not dn.CS_MOSAIC_PATTERN.match(filename):
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
    if not os.path.isfile(de.CS_NO_CAST_IMAGE):
        M_LOG.warning("Imagem de indisponível não encontrada: %s", de.CS_NO_CAST_IMAGE)
        abort(404)

    return send_file(de.CS_NO_CAST_IMAGE)

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

    except dc.CT_CONFIG_ERRORS as l_error:
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
