# -*- coding: utf-8 -*-
"""testes de apps/fe/fe_server.py: servidor estático do frontend que manda o
navegador revalidar (no lugar do "?v=" manual no index.html)"""

import email.utils
import importlib.util
import os
import threading
import urllib.error
import urllib.request

import pytest

CS_FE_SERVER = os.path.join(os.path.dirname(__file__), "..", "apps", "fe", "fe_server.py")


def _load_fe_server():
    # apps/fe não é pacote (tem node_modules, test/ do node...): carrega pelo caminho
    spec = importlib.util.spec_from_file_location("fe_server", CS_FE_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def base_url():
    fe_server = _load_fe_server()
    server = fe_server.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{server.server_address[1]}"

    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("path", ["/", "/index.html", "/app.js", "/style.css"])
def test_every_response_says_no_cache(base_url, path):
    with urllib.request.urlopen(base_url + path) as response:
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["Last-Modified"]


def test_unchanged_file_is_revalidated_with_304(base_url):
    with urllib.request.urlopen(base_url + "/app.js") as response:
        last_modified = response.headers["Last-Modified"]

    request = urllib.request.Request(base_url + "/app.js",
                                     headers={"If-Modified-Since": last_modified})

    with pytest.raises(urllib.error.HTTPError) as error:  # urllib trata 304 como erro
        urllib.request.urlopen(request)

    assert error.value.code == 304
    assert error.value.headers["Cache-Control"] == "no-cache"


def test_changed_file_is_sent_again(base_url):
    old = email.utils.formatdate(0, usegmt=True)  # 1970: o arquivo é mais novo
    request = urllib.request.Request(base_url + "/app.js", headers={"If-Modified-Since": old})

    with urllib.request.urlopen(request) as response:
        assert response.status == 200


def test_index_html_has_no_manual_version():
    with open(os.path.join(os.path.dirname(CS_FE_SERVER), "index.html"), encoding="utf-8") as f:
        html = f.read()

    assert 'src="app.js"' in html and 'href="style.css"' in html
    assert "?v=" not in html.replace('sem "?v="', "")
