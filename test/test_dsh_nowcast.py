# -*- coding: utf-8 -*-
"""testes unitários para apps/dash/dsh_nowcast.py"""

import os
import time

import pytest

import dash.dsh_config as gc
import dash.dsh_nowcast as nc

CLST_RADARS = [("BEL", "Belém"), ("BVA", "Boa Vista"), ("CGU", "Canguçu"),
               ("MDI", "Morro da Igreja"), ("PCO", "Pico do Couto"),
               ("SRO", "São Roque"), ("STI", "Santiago")]


@pytest.fixture
def oflow_output(tmp_path, monkeypatch):
    """saídas do oflow e do u-net com um mosaico recente de 400 km para cada
    radar (devolve a do oflow; a do u-net é a fixture unet_output)."""
    for source in ("oflw", "unet"):
        out = tmp_path / source / "output"
        out.mkdir(parents=True)

        for radar_id, _ in CLST_RADARS:
            (out / f"{radar_id}_400_now_mosaico.gif").write_bytes(b"GIF89a")

    monkeypatch.setattr(gc, "CS_OFLOW_DATA", str(tmp_path / "oflw"))
    monkeypatch.setattr(gc, "CS_UNET_DATA", str(tmp_path / "unet"))
    monkeypatch.setattr(gc, "CS_NO_CAST_IMAGE", str(tmp_path / "no_cast.png"))
    monkeypatch.setattr(gc, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    return tmp_path / "oflw" / "output"


@pytest.fixture
def unet_output(oflow_output):
    return oflow_output.parent.parent / "unet" / "output"


def _unlink_all(*dirs):
    for out in dirs:
        for gif in out.iterdir():
            gif.unlink()


def _entry(radars=CLST_RADARS):
    return {"type": "nowcast", "duration": 20, "name": "Nowcast", "radars": radars}


def test_one_page_per_radar_with_oflow_and_unet_rows(oflow_output, unet_output):
    pages = nc.build_runtime_pages([_entry()], time.time())

    assert len(pages) == 7
    assert pages[0]["name"] == "Nowcast (1/7)"
    assert pages[0]["layout"] == "rows"
    assert pages[0]["tiles"] == [
        ("Belém (BEL) - Fluxo óptico", str(oflow_output / "BEL_400_now_mosaico.gif")),
        ("Belém (BEL) - U-Net", str(unet_output / "BEL_400_now_mosaico.gif")),
    ]
    assert all(p["source_index"] == 0 for p in pages)


def test_radars_without_any_recent_mosaic_are_hidden(oflow_output, unet_output):
    (oflow_output / "BEL_400_now_mosaico.gif").unlink()
    (unet_output / "BEL_400_now_mosaico.gif").unlink()
    old = time.time() - 3 * 3600
    for out in (oflow_output, unet_output):
        os.utime(out / "CGU_400_now_mosaico.gif", (old, old))

    pages = nc.build_runtime_pages([_entry()], time.time())
    titles = [title for p in pages for title, _ in p["tiles"]]

    assert len(pages) == 5
    assert not any("BEL" in t or "CGU" in t for t in titles)


def test_missing_or_stale_source_becomes_unavailable_row(oflow_output, unet_output):
    (unet_output / "BEL_400_now_mosaico.gif").unlink()
    old = time.time() - 3 * 3600
    os.utime(oflow_output / "BVA_400_now_mosaico.gif", (old, old))

    pages = nc.build_runtime_pages([_entry()], time.time())

    assert len(pages) == 7
    assert pages[0]["tiles"][1] == ("Belém (BEL) - U-Net: sem atualização há mais de 2 h",
                                    gc.CS_NO_CAST_IMAGE)
    assert pages[1]["tiles"][0] == ("Boa Vista (BVA) - Fluxo óptico: sem atualização há mais de 2 h",
                                    gc.CS_NO_CAST_IMAGE)
    assert all(p["notice"] == "" for p in pages)


def test_all_hidden_gives_single_unavailable_page(oflow_output, unet_output):
    _unlink_all(oflow_output, unet_output)

    pages = nc.build_runtime_pages([_entry()], time.time())

    assert len(pages) == 1
    assert pages[0]["name"] == "Nowcast"
    assert pages[0]["tiles"] == [(nc.CS_NO_RADAR_TITLE, gc.CS_NO_CAST_IMAGE)]


def test_regular_pages_keep_order_and_get_source_index(oflow_output):
    regular = {"duration": 10, "name": "A", "tiles": []}

    pages = nc.build_runtime_pages([regular, _entry(CLST_RADARS[:3]), regular], time.time())

    assert [p["source_index"] for p in pages] == [0, 1, 1, 1, 2]
    assert pages[0]["name"] == "A" and pages[4]["name"] == "A"
    assert "source_index" not in regular  # a configuração não é alterada


def test_real_config_has_one_nowcast_entry_with_fixed_radar_list():
    entries = [p for p in gc.CLST_PAGES if p.get("type") == nc.CS_NOWCAST_PAGE_TYPE]

    assert len(entries) == 1
    assert entries[0]["radars"] is gc.CLST_NOWCAST_RADARS
    assert gc.CI_NOWCAST_RANGE_KM == 400


def test_notice_lists_hidden_radars(oflow_output, unet_output):
    (oflow_output / "SRO_400_now_mosaico.gif").unlink()
    (unet_output / "SRO_400_now_mosaico.gif").unlink()

    pages = nc.build_runtime_pages([_entry()], time.time())

    assert all(p["notice"] == "Sem atualização há mais de 2 h: São Roque (SRO)" for p in pages)


def test_notice_empty_without_hidden_radars(oflow_output):
    pages = nc.build_runtime_pages([_entry()], time.time())

    assert all(p["notice"] == "" for p in pages)


def test_all_hidden_page_has_notice(oflow_output, unet_output):
    _unlink_all(oflow_output, unet_output)

    page = nc.build_runtime_pages([_entry(CLST_RADARS[:1])], time.time())[0]

    assert page["notice"] == "Sem atualização há mais de 2 h: Belém (BEL)"
