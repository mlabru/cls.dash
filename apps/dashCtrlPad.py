# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dashCtrlPad
programa do control pad: botões grandes (touch) que comandam o dashboard
desktop (dashViewQt) por UDP e ligam/desligam o alerta prioritário.

uso (a partir de apps/, por causa dos imports):
    python dashCtrlPad.py

fluxo (main):
  1. cria a QApplication e aplica o estilo touch (CS_QSS_CONTROL);
  2. cria e mostra a janela do pad (dsh_ctrlpad.CControlPadApp);
  3. entra no loop de eventos do Qt.

2026.out  mlabru  refatoração para legibilidade: QSS_CONTROL renomeado para
                  CS_QSS_CONTROL; log em INFO (os traces de DEBUG saíram);
                  corrigido o "font-size" do QLineEdit, que estava partido
                  em duas linhas e era ignorado pelo Qt
                  módulos dsh_* movidos para apps/dash/ (imports dash.dsh_xxx)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging
import sys

# PyQt
from PyQt5 import QtWidgets

# locals
import dash.dsh_ctrlpad as cp

# < constants >────────────────────────────────────────────────────────────────────────

# estilo global (QSS), pensado para tela de toque. Os seletores "#ActionBtn",
# "#StopBtn", "#PlayBtn" e "#AlertBtn" se ligam aos botões pelo objectName
# definido em dsh_ctrlpad
CS_QSS_CONTROL = """
    QWidget { background-color: #121212; font-family: 'Segoe UI', Arial; }

    QPushButton {
        background-color: #2c2c2e;
        color: white;
        border-radius: 10px;
        font-size: 18px;
        font-weight: bold;
        min-height: 80px;
    }

    QPushButton:pressed { background-color: #3a3a3c; }

    QPushButton#ActionBtn { background-color: #007bff; }
    QPushButton#StopBtn { background-color: #444444; }
    QPushButton#PlayBtn { background-color: #28a745; }

    QPushButton#AlertBtn {
        background-color: #330000;
        color: #ff4444;
        border: 2px solid #ff4444;
        font-size: 22px;
    }
    QPushButton#AlertBtn:checked {
        background-color: #ff0000;
        color: white;
    }

    QLabel { color: #aaaaaa; font-size: 14px; margin-bottom: 5px; }

    QLineEdit {
        background-color: #1c1c1e;
        color: white;
        border: 1px solid #333;
        padding: 5px;
        border-radius: 5px;
        font-size: 16px;
    }
"""

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    ponto de entrada do programa (ver o fluxo no topo do módulo).

    :returns: código de saída do loop de eventos do Qt (0 = normal)
    """
    l_app = QtWidgets.QApplication(sys.argv)
    l_app.setStyleSheet(CS_QSS_CONTROL)

    l_control_pad_window = cp.CControlPadApp()
    l_control_pad_window.show()

    return l_app.exec_()

# ─────────────────────────────────────────────────────────────────────────────────────
# this is the bootstrap process

if "__main__" == __name__:

    logging.basicConfig(datefmt="%Y/%m/%d %H:%M",
                        format="%(asctime)s %(message)s",
                        level=logging.INFO)

    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
