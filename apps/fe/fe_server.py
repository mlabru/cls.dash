# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

fe_server
servidor estático do frontend (apps/fe): o http.server do Python com
"Cache-Control: no-cache" em toda resposta.

sem esse cabeçalho o navegador reusa o app.js/style.css que já tem em cache
(cache heurístico) e, depois de um deploy, a tela roda o JS velho até alguém
limpar o cache; antes isso era contornado com um "?v=<data>" no index.html,
trocado à mão a cada mudança (e esquecido). Com "no-cache" o navegador
pergunta toda vez: o http.server responde 304 (If-Modified-Since) se o
arquivo não mudou, então custa uma requisição pequena, não o download.

uso (o dash_web.sh faz isso):
    python3 fe_server.py [porta] [endereço]   # padrão 8080, todas as interfaces

serve o diretório deste arquivo, de onde quer que seja chamado.

2026.nov  mlabru  initial version: substitui "python3 -m http.server" e o
                  "?v=" manual do index.html
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import functools
import http.server
import os
import sys

# < constants >────────────────────────────────────────────────────────────────────────

# diretório servido (apps/fe)
CS_FE_DIR = os.path.dirname(os.path.abspath(__file__))

CI_DEFAULT_PORT = 8080

# vazio = todas as interfaces (como o http.server)
CS_DEFAULT_BIND = ""

# ─────────────────────────────────────────────────────────────────────────────────────
class CNoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler que manda o navegador revalidar sempre"""

    def end_headers(self):
        # "no-cache" não é "não guarde": guarda, mas confirma com o servidor
        # (304 se não mudou) antes de usar
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

# ─────────────────────────────────────────────────────────────────────────────────────
def make_server(fs_bind: str, fi_port: int) -> http.server.ThreadingHTTPServer:
    """
    :param fs_bind: endereço ("" = todas as interfaces)
    :param fi_port: porta (0 = qualquer livre, nos testes)
    :returns: servidor (ainda não atendendo) que serve CS_FE_DIR
    """
    l_handler = functools.partial(CNoCacheHandler, directory=CS_FE_DIR)

    return http.server.ThreadingHTTPServer((fs_bind, fi_port), l_handler)

# ─────────────────────────────────────────────────────────────────────────────────────
def main(flst_args: list) -> None:
    """
    :param flst_args: [porta] [endereço]
    """
    li_port = int(flst_args[0]) if flst_args else CI_DEFAULT_PORT
    ls_bind = flst_args[1] if len(flst_args) > 1 else CS_DEFAULT_BIND

    l_server = make_server(ls_bind, li_port)

    print(f"frontend em http://{ls_bind or '0.0.0.0'}:{li_port}/ ({CS_FE_DIR})", flush=True)

    try:
        l_server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        l_server.server_close()

# ─────────────────────────────────────────────────────────────────────────────────────
if "__main__" == __name__:
    main(sys.argv[1:])

# < the end >──────────────────────────────────────────────────────────────────────────
