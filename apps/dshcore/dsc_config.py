# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsc_config
leitura, validação e cache do config.json, a fonte única das páginas dos
dois dashboards (web e desktop).

formato:
  {
    "refresh_seconds": 10,                         (só o web usa)
    "roots": {                                     diretórios das mídias
      "blitz": "${BLITZ_DATA:-$STSC_DATA/bltz/data}/output", ...
    },
    "pages": [
      {"name", "duration", "tiles": [{"type", "root", "file", "title"?}]},
      {"type": "nowcast", "name", "duration", "radars": [[sigla, nome], ...]}
    ]
  }

raízes ("roots"): cada valor é um caminho com variáveis de ambiente no
estilo do shell: $VAR, ${VAR} e ${VAR:-padrão} (o padrão pode ter outras
variáveis e começar com ~). Variável ausente no ambiente usa
dsc_env.DCT_VAR_DEFAULTS (ex.: STSC_DATA); sem isso e sem ":-", a config é
inválida. Caminho relativo vale a partir do diretório do config.json. As
raízes podem ainda não existir (o pipeline não rodou): o /health do web
acusa os arquivos ausentes.

fluxo (CConfigCache.load):
  1. caminho + mtime iguais aos da última leitura: devolve a config guardada;
  2. senão lê, valida e expande as raízes (read_config);
  3. guarda a nova config. Se o passo 2 falhar, a anterior continua guardada
     (last_good) e o erro sobe para quem chamou.

2026.nov  mlabru  initial version: substitui o media_dir do web e o
                  CLST_PAGES do desktop por um config.json comum com raízes
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import json
import math
import os
import re
import threading

# locals
from dshcore import dsc_env

# < constants >────────────────────────────────────────────────────────────────────────

# chaves que o config.json precisa ter
CT_REQUIRED_KEYS = ("roots", "pages")

# valor de "type" da entrada que vira páginas de nowcast (dsc_nowcast)
CS_NOWCAST_PAGE_TYPE = "nowcast"

# tipos de tile aceitos (o desktop escolhe pelo nome do arquivo; o web, por este)
CT_TILE_TYPES = ("image", "gif", "video")

# nomes de raiz: viram o primeiro trecho da URL /media/<raiz>/<arquivo> no web
CS_ROOT_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")

# trechos de /media/ que o web já usa para outras coisas
CT_RESERVED_ROOT_NAMES = ("nowcast", "_unavailable")

# nome de variável de ambiente
CS_VAR_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# erros de leitura/validação do config.json
CT_CONFIG_ERRORS = (OSError, ValueError)

# < expansão das raízes >──────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────────────
def expand_path(fs_template: str, fs_base_dir: str) -> str:
    """
    expande as variáveis de uma raiz e a torna absoluta.

    :param fs_template: ex.: "${BLITZ_DATA:-$STSC_DATA/bltz/data}/output"
    :param fs_base_dir: diretório base de um resultado relativo (o do config.json)
    :returns: caminho absoluto normalizado
    :raises ValueError: variável sem valor e sem padrão, ou "${" sem "}"
    """
    ls_path = os.path.expanduser(_expand_vars(fs_template))

    return os.path.normpath(os.path.join(fs_base_dir, ls_path))

# ─────────────────────────────────────────────────────────────────────────────────────
def _expand_vars(fs_text: str) -> str:
    """
    :param fs_text: texto com $VAR, ${VAR} ou ${VAR:-padrão}
    :returns: o texto com as variáveis trocadas pelos valores
    :raises ValueError: ver expand_path
    """
    llst_parts = []
    li_pos = 0

    while li_pos < len(fs_text):
        if fs_text.startswith("${", li_pos):
            li_end = _matching_brace(fs_text, li_pos + 1)
            ls_name, ls_sep, ls_default = fs_text[li_pos + 2:li_end].partition(":-")
            llst_parts.append(_var_value(ls_name, ls_default if ls_sep else None))
            li_pos = li_end + 1
            continue

        l_match = CS_VAR_NAME_PATTERN.match(fs_text, li_pos + 1) if fs_text[li_pos] == "$" else None

        if l_match:
            llst_parts.append(_var_value(l_match.group(), None))
            li_pos = l_match.end()
            continue

        llst_parts.append(fs_text[li_pos])
        li_pos += 1

    return "".join(llst_parts)

# ─────────────────────────────────────────────────────────────────────────────────────
def _matching_brace(fs_text: str, fi_open: int) -> int:
    """
    :param fs_text: texto
    :param fi_open: posição de um "{"
    :returns: posição do "}" que o fecha (contando os "{" aninhados)
    :raises ValueError: se não houver
    """
    li_depth = 0

    for li_pos in range(fi_open, len(fs_text)):
        if fs_text[li_pos] == "{":
            li_depth += 1

        elif fs_text[li_pos] == "}":
            li_depth -= 1

            if li_depth == 0:
                return li_pos

    raise ValueError(f"'${{' sem '}}' em {fs_text!r}.")

# ─────────────────────────────────────────────────────────────────────────────────────
def _var_value(fs_name: str, fs_default) -> str:
    """
    valor de uma variável: o ambiente; se vazia, o padrão do ":-" (expandido,
    com ~); senão dsc_env.DCT_VAR_DEFAULTS.

    :param fs_name: nome da variável
    :param fs_default: texto depois de ":-", ou None se não houver
    :returns: o valor
    :raises ValueError: nome inválido, ou variável sem valor nenhum
    """
    if not CS_VAR_NAME_PATTERN.fullmatch(fs_name):
        raise ValueError(f"nome de variável inválido: {fs_name!r}.")

    ls_value = os.environ.get(fs_name)

    if ls_value:
        return ls_value

    if fs_default is not None:
        return os.path.expanduser(_expand_vars(fs_default))

    if fs_name in dsc_env.DCT_VAR_DEFAULTS:
        return dsc_env.DCT_VAR_DEFAULTS[fs_name]

    raise ValueError(f"variável {fs_name!r} sem valor (defina-a ou use ${{{fs_name}:-padrão}}).")

# < leitura e validação >──────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────────────
def read_config(fs_path: str) -> dict:
    """
    lê o config.json, valida e expande as raízes (sem estado global).

    :param fs_path: caminho do config.json
    :returns: a configuração, com "roots" já em caminhos absolutos
    :raises OSError: arquivo não pode ser lido
    :raises ValueError: JSON inválido (json.JSONDecodeError é ValueError) ou
                        configuração inválida (validate_config, expand_path)
    """
    with open(fs_path, "r", encoding="utf-8") as l_file:
        ldct_config = json.load(l_file)

    validate_config(ldct_config)

    ls_config_dir = os.path.dirname(os.path.abspath(fs_path))

    ldct_config["roots"] = {ls_name: expand_path(ls_template, ls_config_dir)
                            for ls_name, ls_template in ldct_config["roots"].items()}

    return ldct_config

# ─────────────────────────────────────────────────────────────────────────────────────
def validate_config(fdct_config) -> None:
    """
    confere se a configuração tem o mínimo para os dashboards funcionarem.

    :param fdct_config: conteúdo do config.json já convertido
    :raises ValueError: com a primeira inconsistência encontrada
    """
    if not isinstance(fdct_config, dict):
        raise ValueError("o config.json deve ser um objeto.")

    llst_missing_keys = [ls_key for ls_key in CT_REQUIRED_KEYS if ls_key not in fdct_config]

    if llst_missing_keys:
        raise ValueError(f"Chaves obrigatórias ausentes no config: {llst_missing_keys}")

    _validate_roots(fdct_config["roots"])

    llst_pages = fdct_config["pages"]

    if not isinstance(llst_pages, list) or len(llst_pages) == 0:
        raise ValueError("'pages' deve ser uma lista não vazia.")

    for ldct_page in llst_pages:
        if not isinstance(ldct_page, dict):
            raise ValueError(f"página inválida {ldct_page!r} (esperado um objeto).")

        if ldct_page.get("type") == CS_NOWCAST_PAGE_TYPE:
            _validate_nowcast_entry(ldct_page)

        else:
            _validate_regular_page(ldct_page, fdct_config["roots"])

        _validate_duration(ldct_page)

# ─────────────────────────────────────────────────────────────────────────────────────
def _validate_roots(fdct_roots) -> None:
    """
    :param fdct_roots: {"nome": "caminho com variáveis"}
    :raises ValueError: não é objeto, nome inválido/reservado ou valor não é texto
    """
    if not isinstance(fdct_roots, dict):
        raise ValueError("'roots' deve ser um objeto {nome: caminho}.")

    for ls_name, ls_template in fdct_roots.items():
        if not CS_ROOT_NAME_PATTERN.match(ls_name) or ls_name in CT_RESERVED_ROOT_NAMES:
            raise ValueError(f"nome de raiz inválido ou reservado: {ls_name!r}.")

        if not isinstance(ls_template, str) or not ls_template:
            raise ValueError(f"raiz {ls_name!r}: o caminho deve ser um texto não vazio.")

# ─────────────────────────────────────────────────────────────────────────────────────
def _validate_duration(fdct_page: dict) -> None:
    """
    sem "duration" positiva o web agenda a próxima página para 0 ms e o
    desktop dividiria por zero.

    :param fdct_page: uma página do config.json
    :raises ValueError: "duration" ausente, não numérica ou <= 0
    """
    lf_duration = fdct_page.get("duration")

    # bool é subclasse de int: "duration": true não pode passar
    if (isinstance(lf_duration, bool) or not isinstance(lf_duration, (int, float))
            or not math.isfinite(lf_duration) or lf_duration <= 0):
        raise ValueError(f"página {fdct_page.get('name')!r}: 'duration' deve ser um "
                         f"número positivo (veio {lf_duration!r}).")

# ─────────────────────────────────────────────────────────────────────────────────────
def _validate_regular_page(fdct_page: dict, fdct_roots: dict) -> None:
    """
    :param fdct_page: página comum (não nowcast)
    :param fdct_roots: raízes do config.json
    :raises ValueError: sem "name", "tiles" não é lista de tiles válidos
    """
    if not isinstance(fdct_page.get("name"), str):
        raise ValueError(f"página sem 'name' (texto): {fdct_page!r}.")

    llst_tiles = fdct_page.get("tiles")

    if not isinstance(llst_tiles, list) or not all(isinstance(l_tile, dict)
                                                   for l_tile in llst_tiles):
        raise ValueError(f"página {fdct_page['name']!r}: 'tiles' deve ser uma lista "
                         "de objetos.")

    for ldct_tile in llst_tiles:
        _validate_tile(ldct_tile, fdct_page["name"], fdct_roots)

# ─────────────────────────────────────────────────────────────────────────────────────
def _validate_tile(fdct_tile: dict, fs_page_name: str, fdct_roots: dict) -> None:
    """
    :param fdct_tile: {"type", "root", "file", "title"?}
    :param fs_page_name: nome da página (para a mensagem)
    :param fdct_roots: raízes do config.json
    :raises ValueError: tipo desconhecido, raiz inexistente ou arquivo que sai da raiz
    """
    ls_where = f"página {fs_page_name!r}, tile {fdct_tile.get('file')!r}"

    if fdct_tile.get("type") not in CT_TILE_TYPES:
        raise ValueError(f"{ls_where}: 'type' deve ser um de {list(CT_TILE_TYPES)}.")

    if fdct_tile.get("root") not in fdct_roots:
        raise ValueError(f"{ls_where}: 'root' {fdct_tile.get('root')!r} não está em 'roots'.")

    ls_file = fdct_tile.get("file")

    # o arquivo fica dentro da raiz: nada de absoluto nem de ".."
    if (not isinstance(ls_file, str) or not ls_file or os.path.isabs(ls_file)
            or ".." in ls_file.replace("\\", "/").split("/")):
        raise ValueError(f"{ls_where}: 'file' deve ser um caminho relativo dentro da raiz.")

    if "title" in fdct_tile and not isinstance(fdct_tile["title"], str):
        raise ValueError(f"{ls_where}: 'title' deve ser texto.")

# ─────────────────────────────────────────────────────────────────────────────────────
def _validate_nowcast_entry(fdct_entry: dict) -> None:
    """
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

# ─────────────────────────────────────────────────────────────────────────────────────
def tile_path(fdct_config: dict, fdct_tile: dict) -> str:
    """
    :param fdct_config: configuração lida por read_config (raízes absolutas)
    :param fdct_tile: tile de uma página comum
    :returns: caminho absoluto do arquivo do tile
    """
    return os.path.join(fdct_config["roots"][fdct_tile["root"]], fdct_tile["file"])

# < cache >────────────────────────────────────────────────────────────────────────────

class CConfigCache:
    """
    o config.json mais recente, relido só quando o arquivo muda (caminho +
    mtime). Seguro para várias threads (o backend web é multithread).

    a config devolvida é compartilhada: quem for alterá-la faz uma cópia.
    """
    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self):
        self._lock = threading.Lock()

        # (caminho, mtime) da última leitura bem-sucedida; None = nunca carregou
        self._cache_key = None

        # última configuração válida (None = nunca carregou)
        self.last_good = None

    # ─────────────────────────────────────────────────────────────────────────────────
    def load(self, fs_path: str) -> dict:
        """
        :param fs_path: caminho do config.json
        :returns: a configuração atual
        :raises OSError, ValueError: o arquivo mudou (ou nunca foi lido) e não
                                     pôde ser lido/validado; last_good continua
                                     com a configuração anterior
        """
        try:
            lf_mtime = os.path.getmtime(fs_path)

        except OSError:
            # sumiu: a leitura abaixo levanta o erro real
            lf_mtime = None

        lt_cache_key = (fs_path, lf_mtime)

        with self._lock:
            if lf_mtime is not None and lt_cache_key == self._cache_key:
                return self.last_good

            ldct_config = read_config(fs_path)

            self.last_good = ldct_config
            self._cache_key = lt_cache_key

        return ldct_config

# < the end >──────────────────────────────────────────────────────────────────────────
