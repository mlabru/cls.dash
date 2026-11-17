import os
import pathlib
import sys

# põe apps/ no sys.path: permite "import widgets.xxx" e "import dash.xxx"
# independente do diretório de onde o pytest for chamado. Insere na posição 0
# para apps/dash ganhar do Plotly Dash, se ele estiver instalado (ver
# apps/dash/__init__.py)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps")))

# roda o Qt sem precisar de um display real (headless / CI)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

@pytest.fixture(scope="session")
def qapp():
    """uma única QApplication para todo o processo de testes (exigência do Qt)"""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def hidden_radars_state_in_process(monkeypatch):
    """sem arquivo de estado dos radares ocultos (como no desktop): importar
    apps/be/app.py na mesma sessão do pytest o aponta para data/run"""
    from dshcore import dsc_nowcast
    monkeypatch.setattr(dsc_nowcast, "G_HIDDEN_STATE_FILE", None)
    monkeypatch.setattr(dsc_nowcast, "G_HIDDEN_RADARS", set())
    monkeypatch.setattr(dsc_nowcast, "G_HIDDEN_STATE_TOKEN", None)

# a suíte não depende do cls.env de quem a roda (~/.config/cls/cls.env): os
# scripts shell testados herdam este ambiente e não carregam nada de lá
os.environ["CLS_ENV_FILE"] = os.devnull

# cls_common.sh: CLS_LIB do ambiente ou, no checkout de desenvolvimento, o
# repo cls.common irmão (<raiz>/cls.common, com o projeto em
# <raiz>/<nn>.<proj>/cls.<proj>)
os.environ.setdefault("CLS_LIB", str(pathlib.Path(__file__).resolve().parents[3]
                                     / "cls.common" / "bash"))

