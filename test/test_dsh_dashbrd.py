# -*- coding: utf-8 -*-
"""testes unitários para apps/dash/dsh_dashbrd.py"""

import os
import socket

import pytest

import dash.dsh_config as gc
import dash.dsh_dashbrd as ad
import dash.dsh_nowcast as nc
from dshcore import dsc_env as de


def _use_pages(monkeypatch, pages, roots=None):
    """troca o config.json por uma config em memória (sem depender de mídia externa)"""
    config = {"roots": roots or {"m": "/nao"}, "pages": pages}
    monkeypatch.setattr(nc, "load_config", lambda: config)


def _regular(name, duration=10, files=()):
    return {"duration": duration, "name": name,
            "tiles": [{"type": "image", "root": "m", "file": f, "title": "X"} for f in files]}


def _free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def dashboard(qapp, tmp_path, monkeypatch):
    # isola o teste do dsh_config real: porta livre, alerta em arquivo temporário
    # e páginas fixas (sem depender de mídia externa)
    monkeypatch.setattr(gc, "CI_DASHBOARD_PORT", _free_udp_port())
    monkeypatch.setattr(gc, "CS_ALERT_TRIGGER", str(tmp_path / "ALERTA_ATIVO.txt"))
    monkeypatch.setattr(gc, "CS_NO_CAST_IMAGE", str(tmp_path / "no_cast.png"))
    monkeypatch.setattr(de, "CS_OFLOW_DATA", str(tmp_path / "oflw"))
    monkeypatch.setattr(de, "CS_UNET_DATA", str(tmp_path / "unet"))
    monkeypatch.setattr(de, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    _use_pages(monkeypatch, [_regular("Página A"), _regular("Página B"), _regular("Página C")])

    app = ad.CDashboardApp()
    app._update_timer.stop()  # controlamos o avanço manualmente nos testes

    return app


def test_starts_on_page_zero(dashboard):
    assert dashboard._current_page_index == 0


def test_goto_command_changes_page(dashboard):
    dashboard.process_remote_command("GOTO 2", "127.0.0.1")
    assert dashboard._current_page_index == 2


def test_next_and_prev_wrap_around(dashboard):
    dashboard.process_remote_command("NEXT", "127.0.0.1")
    assert dashboard._current_page_index == 1

    dashboard.process_remote_command("PREV", "127.0.0.1")
    dashboard.process_remote_command("PREV", "127.0.0.1")
    assert dashboard._current_page_index == 2  # (0 - 1) % 3 -> dá a volta


def test_goto_with_invalid_index_is_ignored(dashboard):
    dashboard.process_remote_command("GOTO abc", "127.0.0.1")
    assert dashboard._current_page_index == 0


def test_stop_then_update_timer_does_not_advance(dashboard):
    dashboard.process_remote_command("STOP", "127.0.0.1")
    before = dashboard._current_page_index

    dashboard._on_update_timer()  # simula o timer disparando enquanto pausado

    assert dashboard._current_page_index == before
    assert dashboard._is_paused is True


def test_start_resets_pause_flag(dashboard):
    dashboard.process_remote_command("STOP", "127.0.0.1")
    dashboard.process_remote_command("START", "127.0.0.1")

    assert dashboard._is_paused is False


def test_alert_file_triggers_priority_mode(dashboard):
    with open(gc.CS_ALERT_TRIGGER, "w") as fh:
        fh.write("ALERTA")

    dashboard._on_update_timer()

    assert dashboard._in_priority_alert is True
    assert dashboard._current_page_index == 0


def test_priority_mode_ignores_remote_commands(dashboard):
    dashboard.process_remote_command("GOTO 1", "127.0.0.1")  # muda de página antes do alerta

    with open(gc.CS_ALERT_TRIGGER, "w") as fh:
        fh.write("ALERTA")
    dashboard._on_update_timer()

    dashboard.process_remote_command("GOTO 2", "127.0.0.1")

    assert dashboard._current_page_index == 0  # comando ignorado, alerta forçou a página 0


def test_removing_alert_file_exits_priority_mode(dashboard):
    with open(gc.CS_ALERT_TRIGGER, "w") as fh:
        fh.write("ALERTA")
    dashboard._on_update_timer()
    assert dashboard._in_priority_alert is True

    os.remove(gc.CS_ALERT_TRIGGER)
    dashboard._on_update_timer()

    assert dashboard._in_priority_alert is False


def test_tile_exception_does_not_crash_page_change(dashboard, monkeypatch):
    # uma exceção dentro de update_content (slot Qt) abortaria o PyQt5
    def _boom(self, *_args):
        raise RuntimeError("falha simulada no tile")

    monkeypatch.setattr(ad.wt.CTileWidget, "update_content", _boom)
    _use_pages(monkeypatch, [_regular("Página A"), _regular("Página B", files=["existe.png"])])

    dashboard.process_remote_command("NEXT", "127.0.0.1")

    assert dashboard._current_page_index == 1
    assert dashboard._lay_tiles.count() == 1


# ---------------------------------------------------------------------------
# páginas de nowcast e cabeçalho
# ---------------------------------------------------------------------------

def _make_mosaics(tmp_path, radar_ids):
    for source in ("oflw", "unet"):
        out = tmp_path / source / "output"
        out.mkdir(parents=True, exist_ok=True)
        for radar_id in radar_ids:
            (out / f"{radar_id}_400_now_mosaico.gif").write_bytes(b"GIF89a")


@pytest.fixture
def nowcast_dashboard(dashboard, tmp_path, monkeypatch):
    _make_mosaics(tmp_path, ["AAA", "BBB"])
    _use_pages(monkeypatch, [
        _regular("Página A"),
        {"type": "nowcast", "duration": 20, "name": "Nowcast",
         "radars": [["AAA", "Radar A"], ["BBB", "Radar B"]]},
        _regular("Página C"),
    ])
    dashboard._show_page(0)
    return dashboard


def test_header_shows_page_name(dashboard):
    assert dashboard._lbl_header.text() == "Página A"

    dashboard.process_remote_command("NEXT", "127.0.0.1")
    assert dashboard._lbl_header.text() == "Página B"


def test_nowcast_entry_expands_into_one_page_per_radar_with_two_rows(nowcast_dashboard):
    dashboard = nowcast_dashboard

    dashboard.process_remote_command("NEXT", "127.0.0.1")
    assert dashboard._lbl_header.text() == "Nowcast (1/2)"
    assert dashboard._lay_tiles.count() == 2
    assert dashboard._lay_tiles.direction() == ad.QtWidgets.QBoxLayout.TopToBottom

    dashboard.process_remote_command("NEXT", "127.0.0.1")
    assert dashboard._lbl_header.text() == "Nowcast (2/2)"
    assert dashboard._lay_tiles.count() == 2

    dashboard.process_remote_command("NEXT", "127.0.0.1")
    assert dashboard._lbl_header.text() == "Página C"
    assert dashboard._lay_tiles.direction() == ad.QtWidgets.QBoxLayout.LeftToRight


def test_goto_uses_config_index_and_lands_on_first_nowcast_page(nowcast_dashboard):
    nowcast_dashboard.process_remote_command("GOTO 2", "127.0.0.1")
    assert nowcast_dashboard._lbl_header.text() == "Página C"

    nowcast_dashboard.process_remote_command("GOTO 1", "127.0.0.1")
    assert nowcast_dashboard._lbl_header.text() == "Nowcast (1/2)"


def test_alert_header_survives_page_change_and_restores_page_name(nowcast_dashboard):
    with open(gc.CS_ALERT_TRIGGER, "w") as fh:
        fh.write("ALERTA")
    nowcast_dashboard._on_update_timer()
    assert nowcast_dashboard._lbl_header.text() == ad.CS_ALERT_HEADER

    os.remove(gc.CS_ALERT_TRIGGER)
    nowcast_dashboard._on_update_timer()
    assert nowcast_dashboard._lbl_header.text() == "Página A"


def test_notice_label_visible_only_on_page_with_hidden_radars(dashboard, tmp_path, monkeypatch):
    _make_mosaics(tmp_path, ["AAA"])
    _use_pages(monkeypatch, [
        _regular("Página A"),
        {"type": "nowcast", "duration": 20, "name": "Nowcast",
         "radars": [["AAA", "Radar A"], ["ZZZ", "Radar Z"]]},
    ])

    dashboard.process_remote_command("GOTO 0", "127.0.0.1")
    assert dashboard._lbl_notice.isHidden()

    dashboard.process_remote_command("GOTO 1", "127.0.0.1")
    assert not dashboard._lbl_notice.isHidden()
    assert dashboard._lbl_notice.text() == "Sem atualização há mais de 2 h: Radar Z (ZZZ)"


@pytest.mark.parametrize("duration", [0, -1, None, "abc", float("nan")])
def test_page_duration_invalid_falls_back_to_minimum(duration):
    assert ad._page_duration({"duration": duration}) == ad.CF_MIN_PAGE_SECONDS


def test_page_duration_valid_is_kept():
    assert ad._page_duration({"duration": 15}) == 15.


def test_zero_duration_page_does_not_crash_timer(dashboard, monkeypatch):
    # duration 0 dividia por zero dentro do slot do timer (o PyQt5 aborta)
    _use_pages(monkeypatch, [_regular("Z", duration=0), _regular("Y")])
    dashboard._show_page(0)
    dashboard._page_start_time -= 2 * ad.CF_MIN_PAGE_SECONDS

    dashboard._advance_page_timer()

    assert dashboard._current_page_index == 1


def test_without_any_valid_config_shows_nothing_and_does_not_crash(dashboard, monkeypatch):
    monkeypatch.setattr(nc, "load_config", lambda: None)

    dashboard._show_page(1)
    dashboard.process_remote_command("GOTO 0", "127.0.0.1")
    dashboard._advance_page_timer()

    assert dashboard._llst_pages == []


def test_regular_tile_path_comes_from_root(dashboard, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ad.wt.CTileWidget, "update_content",
                        lambda self, title, path: seen.append((title, path)))
    _use_pages(monkeypatch, [_regular("A", files=["sub/a.png"])], roots={"m": str(tmp_path)})

    dashboard._show_page(0)

    assert seen == [("X", str(tmp_path / "sub" / "a.png"))]
