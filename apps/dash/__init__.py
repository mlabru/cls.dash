# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dash
módulos do dashboard desktop (janela da TV, control pad, servidor UDP e
configuração), importados como dash.dsh_xxx.

por que este arquivo existe (vazio): ao contrário de widgets/ e dos pacotes
do 27.nowcast, este diretório precisa ser um pacote "regular". O ~/.venv tem
o Plotly Dash instalado (também chamado "dash"), e um pacote regular no
site-packages ganha de um diretório sem __init__.py, mesmo que apps/ venha
antes no sys.path. Com este arquivo, vale a ordem do sys.path e apps/dash é
o escolhido. Não remova.

2026.out  mlabru  initial version (Linux/Python)
"""
