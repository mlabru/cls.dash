# -*- coding: utf-8 -*-
"""testes unitários para apps/dshcore/dsc_config.py (config comum aos dois dashboards)"""

import json
import os

import pytest

from dshcore import dsc_config as dc
from dshcore import dsc_env as de


def _config(pages=None, roots=None):
    return {"roots": {"m": "/x"} if roots is None else roots,
            "pages": pages if pages is not None else [_page()]}


def _page(**tile):
    return {"name": "p", "duration": 1,
            "tiles": [{"type": "image", "root": "m", "file": "a.png", **tile}]}


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

def test_valid_config_passes():
    dc.validate_config(_config())


@pytest.mark.parametrize("config, match", [
    ({"pages": []}, "Chaves obrigatórias ausentes"),
    (_config(pages=[]), "'pages' deve ser uma lista"),
    (_config(pages="nope"), "'pages' deve ser uma lista"),
    (_config(pages=["x"]), "página inválida"),
    (_config(roots="x"), "'roots' deve ser um objeto"),
    (_config(roots={"Bad Name": "/x"}), "nome de raiz"),
    (_config(roots={"nowcast": "/x"}), "reservado"),
    (_config(roots={"m": ""}), "texto não vazio"),
])
def test_invalid_structure_is_rejected(config, match):
    with pytest.raises(ValueError, match=match):
        dc.validate_config(config)


@pytest.mark.parametrize("duration", [None, 0, -5, "15", True, float("nan")])
def test_bad_duration_is_rejected(duration):
    page = _page()
    page.pop("duration")
    if duration is not None:
        page["duration"] = duration

    with pytest.raises(ValueError, match="'duration'"):
        dc.validate_config(_config(pages=[page]))


@pytest.mark.parametrize("tiles", [None, "a.png", [["t", "a.png"]]])
def test_bad_tiles_are_rejected(tiles):
    page = {"name": "p", "duration": 1}
    if tiles is not None:
        page["tiles"] = tiles

    with pytest.raises(ValueError, match="'tiles'"):
        dc.validate_config(_config(pages=[page]))


@pytest.mark.parametrize("tile, match", [
    ({"type": "pdf"}, "'type'"),
    ({"root": "other"}, "'root'"),
    ({"file": "/etc/passwd"}, "'file'"),
    ({"file": "../x.png"}, "'file'"),
    ({"file": "a/../../x.png"}, "'file'"),
    ({"title": 3}, "'title'"),
])
def test_bad_tile_is_rejected(tile, match):
    with pytest.raises(ValueError, match=match):
        dc.validate_config(_config(pages=[_page(**tile)]))


def test_regular_page_without_name_is_rejected():
    page = _page()
    del page["name"]

    with pytest.raises(ValueError, match="'name'"):
        dc.validate_config(_config(pages=[page]))


@pytest.mark.parametrize("entry", [
    {"type": "nowcast", "name": "n", "duration": 1, "radars": []},
    {"type": "nowcast", "name": "n", "duration": 1, "radars": [["BEL"]]},
    {"type": "nowcast", "name": "n", "radars": [["BEL", "Belém"]]},
])
def test_invalid_nowcast_entry_is_rejected(entry):
    with pytest.raises(ValueError, match="nowcast"):
        dc.validate_config(_config(pages=[entry]))


# ---------------------------------------------------------------------------
# expand_path
# ---------------------------------------------------------------------------

def test_expand_path_uses_environment(monkeypatch):
    monkeypatch.setenv("BLITZ_DATA", "/data/bltz")

    assert dc.expand_path("${BLITZ_DATA:-/nope}/output", "/base") == "/data/bltz/output"
    assert dc.expand_path("$BLITZ_DATA/output", "/base") == "/data/bltz/output"


def test_expand_path_default_with_nested_variable_and_tilde(monkeypatch):
    monkeypatch.delenv("BLITZ_DATA", raising=False)
    monkeypatch.delenv("RSM_PATH", raising=False)
    monkeypatch.setenv("STSC_DATA", "/stsc")

    assert dc.expand_path("${BLITZ_DATA:-${STSC_DATA}/bltz/data}/output", "/b") == \
        "/stsc/bltz/data/output"
    assert dc.expand_path("${RSM_PATH:-~/Public/mrad}/data", "/b") == \
        os.path.expanduser("~/Public/mrad/data")


def test_expand_path_falls_back_to_code_defaults(monkeypatch):
    monkeypatch.delenv("STSC_DATA", raising=False)
    monkeypatch.setitem(de.DCT_VAR_DEFAULTS, "STSC_DATA", "/padrao")

    assert dc.expand_path("$STSC_DATA/goes", "/b") == "/padrao/goes"


def test_expand_path_empty_variable_uses_default(monkeypatch):
    monkeypatch.setenv("GOES_DATA", "")

    assert dc.expand_path("${GOES_DATA:-/g}", "/b") == "/g"


def test_expand_path_relative_result_is_relative_to_base():
    assert dc.expand_path("media/x", "/conf") == "/conf/media/x"


@pytest.mark.parametrize("template, match", [
    ("${NO_SUCH_VAR_XYZ}/x", "sem valor"),
    ("$NO_SUCH_VAR_XYZ", "sem valor"),
    ("${UNCLOSED", "sem '}'"),
    ("${1BAD}", "inválido"),
])
def test_expand_path_errors(monkeypatch, template, match):
    monkeypatch.delenv("NO_SUCH_VAR_XYZ", raising=False)

    with pytest.raises(ValueError, match=match):
        dc.expand_path(template, "/b")


# ---------------------------------------------------------------------------
# read_config / tile_path / CConfigCache
# ---------------------------------------------------------------------------

def _write(path, config):
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_read_config_resolves_roots_relative_to_config_dir(tmp_path, monkeypatch):
    monkeypatch.chdir("/")
    path = _write(tmp_path / "config.json", _config(roots={"m": "./media"}))

    config = dc.read_config(str(path))

    assert config["roots"] == {"m": str(tmp_path / "media")}
    assert dc.tile_path(config, config["pages"][0]["tiles"][0]) == str(tmp_path / "media" / "a.png")


def test_read_config_rejects_bad_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ nope", encoding="utf-8")

    with pytest.raises(ValueError):
        dc.read_config(str(path))


def test_cache_rereads_only_when_file_changes(tmp_path, monkeypatch):
    path = _write(tmp_path / "config.json", _config())
    cache = dc.CConfigCache()

    calls = []
    original = dc.read_config
    monkeypatch.setattr(dc, "read_config", lambda p: calls.append(p) or original(p))

    first = cache.load(str(path))
    assert cache.load(str(path)) is first
    assert len(calls) == 1

    _write(path, _config(pages=[{**_page(), "name": "novo"}]))
    future = os.path.getmtime(path) + 5
    os.utime(path, (future, future))

    assert cache.load(str(path))["pages"][0]["name"] == "novo"
    assert len(calls) == 2


def test_cache_keeps_last_good_when_file_breaks(tmp_path):
    path = _write(tmp_path / "config.json", _config())
    cache = dc.CConfigCache()
    good = cache.load(str(path))

    path.write_text("{ broken", encoding="utf-8")
    future = os.path.getmtime(path) + 5
    os.utime(path, (future, future))

    with pytest.raises(ValueError):
        cache.load(str(path))

    assert cache.last_good is good


def test_real_config_json_is_valid():
    config = dc.read_config(de.CS_CONFIG_FILE)

    entries = [p for p in config["pages"] if p.get("type") == dc.CS_NOWCAST_PAGE_TYPE]
    assert len(entries) == 1
    assert len(entries[0]["radars"]) == 7
