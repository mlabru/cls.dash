# -*- coding: utf-8 -*-
"""testes unitários para widgets/wid_image.py"""

from PyQt5 import QtCore, QtGui

import widgets.wid_image as wi


def test_update_image_noop_without_content(qapp):
    label = wi.CImageLabel()

    label.update_image()  # não deve lançar exceção

    assert label.pixmap() is None or label.pixmap().isNull()


def test_update_image_noop_when_size_is_empty(qapp):
    label = wi.CImageLabel()
    label.resize(0, 0)  # força size().isEmpty() == True

    pixmap = QtGui.QPixmap(200, 100)
    pixmap.fill(QtCore.Qt.red)

    label.set_content(pixmap)

    assert label.pixmap() is None or label.pixmap().isNull()


def test_set_content_pixmap_scales_to_label_size(qapp):
    label = wi.CImageLabel()
    label.resize(50, 40)

    pixmap = QtGui.QPixmap(200, 100)
    pixmap.fill(QtCore.Qt.red)

    label.set_content(pixmap)

    scaled = label.pixmap()
    assert scaled is not None
    assert not scaled.isNull()
    # KeepAspectRatio: nunca deve ultrapassar o tamanho do label
    assert scaled.width() <= 50
    assert scaled.height() <= 40


def test_set_content_pixmap_clears_previous_movie(qapp):
    label = wi.CImageLabel()
    label.resize(50, 40)

    movie = QtGui.QMovie()
    label.set_content(movie)
    assert label.movie() is movie

    pixmap = QtGui.QPixmap(20, 20)
    pixmap.fill(QtCore.Qt.blue)
    label.set_content(pixmap)

    assert label.movie() is None


def test_set_content_movie_is_dispatched_to_movie_branch(qapp):
    label = wi.CImageLabel()
    label.resize(60, 60)

    movie = QtGui.QMovie()  # não precisa de um arquivo GIF válido para testar o dispatch
    label.set_content(movie)

    assert label.movie() is movie
    assert label.pixmap() is None or label.pixmap().isNull()


# GIF animado real de 40x20 (2 frames), embutido para não depender do Pillow
_GIF_40X20_BASE64 = (
    "R0lGODlhKAAUAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwAAAAAKAAUAAAI"
    "MAABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFixgzatzIsaPHjyBDihxJsqTJkxQDAgAh+QQBCgABACwAAAAA"
    "KAAUAIEAAP8AAAAAAAAAAAAIMAABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFixgzatzIsaPHjyBDihxJsqTJ"
    "kxQDAgA7"
)


def _write_gif_40x20(tmp_path):
    import base64

    path = tmp_path / "anim.gif"
    path.write_bytes(base64.b64decode(_GIF_40X20_BASE64))
    return str(path)


def test_set_content_gif_keeps_aspect_ratio(qapp, tmp_path):
    label = wi.CImageLabel()
    label.resize(200, 200)

    movie = QtGui.QMovie(_write_gif_40x20(tmp_path))
    label.set_content(movie)

    # 40x20 (2:1) dentro de 200x200 -> 200x100, sem esticar para 200x200
    assert movie.scaledSize() == QtCore.QSize(200, 100)


def test_resized_label_rescales_gif_keeping_aspect_ratio(qapp, tmp_path):
    label = wi.CImageLabel()
    label.resize(200, 200)
    label.show()

    movie = QtGui.QMovie(_write_gif_40x20(tmp_path))
    label.set_content(movie)

    label.resize(100, 300)
    qapp.processEvents()  # entrega o resizeEvent

    assert movie.scaledSize() == QtCore.QSize(100, 50)
