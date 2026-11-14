# -*- coding: utf-8 -*-
"""testes unitários para apps/dshcore/dsc_nowcast.py (regra comum aos dois dashboards)"""

import os
import time

import pytest

from dshcore import dsc_env as de
from dshcore import dsc_nowcast as dn

CLST_RADARS = [["BEL", "Belém"], ["BVA", "Boa Vista"], ["CGU", "Canguçu"],
               ["MDI", "Morro da Igreja"], ["PCO", "Pico do Couto"],
               ["SRO", "São Roque"], ["STI", "Santiago"]]


@pytest.fixture
def oflow_output(tmp_path, monkeypatch):
    """saídas do oflow e do u-net com um mosaico recente de 400 km para cada
    radar (devolve a do oflow; a do u-net é a fixture unet_output)."""
    for source in ("oflw", "unet"):
        out = tmp_path / source / "output"
        out.mkdir(parents=True)

        for radar_id, _ in CLST_RADARS:
            (out / f"{radar_id}_400_now_mosaico.gif").write_bytes(b"GIF89a")

    monkeypatch.setattr(de, "CS_OFLOW_DATA", str(tmp_path / "oflw"))
    monkeypatch.setattr(de, "CS_UNET_DATA", str(tmp_path / "unet"))
    monkeypatch.setattr(de, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    return tmp_path / "oflw" / "output"


@pytest.fixture
def unet_output(oflow_output):
    return oflow_output.parent.parent / "unet" / "output"


def _entry(radars=CLST_RADARS):
    return {"type": "nowcast", "duration": 20, "name": "Nowcast", "radars": radars}


def _make_old(path, hours):
    old = os.path.getmtime(path) - hours * 3600
    os.utime(path, (old, old))


def _unlink_all(*dirs):
    for out in dirs:
        for gif in out.iterdir():
            gif.unlink()


def _pages(entry):
    # tile = a própria linha: os testes olham o que a regra decidiu
    return dn.build_pages(entry, time.time(), lambda row: row)


def test_one_page_per_radar_with_oflow_and_unet_rows(oflow_output, unet_output):
    pages = _pages(_entry())

    assert len(pages) == 7
    assert [p["name"] for p in pages][:2] == ["Nowcast (1/7)", "Nowcast (2/7)"]
    assert all(p["layout"] == "rows" and p["duration"] == 20 and p["notice"] == "" for p in pages)

    oflow_row, unet_row = pages[0]["tiles"]
    assert (oflow_row["source"], unet_row["source"]) == ("oflow", "unet")
    assert oflow_row["title"] == "Belém (BEL) - Fluxo óptico"
    assert unet_row["title"] == "Belém (BEL) - U-Net"
    assert oflow_row["path"] == str(oflow_output / "BEL_400_now_mosaico.gif")
    assert unet_row["path"] == str(unet_output / "BEL_400_now_mosaico.gif")
    assert oflow_row["available"] and oflow_row["mtime"] is not None


def test_single_page_has_no_counter_in_name(oflow_output):
    assert [p["name"] for p in _pages(_entry(CLST_RADARS[:1]))] == ["Nowcast"]


def test_radars_without_any_recent_mosaic_are_hidden(oflow_output, unet_output):
    (oflow_output / "BEL_400_now_mosaico.gif").unlink()
    (unet_output / "BEL_400_now_mosaico.gif").unlink()
    _make_old(oflow_output / "CGU_400_now_mosaico.gif", hours=3)
    (unet_output / "CGU_400_now_mosaico.gif").unlink()

    pages = _pages(_entry())
    titles = [row["title"] for p in pages for row in p["tiles"]]

    assert len(pages) == 5
    assert not any("BEL" in t or "CGU" in t for t in titles)
    assert all(p["notice"] == "Sem atualização há mais de 2 h: Belém (BEL), Canguçu (CGU)"
               for p in pages)


def test_missing_or_stale_source_becomes_unavailable_row(oflow_output, unet_output):
    (unet_output / "BEL_400_now_mosaico.gif").unlink()
    _make_old(oflow_output / "BVA_400_now_mosaico.gif", hours=3)

    pages = _pages(_entry())

    assert len(pages) == 7
    assert pages[0]["tiles"][0]["available"]
    assert not pages[0]["tiles"][1]["available"]
    assert pages[0]["tiles"][1]["title"] == "Belém (BEL) - U-Net: sem atualização há mais de 2 h"
    assert pages[0]["tiles"][1]["mtime"] is None
    assert not pages[1]["tiles"][0]["available"] and pages[1]["tiles"][1]["available"]


def test_only_400_km_mosaics_count(oflow_output, unet_output):
    for out in (oflow_output, unet_output):
        for radar_id, _ in CLST_RADARS:
            (out / f"{radar_id}_400_now_mosaico.gif").rename(out / f"{radar_id}_250_now_mosaico.gif")

    pages = _pages(_entry())

    assert len(pages) == 1 and pages[0]["tiles"][0]["title"] == dn.CS_NO_RADAR_TITLE


def test_all_hidden_gives_single_unavailable_page_with_notice(oflow_output, unet_output):
    _unlink_all(oflow_output, unet_output)

    pages = _pages(_entry(CLST_RADARS[:1]))

    assert len(pages) == 1
    assert pages[0]["name"] == "Nowcast"
    assert "layout" not in pages[0]
    assert pages[0]["tiles"] == [{"source": None, "title": dn.CS_NO_RADAR_TITLE,
                                  "available": False, "file_name": None, "path": None,
                                  "mtime": None}]
    assert pages[0]["notice"] == "Sem atualização há mais de 2 h: Belém (BEL)"


def test_radar_rows_reports_hidden_and_unavailable(oflow_output, unet_output):
    (oflow_output / "STI_400_now_mosaico.gif").unlink()
    (unet_output / "STI_400_now_mosaico.gif").unlink()
    (unet_output / "BEL_400_now_mosaico.gif").unlink()

    visible, hidden, unavailable = dn.radar_rows(_entry(), time.time())

    assert len(visible) == 6
    assert hidden == [("STI", "Santiago")]
    assert unavailable == ["BEL/unet"]


def test_hidden_set_change_is_logged_once(oflow_output, unet_output, caplog, monkeypatch):
    monkeypatch.setattr(dn, "G_HIDDEN_RADARS", set())
    (oflow_output / "SRO_400_now_mosaico.gif").unlink()
    (unet_output / "SRO_400_now_mosaico.gif").unlink()

    with caplog.at_level("WARNING", logger=dn.__name__):
        _pages(_entry())
        _pages(_entry())

    assert [r.getMessage() for r in caplog.records].count(
        "nowcast: radares ocultos (sem mosaico ou mais velho que 2h): SRO") == 1


def test_source_output_dir_unknown_source_is_none(oflow_output):
    assert dn.source_output_dir("xxx") is None
    assert dn.source_output_dir("unet") == str(oflow_output.parent.parent / "unet" / "output")
