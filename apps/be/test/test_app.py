# -*- coding: utf-8 -*-
"""testes unitários para apps/be/app.py

a leitura/validação do config.json e a regra de nowcast são do dshcore e têm
testes próprios (test/test_dsc_config.py, test/test_dsc_nowcast.py); aqui
fica o que é do web: o formato enviado ao frontend e as rotas.
"""

import json
import os
import time

import pytest

import app as be_app
from dshcore import dsc_config as dc
from dshcore import dsc_env as de
from dshcore import dsc_nowcast as dn


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

CLST_RADARS = [["BEL", "Belém"], ["BVA", "Boa Vista"], ["CGU", "Canguçu"],
               ["MDI", "Morro da Igreja"], ["PCO", "Pico do Couto"],
               ["SRO", "São Roque"], ["STI", "Santiago"]]


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch, tmp_path):
    # cada teste começa como um worker novo: cache vazio; e o estado dos
    # radares ocultos fora do data/run real (o backend em execução usa ele)
    monkeypatch.setattr(be_app, "G_CONFIG_CACHE", dc.CConfigCache())
    monkeypatch.setattr(dn, "G_HIDDEN_STATE_FILE", str(tmp_path / "hidden.state"))
    monkeypatch.setattr(dn, "G_HIDDEN_RADARS", set())
    monkeypatch.setattr(dn, "G_HIDDEN_STATE_TOKEN", "teste")


@pytest.fixture
def media_dir(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "img.png").write_bytes(b"fake-image-bytes")
    return media


def _write_config(tmp_path, monkeypatch, pages, roots, name="config.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"refresh_seconds": 5, "roots": roots, "pages": pages}),
                    encoding="utf-8")
    monkeypatch.setattr(de, "CS_CONFIG_FILE", str(path))
    return path


def _page(name="Página 1", files=("img.png",)):
    return {"name": name, "duration": 10,
            "tiles": [{"type": "image", "root": "m", "file": f, "title": "Tile 1"} for f in files]}


@pytest.fixture
def config_path(tmp_path, media_dir, monkeypatch):
    return _write_config(tmp_path, monkeypatch, [_page()], {"m": str(media_dir)})


@pytest.fixture
def client(config_path):
    return be_app.app.test_client()


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

    monkeypatch.setattr(de, "CS_OFLOW_DATA", str(tmp_path / "oflw"))
    monkeypatch.setattr(de, "CS_UNET_DATA", str(tmp_path / "unet"))
    monkeypatch.setattr(de, "CI_NOWCAST_MAX_AGE_HOURS", 2)
    return tmp_path / "oflw" / "output"


@pytest.fixture
def unet_dir(oflow_dir):
    return oflow_dir.parent.parent / "unet" / "output"


def _make_old(path, hours):
    old = os.path.getmtime(path) - hours * 3600
    os.utime(path, (old, old))


def _expand(pages, roots=None):
    return be_app._expand_pages({"roots": roots or {}, "pages": pages}, time.time())


# ---------------------------------------------------------------------------
# load_config / get_config_public
# ---------------------------------------------------------------------------

def test_load_config_raises_on_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "CS_CONFIG_FILE", str(tmp_path / "missing.json"))

    with pytest.raises(FileNotFoundError):
        be_app.load_config()


def test_load_config_picks_up_edited_file(config_path):
    be_app.load_config()

    new_data = json.loads(config_path.read_text(encoding="utf-8"))
    new_data["refresh_seconds"] = 99
    config_path.write_text(json.dumps(new_data), encoding="utf-8")
    future = os.path.getmtime(config_path) + 5
    os.utime(config_path, (future, future))

    assert be_app.get_config_public(be_app.load_config())["refresh_seconds"] == 99


def test_get_config_public_hides_roots_and_prefixes_file_with_root(client):
    data = be_app.get_config_public(be_app.load_config())

    assert "roots" not in data
    tile = data["pages"][0]["tiles"][0]
    assert tile["file"] == "m/img.png"
    assert "root" not in tile
    assert tile["file_modified"] is not None


def test_get_config_public_missing_media_file_has_none_modified(tmp_path, media_dir, monkeypatch):
    _write_config(tmp_path, monkeypatch, [_page(files=("missing.png",))], {"m": str(media_dir)})

    tile = be_app.get_config_public(be_app.load_config())["pages"][0]["tiles"][0]

    assert tile["file_modified"] is None
    assert "file_version" not in tile


def test_file_version_is_integer_mtime(client, media_dir):
    tile = be_app.get_config_public(be_app.load_config())["pages"][0]["tiles"][0]

    assert tile["file_version"] == int(os.path.getmtime(media_dir / "img.png"))


def test_get_config_public_does_not_mutate_cached_config(client):
    be_app.get_config_public(be_app.load_config())

    assert be_app.load_config()["pages"][0]["tiles"][0] == {"type": "image", "root": "m",
                                                            "file": "img.png", "title": "Tile 1"}


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
    assert "roots" not in body
    assert body["pages"][0]["name"] == "Página 1"
    assert body["pages"][0]["tiles"][0]["file_modified"] is not None


def test_media_route_serves_file_of_root(client):
    resp = client.get("/media/m/img.png")

    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"


def test_media_route_works_before_any_api_config_call(config_path):
    # worker novo do gunicorn: o cache ainda está vazio (fixture fresh_cache)
    resp = be_app.app.test_client().get("/media/m/img.png")

    assert resp.status_code == 200


def test_media_route_unknown_root_or_missing_file_returns_404(client):
    for url in ("/media/m/does-not-exist.png", "/media/xx/img.png", "/media/img.png"):
        resp = client.get(url)
        assert resp.status_code == 404, url
        assert resp.get_json() == {"error": "não encontrado"}


def test_media_route_blocks_path_traversal(client, tmp_path):
    (tmp_path / "secret.txt").write_text("x")

    assert client.get("/media/m/../secret.txt").status_code == 404
    assert client.get("/media/m/..%2Fsecret.txt").status_code == 404


def test_unknown_route_returns_404_json(client):
    resp = client.get("/nope")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "não encontrado"}


def test_api_state_reflects_alert_file(client, monkeypatch, tmp_path):
    trigger = tmp_path / "ALERTA_ATIVO.txt"
    monkeypatch.setattr(de, "CS_ALERT_TRIGGER", str(trigger))

    assert client.get("/api/state").get_json() == {"alert": False}

    trigger.write_text("ALERTA")
    assert client.get("/api/state").get_json() == {"alert": True}


# ---------------------------------------------------------------------------
# nowcast: formato do web (a regra é testada em test/test_dsc_nowcast.py)
# ---------------------------------------------------------------------------

def test_nowcast_tiles_are_gif_urls_with_file_info(oflow_dir):
    pages = _expand([_nowcast_entry()])

    assert len(pages) == 7
    oflow_tile, unet_tile = pages[0]["tiles"]
    assert oflow_tile["type"] == "gif" and unet_tile["type"] == "gif"
    assert oflow_tile["file"] == "nowcast/oflow/BEL_400_now_mosaico.gif"
    assert unet_tile["file"] == "nowcast/unet/BEL_400_now_mosaico.gif"
    assert oflow_tile["title"] == "Belém (BEL) - Fluxo óptico"
    assert oflow_tile["file_version"] == int(os.path.getmtime(oflow_dir / "BEL_400_now_mosaico.gif"))


def test_nowcast_unavailable_row_uses_unavailable_media(oflow_dir, unet_dir):
    (unet_dir / "BEL_400_now_mosaico.gif").unlink()

    pages = _expand([_nowcast_entry()])

    assert pages[0]["tiles"][1] == {"type": "image", "file": "_unavailable",
                                    "title": "Belém (BEL) - U-Net: sem atualização há mais de 2 h",
                                    "file_modified": None}


def test_nowcast_all_hidden_yields_single_unavailable_page(oflow_dir, unet_dir):
    for out in (oflow_dir, unet_dir):
        for gif in out.iterdir():
            gif.unlink()

    pages = _expand([_nowcast_entry(CLST_RADARS[:1])])

    assert len(pages) == 1
    assert "layout" not in pages[0]
    assert pages[0]["tiles"] == [{"type": "image", "file": "_unavailable",
                                  "title": "Nenhum radar com nowcast recente",
                                  "file_modified": None}]
    assert pages[0]["notice"] == "Sem atualização há mais de 2 h: Belém (BEL)"


def test_nowcast_pages_without_hidden_radars_have_no_notice_key(oflow_dir):
    assert not any("notice" in p for p in _expand([_nowcast_entry()]))


def test_expansion_keeps_regular_pages_in_order(oflow_dir, media_dir):
    pages = _expand([_page("a"), _nowcast_entry(CLST_RADARS[:1]), _page("b")],
                    {"m": str(media_dir)})

    assert [p["name"] for p in pages] == ["a", "Nowcast", "b"]
    assert pages[0]["tiles"][0]["file"] == "m/img.png"


@pytest.fixture
def nowcast_client(tmp_path, media_dir, oflow_dir, monkeypatch):
    _write_config(tmp_path, monkeypatch, [_page("p"), _nowcast_entry()], {"m": str(media_dir)},
                  name="config_nowcast.json")

    no_cast = tmp_path / "no_cast.png"
    no_cast.write_bytes(b"no-cast-png")
    monkeypatch.setattr(de, "CS_NO_CAST_IMAGE", str(no_cast))

    return be_app.app.test_client()


def test_api_config_expands_nowcast_pages(nowcast_client):
    body = nowcast_client.get("/api/config").get_json()

    assert len(body["pages"]) == 8
    assert body["pages"][1]["tiles"][0]["file"] == "nowcast/oflow/BEL_400_now_mosaico.gif"
    assert body["pages"][1]["tiles"][1]["file"] == "nowcast/unet/BEL_400_now_mosaico.gif"


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

    monkeypatch.setattr(de, "CS_NO_CAST_IMAGE", str(tmp_path / "missing.png"))
    assert nowcast_client.get("/media/_unavailable").status_code == 404


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

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
    assert body["media"] == {"missing": [], "stale": ["m/img.png"]}
    assert body["nowcast_hidden"] == ["STI"]
    assert body["nowcast_unavailable"] == ["BEL/unet"]


def test_health_ok_with_all_mosaics_recent(nowcast_client):
    body = nowcast_client.get("/health").get_json()

    assert body["nowcast_hidden"] == [] and body["nowcast_unavailable"] == []


def test_health_reports_missing_media_once(tmp_path, media_dir, monkeypatch):
    _write_config(tmp_path, monkeypatch, [_page("a", ("gone.png",)), _page("b", ("gone.png",))],
                  {"m": str(media_dir)})

    body = be_app._collect_product_health(time.time())

    assert body["status"] == "degraded"
    assert body["media"]["missing"] == ["m/gone.png"]


def test_health_with_broken_config_is_200_and_degraded(monkeypatch, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(de, "CS_CONFIG_FILE", str(path))

    resp = be_app.app.test_client().get("/health")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["config_error"]


# ---------------------------------------------------------------------------
# caminhos e a config real
# ---------------------------------------------------------------------------

def test_default_config_file_is_relative_to_app_dir():
    assert os.path.isabs(de.CS_CONFIG_FILE)
    assert os.path.dirname(de.CS_CONFIG_FILE) == be_app.CS_APP_DIR


def test_real_config_json_is_valid():
    # a config que os dois dashboards usam (as raízes podem não existir aqui)
    config = dc.read_config(os.path.join(be_app.CS_APP_DIR, "config.json"))

    assert set(config["roots"]) == {"mrad", "blitz", "goes"}
    assert all(os.path.isabs(d) for d in config["roots"].values())


# ---------------------------------------------------------------------------
# estado dos radares ocultos comum aos workers
# ---------------------------------------------------------------------------

def test_import_points_hidden_state_at_data_run_with_parent_pid(monkeypatch, tmp_path):
    state = tmp_path / "run" / "nowcast_hidden.state"
    monkeypatch.setattr(be_app, "CS_HIDDEN_STATE_FILE", str(state))

    be_app._share_hidden_radars_state()

    assert dn.G_HIDDEN_STATE_FILE == str(state)
    assert dn.G_HIDDEN_STATE_TOKEN == str(os.getppid())
    assert state.parent.is_dir()


def test_hidden_state_file_default_is_under_repo_data_run():
    assert be_app.CS_HIDDEN_STATE_FILE.endswith(os.path.join("data", "run", "nowcast_hidden.state"))
