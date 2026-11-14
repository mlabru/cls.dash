# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dashViewQt
programa do dashboard desktop (NOC / videowall), em tela cheia. Não foi
feito para interação direta: é comandado pelo control pad (dashCtrlPad).

uso (a partir de apps/, por causa dos imports):
    python dashViewQt.py [índice_da_tela]

    índice_da_tela: 0 = monitor principal (padrão), 1 = TV/videowall, ...

fluxo (main):
  1. cria a QApplication e aplica o estilo global (CS_QSS_STYLE);
  2. cria a janela do dashboard (dsh_dashbrd.CDashboardApp);
  3. se foi pedido um índice de tela válido, move a janela para essa tela;
  4. mostra em tela cheia e entra no loop de eventos do Qt.

2026.out  mlabru  refatoração para legibilidade: main dividido (leitura do
                  argumento, escolha da tela); QSS_STYLE renomeado para
                  CS_QSS_STYLE; winId() antes de windowHandle() (sem ele o
                  handle é None antes do show() e a tela pedida era ignorada)
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
import dash.dsh_dashbrd as db

# < constants >────────────────────────────────────────────────────────────────────────

# estilo global (QSS). Os seletores "#Title" e "#Caption" valem para os labels
# de título e rodapé dos tiles (wid_tile, via setObjectName)
CS_QSS_STYLE = """
    QMainWindow { background-color: #0e1117; }

    QLabel#Title { color: #ff4b4b; font-size: 22px; font-weight: bold; }
    QLabel#Caption { color: #808495; font-size: 14px; }

    QProgressBar { border: none; background-color: #262730; height: 6px; }
    QProgressBar::chunk { background-color: #ff4b4b; }

    QStatusBar {
        background-color: #1a1c24;
        color: #00ff00;
        font-family: 'Courier New';
        border-top: 1px solid #333;
    }
"""

# tela usada quando nenhum índice válido é informado
CI_DEFAULT_SCREEN_INDEX = 0

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    ponto de entrada do programa (ver o fluxo no topo do módulo).

    :returns: código de saída do loop de eventos do Qt (0 = normal)
    """
    l_app = QtWidgets.QApplication(sys.argv)
    l_app.setStyleSheet(CS_QSS_STYLE)

    l_dashboard_window = db.CDashboardApp()

    li_screen_index = _read_screen_index(sys.argv)
    _move_window_to_screen(l_dashboard_window, l_app, li_screen_index)

    l_dashboard_window.showFullScreen()

    return l_app.exec_()

# ─────────────────────────────────────────────────────────────────────────────────────
def _read_screen_index(flst_argv: list) -> int:
    """
    lê o índice da tela do primeiro argumento da linha de comando.

    :param flst_argv: argumentos do programa (sys.argv)
    :returns: o índice informado, ou CI_DEFAULT_SCREEN_INDEX se não houver
              argumento ou ele não for um número inteiro
    """
    if len(flst_argv) < 2:
        return CI_DEFAULT_SCREEN_INDEX

    try:
        return int(flst_argv[1])

    except ValueError:
        M_LOG.warning(f"índice de tela inválido ({flst_argv[1]!r}), usando o padrão "
                      f"({CI_DEFAULT_SCREEN_INDEX})")
        return CI_DEFAULT_SCREEN_INDEX

# ─────────────────────────────────────────────────────────────────────────────────────
def _move_window_to_screen(f_window, f_app, fi_screen_index: int):
    """
    coloca a janela na tela pedida, antes de ela ser mostrada. Se o índice
    não existir (ex.: TV desligada), a janela fica na tela padrão.

    :param f_window: janela principal (ainda não mostrada)
    :param f_app: a QApplication, que conhece as telas disponíveis
    :param fi_screen_index: índice da tela em f_app.screens()
    """
    llst_screens = f_app.screens()

    if fi_screen_index >= len(llst_screens):
        M_LOG.warning(f"tela {fi_screen_index} não existe ({len(llst_screens)} disponíveis), "
                      "usando a tela padrão")
        return

    l_target_screen = llst_screens[fi_screen_index]

    # winId() obriga o Qt a criar a janela nativa agora: antes do show(),
    # windowHandle() devolve None e a escolha da tela seria ignorada
    f_window.winId()
    f_window.windowHandle().setScreen(l_target_screen)

    # move também para o canto da tela, caso as telas não estejam alinhadas
    # num desktop virtual
    l_screen_geometry = l_target_screen.geometry()
    f_window.move(l_screen_geometry.left(), l_screen_geometry.top())

# ─────────────────────────────────────────────────────────────────────────────────────
# this is the bootstrap process

if "__main__" == __name__:

    logging.basicConfig(level=logging.INFO)

    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
