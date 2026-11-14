# -*- coding: utf-8 -*-
"""testes unitários para apps/dash/dsh_ctrlpad.py"""

import pytest
from PyQt5 import QtWidgets

import dash.dsh_config as gc
import dash.dsh_ctrlpad as cp


@pytest.fixture
def pad(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CS_ALERT_TRIGGER", str(tmp_path / "ALERTA_ATIVO.txt"))
    # evita a messageBox modal travar o teste
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *_a, **_k: None)

    return cp.CControlPadApp()


def test_toggle_alert_creates_and_removes_trigger_file(pad):
    import os

    pad._btn_alert.setChecked(True)
    assert os.path.exists(gc.CS_ALERT_TRIGGER)

    pad._btn_alert.setChecked(False)
    assert not os.path.exists(gc.CS_ALERT_TRIGGER)


def test_toggle_alert_failure_reverts_button_without_running_opposite_action(pad, tmp_path, monkeypatch):
    # diretório inexistente: open() falha ao criar o gatilho
    monkeypatch.setattr(gc, "CS_ALERT_TRIGGER", str(tmp_path / "nao_existe" / "ALERTA_ATIVO.txt"))

    calls = []
    original = pad._on_alert_button_toggled
    monkeypatch.setattr(pad, "_on_alert_button_toggled", lambda fv: (calls.append(fv), original(fv)))

    pad._btn_alert.toggled.disconnect()
    pad._btn_alert.toggled.connect(pad._on_alert_button_toggled)

    pad._btn_alert.setChecked(True)

    assert pad._btn_alert.isChecked() is False
    assert calls == [True]  # o revert não reexecutou o slot com False
    assert pad.statusBar().currentMessage() != "ALERTA DESATIVADO"
