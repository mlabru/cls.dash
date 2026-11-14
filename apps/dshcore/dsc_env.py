# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsc_env
variáveis de ambiente e caminhos padrão comuns aos dois dashboards. Os
nomes e padrões são os mesmos dos pipelines vizinhos e do dash_sync.sh.

O backend carrega o apps/be/.env ANTES de importar este módulo (os valores
são lidos na importação). Os outros módulos do dshcore leem estes nomes no
momento do uso (dsc_env.CS_xxx), para os testes poderem trocá-los.

2026.nov  mlabru  initial version (juntou o que estava repetido em
                  apps/be/app.py e apps/dash/dsh_config.py)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import getpass
import os

# < diretórios do repositório >────────────────────────────────────────────────────────

# apps/ e apps/be: base dos caminhos relativos (nunca o diretório atual)
CS_APPS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS_BE_DIR = os.path.join(CS_APPS_DIR, "be")

# config.json das páginas, o mesmo para o web e o desktop; CONFIG_FILE
# relativo vale a partir de apps/be
CS_CONFIG_FILE = os.path.join(CS_BE_DIR, os.environ.get("CONFIG_FILE", "config.json"))

# < dados >────────────────────────────────────────────────────────────────────────────

# USER pode não existir em ambientes de serviço; getpass cobre LOGNAME e o pwd
CS_USER = os.environ.get("USER") or getpass.getuser()

# raiz dos dados do STSC
CS_STSC_DATA = os.environ.get("STSC_DATA", f"/home/{CS_USER}/Public")

# saídas do 25.oflow e do 25.u-net (os mosaicos ficam em <raiz>/output)
CS_OFLOW_DATA = os.environ.get("OFLOW_DATA", os.path.join(CS_STSC_DATA, "oflw", "data"))
CS_UNET_DATA = os.environ.get("UNET_DATA", os.path.join(CS_STSC_DATA, "unet", "data"))

# imagem de "indisponível": a mesma que o 25.oflow põe no lugar de uma
# previsão que falhou
CS_NO_CAST_IMAGE = os.environ.get("OFL_NO_CAST_IMAGE",
                                  os.path.join(CS_OFLOW_DATA, "assets", "no_cast.png"))

# enquanto este arquivo existir, os dois dashboards ficam em alerta
# prioritário (o control pad cria/apaga o arquivo)
CS_ALERT_TRIGGER = os.path.join(CS_STSC_DATA, "ALERTA_ATIVO.txt")

# mosaico mais velho que isso = radar fora do ar
CI_NOWCAST_MAX_AGE_HOURS = int(os.environ.get("NOWCAST_MAX_AGE_HOURS", "2"))

# valores usados na expansão das raízes do config.json quando a variável não
# está no ambiente (ver dsc_config.expand_path)
DCT_VAR_DEFAULTS = {"STSC_DATA": CS_STSC_DATA}

# < the end >──────────────────────────────────────────────────────────────────────────
