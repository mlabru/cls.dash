# -*- coding: utf-8 -*-
"""testes unitários para apps/be/app.py"""

import json
import os
import time

import pytest

import app as be_app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def media_dir(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "img.png").write_bytes(b"fake-image-bytes")
    return media


@pytest.fixture
def config_path(tmp_path, media_dir):
    data = {
        "media_dir": str(media_dir),
        "refresh_seconds": 5,
        "pages": [
            {
                "name": "Página 1",
                "duration": 10,
                "tiles": [
                    {"type": "image", "file": "img.png", "title": "Tile 1"},
                ],
            },
        ],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def client(config_path, monkeypatch):
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(config_path))
    be_app.load_config()
    return be_app.app.test_client()


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

def test_validate_config_missing_required_keys():
    with pytest.raises(ValueError, match="Chaves obrigatórias ausentes"):
        be_app.validate_config({"pages": []})


def test_validate_config_empty_pages(media_dir):
    with pytest.raises(ValueError, match="'pages' deve ser uma lista"):
        be_app.validate_config({"media_dir": str(media_dir), "pages": []})


def test_validate_config_pages_not_a_list(media_dir):
    with pytest.raises(ValueError, match="'pages' deve ser uma lista"):
        be_app.validate_config({"media_dir": str(media_dir), "pages": "nope"})


def test_validate_config_missing_media_dir(tmp_path):
    with pytest.raises(ValueError, match="media_dir"):
        be_app.validate_config({
            "media_dir": str(tmp_path / "does-not-exist"),
            "pages": [{"name": "x", "duration": 1, "tiles": []}],
        })


@pytest.mark.parametrize("duration", [None, 0, -5, "15", True, float("nan")])
def test_validate_config_rejects_bad_duration(media_dir, duration):
    page = {"name": "x", "tiles": []}
    if duration is not None:
        page["duration"] = duration
    with pytest.raises(ValueError, match="'duration'"):
        be_app.validate_config({"media_dir": str(media_dir), "pages": [page]})


@pytest.mark.parametrize("tiles", [None, "a.png", [["t", "a.png"]]])
def test_validate_config_rejects_bad_tiles(media_dir, tiles):
    page = {"name": "x", "duration": 1}
    if tiles is not None:
        page["tiles"] = tiles
    with pytest.raises(ValueError, match="'tiles'"):
        be_app.validate_config({"media_dir": str(media_dir), "pages": [page]})


def test_validate_config_rejects_non_object_page(media_dir):
    with pytest.raises(ValueError, match="página inválida"):
        be_app.validate_config({"media_dir": str(media_dir), "pages": ["x"]})


def test_validate_config_accepts_valid_config(media_dir):
    be_app.validate_config({
        "media_dir": str(media_dir),
        "pages": [{"name": "x", "duration": 1, "tiles": []}],
    })  # não deve levantar exceção


# ---------------------------------------------------------------------------
# get_file_modified
# ---------------------------------------------------------------------------

def test_get_file_modified_existing_file(media_dir):
    result = be_app.get_file_modified(str(media_dir), "img.png")
    assert result is not None
    assert len(result.split()) == 2  # "dd/mm/aaaa hh:mm"


def test_get_file_modified_missing_file(media_dir):
    assert be_app.get_file_modified(str(media_dir), "nope.png") is None


# ---------------------------------------------------------------------------
# load_config / get_config_public
# ---------------------------------------------------------------------------

def test_load_config_raises_on_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(tmp_path / "missing.json"))

    with pytest.raises(FileNotFoundError):
        be_app.load_config()


def test_load_config_skips_reparsing_when_file_unchanged(config_path, monkeypatch):
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(config_path))
    be_app.load_config()

    calls = []
    original_validate = be_app.validate_config
    monkeypatch.setattr(
        be_app, "validate_config",
        lambda data: calls.append(1) or original_validate(data),
    )

    be_app.load_config()  # arquivo não mudou -> não deve reler nem revalidar

    assert calls == []


def test_load_config_reparses_after_file_is_modified(config_path, monkeypatch):
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(config_path))
    be_app.load_config()

    calls = []
    original_validate = be_app.validate_config
    monkeypatch.setattr(
        be_app, "validate_config",
        lambda data: calls.append(1) or original_validate(data),
    )

    # simula edição do arquivo (conteúdo novo + mtime adiantado)
    new_data = json.loads(config_path.read_text(encoding="utf-8"))
    new_data["refresh_seconds"] = 99
    config_path.write_text(json.dumps(new_data), encoding="utf-8")
    future = os.path.getmtime(config_path) + 5
    os.utime(config_path, (future, future))

    be_app.load_config()

    assert calls == [1]
    assert be_app.get_config_public()["refresh_seconds"] == 99


def test_get_config_public_hides_media_dir_and_adds_file_modified(client):
    data = be_app.get_config_public()

    assert "media_dir" not in data
    assert data["pages"][0]["tiles"][0]["file_modified"] is not None


def test_get_config_public_missing_media_file_has_none_modified(monkeypatch, tmp_path, media_dir):
    data = {
        "media_dir": str(media_dir),
        "pages": [
            {"name": "p", "duration": 1, "tiles": [{"type": "image", "file": "missing.png"}]},
        ],
    }
    path = tmp_path / "config2.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(path))
    be_app.load_config()

    result = be_app.get_config_public()
    assert result["pages"][0]["tiles"][0]["file_modified"] is None


# ---------------------------------------------------------------------------
# rotas HTTP
# ---------------------------------------------------------------------------

def test_health_route(client):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok",
                               "media": {"missing": [], "stale": []},
                               "nowcast_hidden": [],
                               "nowcast_unavailable": [],
                               "config_error": None}


def test_api_config_route_returns_pages(client):
    resp = client.get("/api/config")

    assert resp.status_code == 200

    body = resp.get_json()
    assert "media_dir" not in body
    assert body["pages"][0]["name"] == "Página 1"
    assert body["pages"][0]["tiles"][0]["file_modified"] is not None


def test_media_route_serves_existing_file(client):
    resp = client.get("/media/img.png")

    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"


def test_media_route_works_before_any_api_config_call(config_path, monkeypatch):
    # simula um worker novo do gunicorn: G_CONFIG ainda vazio, nunca carregado
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(be_app, "G_CONFIG_CACHE_KEY", None)
    be_app.G_CONFIG.clear()

    resp = be_app.app.test_client().get("/media/img.png")

    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"


def test_media_route_missing_file_returns_404(client):
    resp = client.get("/media/does-not-exist.png")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "não encontrado"}


def test_unknown_route_returns_404_json(client):
    resp = client.get("/nope")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "não encontrado"}


# ---------------------------------------------------------------------------
# nowcast (mosaicos do 25.oflow)
# ---------------------------------------------------------------------------

CLST_RADARS = [["BEL", "Belém"], ["BVA", "Boa Vista"], ["CGU", "Canguçu"],
               ["MDI", "Morro da Igreja"], ["PCO", "Pico do Couto"],
               ["SRO", "São Roque"], ["STI", "Santiago"]]


def _nowcast_entry(radars=None):
    return {"type": "nowcast", "name": "Nowcast", "duration": 20,
            "radars": radars if radars is not None else CLST_RADARS}


@pytest.fixture
def oflow_dir(tmp_path, monkeypatch):
    """saídas do oflow e do u-net com um mosaico recente para cada radar
    (devolve a do oflow; a do u-net é a fixture unet_dir)."""
    for source, prefix in (("oflw", b"GIF89a-"), ("unet", b"GIF89a-U-")):
        out = tmp_path / source / "output"
        out.mkdir(parents=True)

        for radar_id, _ in CLST_RADARS:
            (out / f"{radar_id}_400_now_mosaico.gif").write_bytes(prefix + radar_id.encode())

    monkeypatch.setattr(be_app, "CS_OFLOW_OUTPUT_DIR", str(tmp_path / "oflw" / "output"))
    monkeypatch.setattr(be_app, "CS_UNET_OUTPUT_DIR", str(tmp_path / "unet" / "output"))
    monkeypatch.setattr(be_app, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    return tmp_path / "oflw" / "output"


@pytest.fixture
def unet_dir(oflow_dir):
    return oflow_dir.parent.parent / "unet" / "output"


def _make_old(path, hours):
    old = os.path.getmtime(path) - hours * 3600
    os.utime(path, (old, old))


def test_nowcast_one_page_per_radar_with_oflow_and_unet_rows(oflow_dir):
    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert len(pages) == 7
    assert [p["name"] for p in pages][:2] == ["Nowcast (1/7)", "Nowcast (2/7)"]
    assert all(p["layout"] == "rows" and p["duration"] == 20 for p in pages)

    oflow_tile, unet_tile = pages[0]["tiles"]
    assert oflow_tile["type"] == "gif" and unet_tile["type"] == "gif"
    assert oflow_tile["file"] == "nowcast/oflow/BEL_400_now_mosaico.gif"
    assert unet_tile["file"] == "nowcast/unet/BEL_400_now_mosaico.gif"
    assert oflow_tile["title"] == "Belém (BEL) - Fluxo óptico"
    assert unet_tile["title"] == "Belém (BEL) - U-Net"
    assert oflow_tile["file_modified"] is not None


def test_nowcast_single_page_has_no_counter_in_name(oflow_dir):
    pages = be_app._expand_pages([_nowcast_entry(CLST_RADARS[:1])], time.time())

    assert [p["name"] for p in pages] == ["Nowcast"]


def test_nowcast_hides_radars_without_any_recent_mosaic(oflow_dir, unet_dir):
    (oflow_dir / "BEL_400_now_mosaico.gif").unlink()
    (unet_dir / "BEL_400_now_mosaico.gif").unlink()
    _make_old(oflow_dir / "CGU_400_now_mosaico.gif", hours=3)
    (unet_dir / "CGU_400_now_mosaico.gif").unlink()

    pages = be_app._expand_pages([_nowcast_entry()], time.time())
    titles = [t["title"] for p in pages for t in p["tiles"]]

    assert len(pages) == 5
    assert not any("BEL" in t or "CGU" in t for t in titles)


def test_nowcast_missing_or_stale_source_becomes_unavailable_row(oflow_dir, unet_dir):
    (unet_dir / "BEL_400_now_mosaico.gif").unlink()
    _make_old(oflow_dir / "BVA_400_now_mosaico.gif", hours=3)

    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert len(pages) == 7
    assert pages[0]["tiles"][0]["file"] == "nowcast/oflow/BEL_400_now_mosaico.gif"
    assert pages[0]["tiles"][1] == {"type": "image", "file": "_unavailable",
                                    "title": "Belém (BEL) - U-Net: sem atualização há mais de 2 h",
                                    "file_modified": None}
    assert pages[1]["tiles"][0]["file"] == "_unavailable"
    assert pages[1]["tiles"][1]["file"] == "nowcast/unet/BVA_400_now_mosaico.gif"
    assert not any("notice" in p for p in pages)


def test_nowcast_only_uses_400_km_mosaics(oflow_dir, unet_dir):
    for out in (oflow_dir, unet_dir):
        for radar_id, _ in CLST_RADARS:
            (out / f"{radar_id}_400_now_mosaico.gif").rename(
                out / f"{radar_id}_250_now_mosaico.gif")

    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert pages[0]["tiles"][0]["file"] == "_unavailable"


def test_nowcast_all_hidden_yields_single_unavailable_page(oflow_dir, unet_dir):
    for out in (oflow_dir, unet_dir):
        for gif in out.iterdir():
            gif.unlink()

    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert len(pages) == 1
    assert pages[0]["name"] == "Nowcast"
    assert pages[0]["tiles"] == [{"type": "image", "file": "_unavailable",
                                  "title": be_app.CS_NO_RADAR_TITLE, "file_modified": None}]


def test_nowcast_expansion_keeps_other_pages_in_order(oflow_dir):
    other = {"name": "x", "duration": 1, "tiles": []}

    pages = be_app._expand_pages([other, _nowcast_entry(CLST_RADARS[:1]), other], time.time())

    assert pages[0] is other and pages[2] is other
    assert pages[1]["tiles"][0]["title"] == "Belém (BEL) - Fluxo óptico"


def test_validate_config_rejects_invalid_nowcast_entry(media_dir):
    for entry in ({"type": "nowcast", "name": "n", "duration": 1, "radars": []},
                  {"type": "nowcast", "name": "n", "duration": 1, "radars": [["BEL"]]},
                  {"type": "nowcast", "name": "n", "radars": [["BEL", "Belém"]]}):
        with pytest.raises(ValueError, match="nowcast"):
            be_app.validate_config({"media_dir": str(media_dir), "pages": [entry]})


@pytest.fixture
def nowcast_client(tmp_path, media_dir, oflow_dir, monkeypatch):
    data = {"media_dir": str(media_dir),
            "pages": [{"name": "p", "duration": 1, "tiles": [{"type": "image", "file": "img.png"}]},
                      _nowcast_entry()]}
    path = tmp_path / "config_nowcast.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    no_cast = tmp_path / "no_cast.png"
    no_cast.write_bytes(b"no-cast-png")
    monkeypatch.setattr(be_app, "CS_NO_CAST_IMAGE", str(no_cast))

    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(path))
    be_app.load_config()
    return be_app.app.test_client()


def test_api_config_expands_nowcast_pages(nowcast_client):
    body = nowcast_client.get("/api/config").get_json()

    assert len(body["pages"]) == 8
    assert body["pages"][0]["tiles"][0]["file_modified"] is not None
    assert body["pages"][1]["tiles"][0]["file"] == "nowcast/oflow/BEL_400_now_mosaico.gif"
    assert body["pages"][1]["tiles"][1]["file"] == "nowcast/unet/BEL_400_now_mosaico.gif"


def test_api_config_does_not_mutate_stored_config(nowcast_client):
    nowcast_client.get("/api/config")

    assert be_app.G_CONFIG["pages"][1]["type"] == "nowcast"


def test_media_nowcast_route_serves_mosaic_of_each_source(nowcast_client):
    resp = nowcast_client.get("/media/nowcast/oflow/CGU_400_now_mosaico.gif")
    assert resp.status_code == 200
    assert resp.data == b"GIF89a-CGU"

    resp = nowcast_client.get("/media/nowcast/unet/CGU_400_now_mosaico.gif")
    assert resp.status_code == 200
    assert resp.data == b"GIF89a-U-CGU"


def test_media_nowcast_route_rejects_unknown_source(nowcast_client):
    assert nowcast_client.get("/media/nowcast/xxx/CGU_400_now_mosaico.gif").status_code == 404


def test_media_nowcast_route_rejects_non_mosaic_names(nowcast_client, oflow_dir):
    (oflow_dir / "CGU_400_verify.jsonl").write_text("{}")

    for name in ("CGU_400_verify.jsonl", "CGU_400_now_opencv.gif", "..%2Fsecret.gif"):
        assert nowcast_client.get(f"/media/nowcast/oflow/{name}").status_code == 404


def test_media_nowcast_route_missing_mosaic_returns_404(nowcast_client, oflow_dir):
    (oflow_dir / "STI_400_now_mosaico.gif").unlink()

    assert nowcast_client.get("/media/nowcast/oflow/STI_400_now_mosaico.gif").status_code == 404


def test_media_unavailable_route(nowcast_client, monkeypatch, tmp_path):
    resp = nowcast_client.get("/media/_unavailable")
    assert resp.status_code == 200
    assert resp.data == b"no-cast-png"

    monkeypatch.setattr(be_app, "CS_NO_CAST_IMAGE", str(tmp_path / "missing.png"))
    assert nowcast_client.get("/media/_unavailable").status_code == 404


def test_media_route_still_serves_media_dir_files(nowcast_client):
    assert nowcast_client.get("/media/img.png").data == b"fake-image-bytes"


# ---------------------------------------------------------------------------
# aviso dos ocultos, file_version, /health, /api/state
# ---------------------------------------------------------------------------

def test_nowcast_pages_carry_notice_of_hidden_radars(oflow_dir, unet_dir):
    for out in (oflow_dir, unet_dir):
        (out / "SRO_400_now_mosaico.gif").unlink()
        _make_old(out / "STI_400_now_mosaico.gif", hours=3)

    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert all(p["notice"] == "Sem atualização há mais de 2 h: São Roque (SRO), Santiago (STI)"
               for p in pages)


def test_nowcast_pages_without_hidden_radars_have_no_notice(oflow_dir):
    pages = be_app._expand_pages([_nowcast_entry()], time.time())

    assert not any("notice" in p for p in pages)


def test_all_hidden_page_also_carries_notice(oflow_dir, unet_dir):
    for out in (oflow_dir, unet_dir):
        for gif in out.iterdir():
            gif.unlink()

    pages = be_app._expand_pages([_nowcast_entry(CLST_RADARS[:1])], time.time())

    assert pages[0]["notice"] == "Sem atualização há mais de 2 h: Belém (BEL)"


def test_file_version_is_integer_mtime(client, media_dir):
    tile = be_app.get_config_public()["pages"][0]["tiles"][0]

    assert tile["file_version"] == int(os.path.getmtime(media_dir / "img.png"))


def test_file_version_absent_for_missing_file(monkeypatch, tmp_path, media_dir):
    data = {"media_dir": str(media_dir),
            "pages": [{"name": "p", "duration": 1, "tiles": [{"type": "image", "file": "x.png"}]}]}
    path = tmp_path / "config3.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(path))
    be_app.load_config()

    assert "file_version" not in be_app.get_config_public()["pages"][0]["tiles"][0]


def test_nowcast_tiles_have_file_version(oflow_dir):
    tile = be_app._expand_pages([_nowcast_entry()], time.time())[0]["tiles"][0]

    assert tile["file_version"] == int(os.path.getmtime(oflow_dir / "BEL_400_now_mosaico.gif"))


def test_health_degraded_lists_missing_stale_and_hidden(nowcast_client, media_dir, oflow_dir,
                                                        unet_dir, monkeypatch):
    monkeypatch.setattr(be_app, "CI_MEDIA_MAX_AGE_HOURS", 2)
    _make_old(media_dir / "img.png", hours=3)
    (oflow_dir / "STI_400_now_mosaico.gif").unlink()
    (unet_dir / "STI_400_now_mosaico.gif").unlink()
    (unet_dir / "BEL_400_now_mosaico.gif").unlink()

    resp = nowcast_client.get("/health")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["media"] == {"missing": [], "stale": ["img.png"]}
    assert body["nowcast_hidden"] == ["STI"]
    assert body["nowcast_unavailable"] == ["BEL/unet"]


def test_health_ok_with_all_mosaics_recent(nowcast_client):
    body = nowcast_client.get("/health").get_json()

    assert body["nowcast_hidden"] == [] and body["nowcast_unavailable"] == []


def test_health_reports_missing_media_once(monkeypatch, tmp_path, media_dir):
    tile = {"type": "image", "file": "gone.png"}
    data = {"media_dir": str(media_dir),
            "pages": [{"name": "a", "duration": 1, "tiles": [tile]},
                      {"name": "b", "duration": 1, "tiles": [tile]}]}
    path = tmp_path / "config4.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(path))

    body = be_app._collect_product_health(time.time())

    assert body["status"] == "degraded"
    assert body["media"]["missing"] == ["gone.png"]


def test_health_with_broken_config_is_200_and_degraded(monkeypatch, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(be_app, "CS_CONFIG_FILE", str(path))

    resp = be_app.app.test_client().get("/health")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["config_error"]


def test_api_state_reflects_alert_file(client, monkeypatch, tmp_path):
    trigger = tmp_path / "ALERTA_ATIVO.txt"
    monkeypatch.setattr(be_app, "CS_ALERT_TRIGGER", str(trigger))

    assert client.get("/api/state").get_json() == {"alert": False}

    trigger.write_text("ALERTA")
    assert client.get("/api/state").get_json() == {"alert": True}
