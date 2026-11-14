# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dshcore
código comum aos dois dashboards (web: apps/be; desktop: apps/dash):
  - dsc_env:     variáveis de ambiente e caminhos padrão;
  - dsc_config:  leitura, validação e cache do config.json (fonte única das
                 páginas dos dois dashboards);
  - dsc_nowcast: a regra das páginas de nowcast (idade dos mosaicos, radares
                 ocultos, aviso).
Cada app só formata o resultado do seu jeito (o web em JSON com URLs, o
desktop em (título, caminho) para os tiles).

É um pacote regular (com este __init__.py) pelo mesmo motivo de apps/dash:
um pacote de mesmo nome no site-packages não pode ganhar dele.

2026.nov  mlabru  initial version: config e regra de nowcast unificadas
"""
