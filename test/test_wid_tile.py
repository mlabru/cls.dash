# -*- coding: utf-8 -*-
"""testes unitários para widgets/wid_tile.py"""

import pytest

import widgets.wid_tile as wt


@pytest.fixture(autouse=True)
def _no_unavailable_image(monkeypatch):
    # G_UNAVAILABLE_PIXMAP é global do módulo: cada teste começa sem imagem
    monkeypatch.setattr(wt, "G_UNAVAILABLE_PIXMAP", None)


def _touch(path, content=b"data"):
    with open(path, "wb") as fh:
        fh.write(content)
    return str(path)


# GIF 1x1 válido: os tiles agora recusam mídia que não decodifica
CB_GIF_1X1 = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
              b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
              b"\x00\x02\x02D\x01\x00;")


@pytest.fixture(autouse=True)
def _fresh_invalid_log(monkeypatch):
    monkeypatch.setattr(wt, "G_INVALID_LOGGED", {})


# ---------------------------------------------------------------------------
# _find_existing_media_file
# ---------------------------------------------------------------------------

def test_find_existing_media_file_returns_exact_match_when_it_exists(tmp_path):
    png = tmp_path / "img.png"
    _touch(png)

    assert wt._find_existing_media_file(str(png)) == str(png)


def test_find_existing_media_file_tries_alternate_extensions(tmp_path):
    # pede um .mp4 que não existe, mas o .gif "irmão" existe
    gif = tmp_path / "clip.gif"
    _touch(gif)

    result = wt._find_existing_media_file(str(tmp_path / "clip.mp4"))

    assert result == str(gif)


def test_find_existing_media_file_prefers_mp4_over_gif_and_png(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    gif = tmp_path / "clip.gif"
    _touch(mp4)
    _touch(gif)

    result = wt._find_existing_media_file(str(tmp_path / "clip.anything"))

    assert result == str(mp4)


def test_find_existing_media_file_returns_none_when_nothing_matches(tmp_path):
    assert wt._find_existing_media_file(str(tmp_path / "missing.png")) is None


# ---------------------------------------------------------------------------
# update_content
# ---------------------------------------------------------------------------

def test_update_content_missing_file_shows_placeholder(qapp, tmp_path):
    tile = wt.CTileWidget()
    tile.update_content("Título", str(tmp_path / "missing.png"))

    assert tile._lbl_title.text() == "Título"
    assert tile._lbl_image.text() == "❌ Produto indisponível"


def test_update_content_file_vanishing_before_getmtime_shows_placeholder(qapp, tmp_path, monkeypatch):
    # simula o pipeline apagando o arquivo entre o exists() e o getmtime()
    png = tmp_path / "img.png"
    _touch(png)

    def _vanished(_path):
        raise FileNotFoundError(_path)

    monkeypatch.setattr(wt.os.path, "getmtime", _vanished)

    tile = wt.CTileWidget()
    tile.update_content("Radar", str(png))

    assert tile._lbl_image.text() == "❌ Produto indisponível"


def test_update_content_static_image_sets_title_and_caption(qapp, tmp_path):
    png = tmp_path / "img.png"
    _write_png(png)

    tile = wt.CTileWidget()
    tile.update_content("Radar", str(png))

    assert tile._lbl_title.text() == "Radar"
    assert "Atualizado em" in tile._lbl_caption.text()
    assert tile._lay_media.currentWidget() is tile._lbl_image


def test_update_content_video_switches_stack_to_video_widget(qapp, tmp_path):
    mp4 = tmp_path / "clip.mp4"
    _touch(mp4)

    tile = wt.CTileWidget()
    tile.update_content("GOES", str(mp4))

    assert tile._lay_media.currentWidget() is tile._wid_video


def test_update_content_stops_previous_media_before_showing_new_one(qapp, tmp_path):
    mp4 = tmp_path / "clip.mp4"
    png = tmp_path / "img.png"
    _touch(mp4)
    _write_png(png)

    tile = wt.CTileWidget()
    tile.update_content("GOES", str(mp4))
    assert tile._video_player is not None

    tile.update_content("Radar", str(png))

    assert tile._video_player is None
    assert tile._lay_media.currentWidget() is tile._lbl_image


def test_stop_playback_releases_gif_and_video(qapp, tmp_path):
    gif = tmp_path / "anim.gif"
    _touch(gif, CB_GIF_1X1)

    tile = wt.CTileWidget()
    tile.update_content("Raios", str(gif))
    assert tile._gif_movie is not None

    tile.stop_playback()

    assert tile._gif_movie is None
    assert tile._video_player is None


# ---------------------------------------------------------------------------
# imagem de indisponível (set_unavailable_image)
# ---------------------------------------------------------------------------

def _write_png(path):
    from PyQt5 import QtGui
    image = QtGui.QImage(8, 6, QtGui.QImage.Format_RGB32)
    image.fill(0)
    assert image.save(str(path), "PNG")
    return str(path)


def test_missing_file_shows_unavailable_image_when_configured(qapp, tmp_path):
    wt.set_unavailable_image(_write_png(tmp_path / "no_cast.png"))

    tile = wt.CTileWidget()
    tile.update_content("Radar", str(tmp_path / "missing.gif"))

    assert tile._lbl_image._content is wt.G_UNAVAILABLE_PIXMAP
    assert tile._lbl_caption.text() == wt.CS_NOT_FOUND_CAPTION


def test_set_unavailable_image_with_missing_file_falls_back_to_text(qapp, tmp_path):
    wt.set_unavailable_image(str(tmp_path / "nope.png"))
    assert wt.G_UNAVAILABLE_PIXMAP is None

    tile = wt.CTileWidget()
    tile.update_content("Radar", str(tmp_path / "missing.gif"))

    assert tile._lbl_image.text() == wt.CS_UNAVAILABLE_TEXT


# ---------------------------------------------------------------------------
# arquivo que existe mas não decodifica (vazio, corrompido)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, content", [("vazio.png", b""), ("lixo.png", b"nao e png"),
                                           ("vazio.gif", b""), ("lixo.gif", b"GIF89a truncado")])
def test_invalid_image_or_gif_shows_unavailable_image(qapp, tmp_path, name, content):
    wt.set_unavailable_image(_write_png(tmp_path / "no_cast.png"))

    tile = wt.CTileWidget()
    tile.update_content("Radar", _touch(tmp_path / name, content))

    assert tile._lbl_image._content is wt.G_UNAVAILABLE_PIXMAP
    assert tile._lbl_caption.text() == wt.CS_INVALID_CAPTION
    assert tile._gif_movie is None
    assert tile._lay_media.currentWidget() is tile._lbl_image


def test_invalid_image_without_unavailable_image_shows_text(qapp, tmp_path):
    tile = wt.CTileWidget()
    tile.update_content("Radar", _touch(tmp_path / "vazio.png", b""))

    assert tile._lbl_image.text() == wt.CS_UNAVAILABLE_TEXT
    assert tile._lbl_caption.text() == wt.CS_INVALID_CAPTION


def test_invalid_file_is_logged_once_per_version(qapp, tmp_path, caplog):
    import os
    png = _touch(tmp_path / "vazio.png", b"")
    tile = wt.CTileWidget()

    with caplog.at_level("WARNING", logger=wt.__name__):
        tile.update_content("Radar", png)
        tile.update_content("Radar", png)  # a página voltou na rotação

        future = os.path.getmtime(png) + 5
        os.utime(png, (future, future))   # o pipeline regravou, ainda vazio
        tile.update_content("Radar", png)

    assert [r.getMessage() for r in caplog.records] == [
        f"mídia inválida ou vazia (0 bytes), mostrando indisponível: {png}"] * 2


def test_valid_png_after_invalid_shows_image_and_date(qapp, tmp_path):
    png = tmp_path / "img.png"
    tile = wt.CTileWidget()

    tile.update_content("Radar", _touch(png, b""))
    tile.update_content("Radar", _write_png(png))

    assert isinstance(tile._lbl_image._content, wt.QtGui.QPixmap)
    assert not tile._lbl_image._content.isNull()
    assert "Atualizado em" in tile._lbl_caption.text()


def test_invalid_video_switches_to_unavailable_after_the_signal(qapp, tmp_path):
    from PyQt5 import QtMultimedia
    tile = wt.CTileWidget()
    tile.update_content("GOES", _touch(tmp_path / "vazio.mp4", b""))
    assert tile._lay_media.currentWidget() is tile._wid_video

    tile._on_video_media_status(QtMultimedia.QMediaPlayer.InvalidMedia)
    assert tile._video_player is not None  # ainda dentro do "slot": nada descartado

    qapp.processEvents()

    assert tile._video_player is None
    assert tile._lay_media.currentWidget() is tile._lbl_image
    assert tile._lbl_caption.text() == wt.CS_INVALID_CAPTION


def test_invalid_video_status_after_page_change_is_ignored(qapp, tmp_path):
    from PyQt5 import QtMultimedia
    tile = wt.CTileWidget()
    tile.update_content("GOES", _touch(tmp_path / "vazio.mp4", b""))

    tile._on_video_media_status(QtMultimedia.QMediaPlayer.InvalidMedia)
    tile.update_content("Radar", _write_png(tmp_path / "img.png"))  # trocou antes do timer
    qapp.processEvents()

    assert "Atualizado em" in tile._lbl_caption.text()
