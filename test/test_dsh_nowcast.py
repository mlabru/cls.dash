# -*- coding: utf-8 -*-
"""testes unitários para apps/dash/dsh_nowcast.py

a regra de nowcast é do dshcore (test/test_dsc_nowcast.py); aqui fica o que é
do desktop: o formato (título, caminho), "source_index", o fallback para a
última config válida e os nomes dos botões do pad.
"""

import json
import os
import time

import pytest

import dash.dsh_config as gc
import dash.dsh_nowcast as nc
from dshcore import dsc_config as dc
from dshcore import dsc_env as de


@pytest.fixture
def mosaics(tmp_path, monkeypatch):
    for source in ("oflw", "unet"):
        out = tmp_path / source / "output"
        out.mkdir(parents=True)
        (out / "BEL_400_now_mosaico.gif").write_bytes(b"GIF89a")

    monkeypatch.setattr(de, "CS_OFLOW_DATA", str(tmp_path / "oflw"))
    monkeypatch.setattr(de, "CS_UNET_DATA", str(tmp_path / "unet"))
    monkeypatch.setattr(de, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    monkeypatch.setattr(gc, "CS_NO_CAST_IMAGE", str(tmp_path / "no_cast.png"))
    return tmp_path


def _config(tmp_path, radars=(("BEL", "Belém"),)):
    return {"roots": {"m": str(tmp_path / "media")},
            "pages": [{"name": "A", "duration": 10,
                       "tiles": [{"type": "image", "root": "m", "file": "a.png", "title": "T"},
                                 {"type": "video", "root": "m", "file": "b.mp4"}]},
                      {"type": "nowcast", "name": "Nowcast", "duration": 20,
                       "radars": [list(r) for r in radars]}]}


def test_regular_page_tiles_become_title_and_absolute_path(mosaics):
    page = nc.build_runtime_pages(_config(mosaics), time.time())[0]

    assert page["tiles"] == [("T", str(mosaics / "media" / "a.png")),
                             ("", str(mosaics / "media" / "b.mp4"))]
    assert page["notice"] == "" and page["source_index"] == 0


def test_nowcast_rows_become_mosaic_path_or_unavailable_image(mosaics):
    (mosaics / "unet" / "output" / "BEL_400_now_mosaico.gif").unlink()

    page = nc.build_runtime_pages(_config(mosaics), time.time())[1]

    assert page["layout"] == "rows" and page["source_index"] == 1
    assert page["tiles"] == [
        ("Belém (BEL) - Fluxo óptico", str(mosaics / "oflw" / "output" / "BEL_400_now_mosaico.gif")),
        ("Belém (BEL) - U-Net: sem atualização há mais de 2 h", gc.CS_NO_CAST_IMAGE),
    ]


def test_all_hidden_page_uses_unavailable_image(mosaics):
    page = nc.build_runtime_pages(_config(mosaics, radars=[("ZZZ", "Z")]), time.time())[1]

    assert page["tiles"] == [("Nenhum radar com nowcast recente", gc.CS_NO_CAST_IMAGE)]
    assert page["notice"] == "Sem atualização há mais de 2 h: Z (ZZZ)"


def test_source_index_points_at_config_entry(mosaics):
    (mosaics / "oflw" / "output" / "STI_400_now_mosaico.gif").write_bytes(b"GIF89a")
    config = _config(mosaics, radars=[("BEL", "Belém"), ("STI", "Santiago")])

    pages = nc.build_runtime_pages(config, time.time())

    assert [p["source_index"] for p in pages] == [0, 1, 1]
    assert "source_index" not in config["pages"][0]  # a configuração não é alterada


# ---------------------------------------------------------------------------
# load_config / page_names
# ---------------------------------------------------------------------------

@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config(tmp_path)), encoding="utf-8")
    monkeypatch.setattr(de, "CS_CONFIG_FILE", str(path))
    monkeypatch.setattr(nc, "G_CONFIG_CACHE", dc.CConfigCache())
    monkeypatch.setattr(nc, "G_LAST_CONFIG_ERROR", None)
    return path


def test_page_names_come_from_config(config_file):
    assert nc.page_names() == ["A", "Nowcast"]


def test_broken_config_keeps_last_good_and_logs_once(config_file, caplog):
    good = nc.load_config()

    config_file.write_text("{ broken", encoding="utf-8")
    future = os.path.getmtime(config_file) + 5
    os.utime(config_file, (future, future))

    with caplog.at_level("ERROR", logger=nc.__name__):
        assert nc.load_config() is good
        assert nc.load_config() is good

    assert len(caplog.records) == 1


def test_never_loaded_config_gives_none_and_no_page_names(tmp_path, monkeypatch):
    monkeypatch.setattr(de, "CS_CONFIG_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(nc, "G_CONFIG_CACHE", dc.CConfigCache())

    assert nc.load_config() is None
    assert nc.page_names() == []


def test_real_config_gives_one_pad_button_per_entry():
    assert nc.page_names() == ["Monitor de Recepção de Dados Radar", "Monitoramento de Raios",
                               "NOAA GOES-East", "Nowcast Radar 400 km"]
