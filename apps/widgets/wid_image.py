# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

wid_image
label que mostra uma imagem estática (QPixmap) ou um GIF animado (QMovie)
sempre do tamanho do label, sem deformar (mantém a proporção original).

como funciona:
  - set_content guarda o conteúdo original e chama update_image;
  - update_image escala o conteúdo para o tamanho atual do label;
  - resizeEvent chama update_image de novo sempre que o label muda de
    tamanho (ex.: quando o layout termina de distribuir o espaço).
  O original nunca é alterado: escalar a partir dele evita perder qualidade
  a cada redimensionamento.

2026.out  mlabru  refatoração para legibilidade: o GIF passa a ser escalado
                  com KeepAspectRatio aqui, a partir do tamanho original lido
                  uma vez (antes o label o esticava para o próprio tamanho e
                  um closure no wid_tile corrigia a proporção a cada frame);
                  sizeHint/hasHeightForWidth viraram métodos da classe (eram
                  lambdas atribuídas de fora, em wid_tile)
2022.apr  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging

# PyQt
from PyQt5 import QtCore, QtGui, QtWidgets

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < CImageLabel >──────────────────────────────────────────────────────────────────────

class CImageLabel(QtWidgets.QLabel):
    """
    QLabel que redimensiona o próprio conteúdo (imagem ou GIF) mantendo a
    proporção.

    o label não "pede" espaço ao layout (sizeHint zero, política Ignored): ele
    ocupa o espaço que sobrar, e o conteúdo se adapta a ele. Sem isso, um GIF
    grande empurraria o layout e deformaria a grade de tiles.
    """
    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self):
        super().__init__()

        # conteúdo original: QPixmap, QMovie ou None
        self._content = None

        # tamanho original dos frames do GIF (QSize vazio se não houver GIF
        # ou se o tamanho não puder ser lido)
        self._gif_original_size = QtCore.QSize()

        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                           QtWidgets.QSizePolicy.Ignored)

    # ─────────────────────────────────────────────────────────────────────────────────
    def sizeHint(self):
        """
        tamanho "preferido" zero: o layout ignora o conteúdo e usa o espaço
        disponível (ver docstring da classe).
        """
        return QtCore.QSize(0, 0)

    # ─────────────────────────────────────────────────────────────────────────────────
    def hasHeightForWidth(self):
        """
        impede que o layout tente calcular a altura em função da largura.
        """
        return False

    # ─────────────────────────────────────────────────────────────────────────────────
    def resizeEvent(self, f_event):
        """
        chamado pelo Qt quando o label muda de tamanho: reescala o conteúdo.
        """
        super().resizeEvent(f_event)
        self.update_image()

    # ─────────────────────────────────────────────────────────────────────────────────
    def set_content(self, f_content):
        """
        troca o conteúdo exibido.

        fluxo:
          - GIF (QMovie): liga o filme ao label, lê o tamanho original dos
            frames e inicia a animação;
          - imagem (QPixmap): desliga um eventual GIF anterior;
          - nos dois casos, escala para o tamanho atual (update_image).

        :param f_content: QtGui.QMovie (GIF) ou QtGui.QPixmap (imagem estática)
        """
        self._content = f_content

        if isinstance(f_content, QtGui.QMovie):
            self._gif_original_size = _read_gif_original_size(f_content)
            self.setMovie(f_content)
            f_content.start()

        elif isinstance(f_content, QtGui.QPixmap):
            self._gif_original_size = QtCore.QSize()
            self.setMovie(None)

        self.update_image()

    # ─────────────────────────────────────────────────────────────────────────────────
    def update_image(self):
        """
        escala o conteúdo original para o tamanho atual do label, mantendo a
        proporção. Não faz nada se ainda não há conteúdo ou se o label ainda
        não tem tamanho (antes de o layout distribuir o espaço).
        """
        if not self._content:
            return

        if self.size().isEmpty():
            return

        if isinstance(self._content, QtGui.QMovie):
            self._scale_gif_to_label()

        elif isinstance(self._content, QtGui.QPixmap):
            self._scale_pixmap_to_label()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _scale_gif_to_label(self):
        """
        GIF: o QMovie desenha cada frame já no tamanho de setScaledSize.
        Sem o tamanho original (arquivo ilegível), deixa o GIF como está.
        """
        if self._gif_original_size.isEmpty():
            return

        l_fitted_size = self._gif_original_size.scaled(self.size(), QtCore.Qt.KeepAspectRatio)
        self._content.setScaledSize(l_fitted_size)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _scale_pixmap_to_label(self):
        """
        imagem estática: gera uma cópia escalada do original e a exibe.
        """
        l_scaled_pixmap = self._content.scaled(self.size(),
                                               QtCore.Qt.KeepAspectRatio,
                                               QtCore.Qt.SmoothTransformation)
        super().setPixmap(l_scaled_pixmap)

# ─────────────────────────────────────────────────────────────────────────────────────
def _read_gif_original_size(f_movie):
    """
    lê o tamanho original dos frames de um GIF direto do arquivo, sem
    decodificar a animação.

    :param f_movie: QtGui.QMovie do GIF
    :returns: QtCore.QSize com largura x altura originais; vazio se o QMovie
              não tem arquivo ou o arquivo não pôde ser lido
    """
    ls_filename = f_movie.fileName()

    if not ls_filename:
        return QtCore.QSize()

    l_original_size = QtGui.QImageReader(ls_filename).size()

    if not l_original_size.isValid():
        M_LOG.warning(f"não foi possível ler o tamanho do GIF {ls_filename!r}")
        return QtCore.QSize()

    return l_original_size

# < the end >──────────────────────────────────────────────────────────────────────────
