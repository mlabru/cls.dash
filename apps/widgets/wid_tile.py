# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

wid_tile
um "tile" do dashboard: título em cima, mídia no meio, data de atualização
embaixo. A mídia pode ser imagem estática, GIF animado ou vídeo MP4.

layout do tile:
  ┌──────────────────────────────┐
  │ _lbl_title                   │
  ├──────────────────────────────┤
  │ _lay_media (empilhado):      │
  │   _lbl_image  (imagem / GIF) │  só um dos dois aparece por vez
  │   _wid_video  (MP4)          │
  ├──────────────────────────────┤
  │ _lbl_caption ("Atualizado…") │
  └──────────────────────────────┘

fluxo (update_content):
  1. procura o arquivo (ou um "irmão" com outra extensão, ver
     CT_FALLBACK_EXTENSIONS); sem arquivo, mostra a imagem de indisponível
     (set_unavailable_image; sem ela, o texto "Produto indisponível");
  2. para o que estava tocando (stop_playback);
  3. exibe conforme a extensão: vídeo, GIF ou imagem;
  4. faz um fade-in e escreve a data de modificação no rodapé.

2026.out  mlabru  imagem de indisponível configurável
                  (set_unavailable_image: o no_cast.png do 25.oflow) e
                  rodapé "Arquivo não encontrado"
2026.out  mlabru  refatoração para legibilidade: update_content dividido por
                  tipo de mídia; removido o "reload inteligente" (o
                  dashboard cria tiles novos a cada página, então ele nunca
                  era usado); o ajuste de proporção do GIF foi para o
                  CImageLabel (o closure de frameChanged saiu);
                  stop_playback público, chamado pelo dashboard antes de
                  descartar o tile; tolera o arquivo sumir entre exists() e
                  getmtime() (pipeline regravando o produto)
2022.apr  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import datetime
import logging
import os

# PyQt
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5 import QtMultimedia, QtMultimediaWidgets

# locals
import widgets.wid_image as wi

# < constants >────────────────────────────────────────────────────────────────────────

# extensões tentadas, nesta ordem, quando o arquivo configurado não existe.
# Ex.: a página pede "slm_out.gif", mas o pipeline passou a gerar
# "slm_out.mp4": o tile encontra o .mp4 sem precisar mudar a configuração
CT_FALLBACK_EXTENSIONS = (".mp4", ".gif", ".png", ".jpg")

# texto exibido quando nenhum arquivo foi encontrado e não há imagem de
# indisponível (G_UNAVAILABLE_PIXMAP)
CS_UNAVAILABLE_TEXT = "❌ Produto indisponível"

# rodapé do tile quando nenhum arquivo foi encontrado
CS_NOT_FOUND_CAPTION = "Arquivo não encontrado"

# texto provisório do título e do rodapé, antes do primeiro conteúdo
CS_PLACEHOLDER_TEXT = "───"

# duração (ms) do fade-in ao trocar o conteúdo
CI_FADE_DURATION_MS = 300

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < global state >─────────────────────────────────────────────────────────────────────

# imagem mostrada no lugar de um produto indisponível; None = só o texto
# CS_UNAVAILABLE_TEXT. Definida uma vez pelo dashboard (set_unavailable_image)
G_UNAVAILABLE_PIXMAP = None

# ─────────────────────────────────────────────────────────────────────────────────────
def set_unavailable_image(fs_path: str):
    """
    define a imagem de indisponível de todos os tiles. Arquivo ausente ou
    ilegível deixa só o texto (o dashboard não depende do 25.oflow para subir).

    :param fs_path: caminho da imagem (ex.: o no_cast.png do 25.oflow)
    """
    global G_UNAVAILABLE_PIXMAP

    l_pixmap = QtGui.QPixmap(fs_path) if fs_path and os.path.isfile(fs_path) else QtGui.QPixmap()

    if l_pixmap.isNull():
        M_LOG.warning(f"imagem de indisponível não carregada ({fs_path!r}): usando texto")
        G_UNAVAILABLE_PIXMAP = None
        return

    G_UNAVAILABLE_PIXMAP = l_pixmap

# < CVideoWidget >─────────────────────────────────────────────────────────────────────

class CVideoWidget(QtMultimediaWidgets.QVideoWidget):
    """
    QVideoWidget que não pede espaço ao layout.

    o QVideoWidget padrão informa a resolução do vídeo como tamanho
    preferido assim que o vídeo carrega, e isso empurra a grade de tiles.
    Este reporta tamanho zero e ocupa só o espaço que o layout der; o vídeo
    continua desenhado com a proporção certa (KeepAspectRatio).
    """
    def sizeHint(self):
        """
        tamanho preferido zero: o layout usa o espaço disponível.
        """
        return QtCore.QSize(0, 0)

    def hasHeightForWidth(self):
        """
        impede que o layout calcule a altura em função da largura.
        """
        return False

# < CTileWidget >──────────────────────────────────────────────────────────────────────

class CTileWidget(QtWidgets.QWidget):
    """
    um tile do dashboard (ver o desenho no topo do módulo).

    uso:
        l_tile = CTileWidget()
        l_tile.update_content("Radar", "/caminho/monrad.png")
        ...
        l_tile.stop_playback()   # antes de descartar o tile
    """
    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self):
        super().__init__()

        # o que está tocando agora (no máximo um dos dois)
        self._gif_movie = None
        self._video_player = None

        self._lbl_title = _create_centered_label(CS_PLACEHOLDER_TEXT, "Title")
        self._lbl_caption = _create_centered_label(CS_PLACEHOLDER_TEXT, "Caption")

        self._lbl_image = wi.CImageLabel()

        self._wid_video = CVideoWidget()
        self._wid_video.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self._wid_video.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                      QtWidgets.QSizePolicy.Expanding)

        # imagem e vídeo empilhados: setCurrentWidget escolhe qual aparece
        self._lay_media = QtWidgets.QStackedLayout()
        self._lay_media.addWidget(self._lbl_image)
        self._lay_media.addWidget(self._wid_video)

        l_media_container = QtWidgets.QWidget()
        l_media_container.setLayout(self._lay_media)

        l_layout = QtWidgets.QVBoxLayout(self)
        l_layout.addWidget(self._lbl_title)
        l_layout.addWidget(l_media_container, 1)  # 1 = a mídia fica com o espaço que sobra
        l_layout.addWidget(self._lbl_caption)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)

        # fade-in: anima a opacidade do container de mídia de 0 a 1
        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect()
        l_media_container.setGraphicsEffect(self._opacity_effect)

        self._fade_animation = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(CI_FADE_DURATION_MS)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)

    # ─────────────────────────────────────────────────────────────────────────────────
    def update_content(self, fs_title: str, fs_file: str):
        """
        mostra um novo conteúdo no tile (ver o fluxo no topo do módulo).

        :param fs_title: texto do título do tile
        :param fs_file: caminho do arquivo de mídia configurado; a extensão
                        decide o tipo (.mp4 = vídeo, .gif = GIF, outro = imagem)
        """
        self._lbl_title.setText(fs_title)

        ls_media_file = _find_existing_media_file(fs_file)

        if ls_media_file is None:
            self._show_unavailable()
            return

        # lido antes de trocar a mídia: se o arquivo sumir agora (pipeline
        # regravando), o tile fica "indisponível" em vez de quebrar
        try:
            lf_modified_timestamp = os.path.getmtime(ls_media_file)

        except OSError:
            self._show_unavailable()
            return

        self.stop_playback()

        ls_lower_name = ls_media_file.lower()

        if ls_lower_name.endswith(".mp4"):
            self._show_video(ls_media_file)

        elif ls_lower_name.endswith(".gif"):
            self._show_gif(ls_media_file)

        else:
            self._show_static_image(ls_media_file)

        self._fade_animation.stop()
        self._fade_animation.start()

        self._show_modified_time(lf_modified_timestamp)

    # ─────────────────────────────────────────────────────────────────────────────────
    def stop_playback(self):
        """
        para o GIF ou o vídeo que estiver tocando. Chamar antes de trocar o
        conteúdo e antes de descartar o tile, para o player não continuar
        decodificando em segundo plano.
        """
        if self._gif_movie is not None:
            self._gif_movie.stop()
            self._gif_movie = None

        if self._video_player is not None:
            self._video_player.stop()
            self._video_player = None

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_unavailable(self):
        """
        mostra a imagem de indisponível (ou, sem ela, o texto) no lugar da
        mídia, e avisa no rodapé.
        """
        self.stop_playback()

        if G_UNAVAILABLE_PIXMAP is None:
            self._lbl_image.setText(CS_UNAVAILABLE_TEXT)

        else:
            self._lbl_image.set_content(G_UNAVAILABLE_PIXMAP)

        self._lay_media.setCurrentWidget(self._lbl_image)
        self._lbl_caption.setText(CS_NOT_FOUND_CAPTION)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_video(self, fs_file: str):
        """
        toca um MP4 mudo e em loop.

        :param fs_file: caminho do arquivo .mp4 (já verificado que existe)
        """
        self._video_player = QtMultimedia.QMediaPlayer(None, QtMultimedia.QMediaPlayer.VideoSurface)
        self._video_player.setVideoOutput(self._wid_video)
        self._video_player.setMedia(QtMultimedia.QMediaContent(QtCore.QUrl.fromLocalFile(fs_file)))
        self._video_player.mediaStatusChanged.connect(self._restart_video_when_finished)

        self._lay_media.setCurrentWidget(self._wid_video)
        self._video_player.play()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _restart_video_when_finished(self, f_media_status):
        """
        loop do vídeo: o QMediaPlayer do Qt5 não tem modo de repetição, então
        quando o vídeo chega ao fim ele é rebobinado e tocado de novo.

        :param f_media_status: QMediaPlayer.MediaStatus recebido do sinal
        """
        if f_media_status != QtMultimedia.QMediaPlayer.EndOfMedia:
            return

        self._video_player.setPosition(0)
        self._video_player.play()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_gif(self, fs_file: str):
        """
        mostra um GIF animado (o CImageLabel cuida da escala e da animação).

        :param fs_file: caminho do arquivo .gif (já verificado que existe)
        """
        self._gif_movie = QtGui.QMovie(fs_file)

        self._lbl_image.set_content(self._gif_movie)
        self._lay_media.setCurrentWidget(self._lbl_image)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_static_image(self, fs_file: str):
        """
        mostra uma imagem estática (PNG, JPG, ...).

        :param fs_file: caminho do arquivo de imagem (já verificado que existe)
        """
        self._lbl_image.set_content(QtGui.QPixmap(fs_file))
        self._lay_media.setCurrentWidget(self._lbl_image)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_modified_time(self, ff_modified_timestamp: float):
        """
        escreve no rodapé quando o arquivo foi atualizado pela última vez.

        :param ff_modified_timestamp: mtime do arquivo (segundos desde 1970)
        """
        ldt_modified = datetime.datetime.fromtimestamp(ff_modified_timestamp)
        self._lbl_caption.setText(f"Atualizado em {ldt_modified:%d/%m/%Y %H:%M:%S}")

# ─────────────────────────────────────────────────────────────────────────────────────
def _create_centered_label(fs_text: str, fs_object_name: str):
    """
    cria um QLabel centralizado. O objectName liga o label ao estilo QSS
    global (QLabel#Title e QLabel#Caption, em dashViewQt.CS_QSS_STYLE).

    :param fs_text: texto inicial
    :param fs_object_name: nome usado pelo seletor QSS
    :returns: QtWidgets.QLabel
    """
    l_label = QtWidgets.QLabel(fs_text)
    l_label.setObjectName(fs_object_name)
    l_label.setAlignment(QtCore.Qt.AlignCenter)

    return l_label

# ─────────────────────────────────────────────────────────────────────────────────────
def _find_existing_media_file(fs_file: str):
    """
    procura o arquivo de mídia em disco: primeiro o caminho exato, depois a
    mesma base com cada extensão de CT_FALLBACK_EXTENSIONS, nesta ordem.

    :param fs_file: caminho configurado (ex.: ".../slm_out.gif")
    :returns: o primeiro caminho que existe, ou None se nenhum existir
    """
    ls_base_name, _ = os.path.splitext(fs_file)

    llst_candidates = [fs_file]

    for ls_extension in CT_FALLBACK_EXTENSIONS:
        llst_candidates.append(ls_base_name + ls_extension)

    for ls_candidate in llst_candidates:
        if os.path.exists(ls_candidate):
            return ls_candidate

    return None

# < the end >──────────────────────────────────────────────────────────────────────────
