# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_ctrlpad
janela do control pad: comanda o dashboard desktop (NOC / videowall).

layout da janela (de cima para baixo):
  - IP DO DASHBOARD:  campo com o IP para onde os comandos vão;
  - CONTROLE DE CICLO: ANTERIOR / PRÓXIMO, PAUSAR / RETOMAR;
  - IR PARA PÁGINA:   um botão por entrada do config.json comum com o web
                      (dsh_nowcast.page_names, lido ao abrir o pad);
  - ALERTA PRIORITÁRIO: botão liga/desliga.

como cada botão age:
  - navegação e páginas: enviam um comando de texto por UDP para
    <IP digitado>:gc.CI_DASHBOARD_PORT ("PREV", "NEXT", "STOP", "START",
    "GOTO n"), sem esperar resposta;
  - alerta: cria ou apaga o arquivo gc.CS_ALERT_TRIGGER. NÃO usa a rede: só
    funciona se o pad e o dashboard enxergarem o mesmo disco. Um timer
    (CI_ALERT_SYNC_INTERVAL_MS) mantém o botão igual ao arquivo, mesmo que
    outro pad, um script ou um "rm" o mude.

2026.nov  mlabru  botões de página vêm do config.json comum (nc.page_names)
2026.nov  mlabru  botão de alerta acompanha o arquivo de alerta (antes só era
                  lido ao abrir o pad e ficava errado se o arquivo mudasse)
2026.out  mlabru  refatoração para legibilidade: seções da tela com uma só
                  função de caixa de grupo; envio UDP fecha o socket e só
                  captura OSError; o botão de alerta separa a ação no arquivo
                  da reversão do botão, que agora não reemite toggled (antes
                  a reversão rodava a ação oposta e apagava a mensagem de
                  erro); log de erro com o f-string que faltava
                  módulos dsh_* movidos para apps/dash/ (imports dash.dsh_xxx)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging
import os
import socket

# PyQt
from PyQt5 import QtCore, QtWidgets

# locals
import dash.dsh_config as gc
import dash.dsh_nowcast as nc

# < constants >────────────────────────────────────────────────────────────────────────

# estilo das caixas de grupo ("CONTROLE DE CICLO", "IR PARA PÁGINA")
CS_GROUP_BOX_STYLE = ("QGroupBox { color: white; font-weight: bold; "
                      "border: 1px solid #333; padding-top: 15px; }")

# estilo da barra de status
CS_STATUS_BAR_STYLE = "color: #00ff00; background: #1a1c24;"

# número de colunas da grade de botões "IR PARA PÁGINA"
CI_PAGE_BUTTON_COLUMNS = 2

# intervalo (ms) da conferência do botão de alerta com o arquivo de alerta
CI_ALERT_SYNC_INTERVAL_MS = 1000

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < CControlPadApp >───────────────────────────────────────────────────────────────────

class CControlPadApp(QtWidgets.QMainWindow):
    """
    janela do control pad (ver o layout no topo do módulo).
    """
    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self):
        super().__init__()

        self.setWindowTitle("NOC Control Pad")
        self.setMinimumSize(400, 700)

        l_central_widget = QtWidgets.QWidget()
        self.setCentralWidget(l_central_widget)

        self._lay_main = QtWidgets.QVBoxLayout(l_central_widget)
        self._lay_main.setSpacing(15)
        self._lay_main.setContentsMargins(20, 20, 20, 20)

        self._add_dashboard_ip_field()
        self._add_rotation_controls()
        self._add_page_shortcuts()
        self._add_alert_button()

        self.statusBar().setStyleSheet(CS_STATUS_BAR_STYLE)
        self.statusBar().showMessage("Ready")

        self._alert_sync_timer = QtCore.QTimer(self)
        self._alert_sync_timer.timeout.connect(self._sync_alert_button_with_trigger_file)
        self._alert_sync_timer.start(CI_ALERT_SYNC_INTERVAL_MS)

    # < montagem da tela >─────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_dashboard_ip_field(self):
        """
        campo editável com o IP do dashboard (começa com gc.CS_DASHBOARD_IP).
        """
        self._lay_main.addWidget(QtWidgets.QLabel("IP DO DASHBOARD:"))

        self._txt_dashboard_ip = QtWidgets.QLineEdit(gc.CS_DASHBOARD_IP)
        self._lay_main.addWidget(self._txt_dashboard_ip)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_rotation_controls(self):
        """
        caixa "CONTROLE DE CICLO": ANTERIOR / PRÓXIMO na primeira linha,
        PAUSAR / RETOMAR na segunda.
        """
        l_group_layout = self._add_group_box("CONTROLE DE CICLO", QtWidgets.QVBoxLayout)

        l_navigation_row = QtWidgets.QHBoxLayout()
        l_navigation_row.addWidget(self._create_command_button("⏮ ANTERIOR", "PREV"))
        l_navigation_row.addWidget(self._create_command_button("PRÓXIMO ⏭", "NEXT"))
        l_group_layout.addLayout(l_navigation_row)

        l_pause_row = QtWidgets.QHBoxLayout()
        l_pause_row.addWidget(self._create_command_button("⏸ PAUSAR", "STOP", "StopBtn"))
        l_pause_row.addWidget(self._create_command_button("▶ RETOMAR", "START", "PlayBtn"))
        l_group_layout.addLayout(l_pause_row)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_page_shortcuts(self):
        """
        caixa "IR PARA PÁGINA": um botão "GOTO n" por página, numa grade de
        CI_PAGE_BUTTON_COLUMNS colunas.
        """
        l_grid_layout = self._add_group_box("IR PARA PÁGINA", QtWidgets.QGridLayout)

        for li_page_index, ls_page_name in enumerate(nc.page_names()):
            l_button = self._create_command_button(ls_page_name, f"GOTO {li_page_index}",
                                                   "ActionBtn")

            li_row = li_page_index // CI_PAGE_BUTTON_COLUMNS
            li_column = li_page_index % CI_PAGE_BUTTON_COLUMNS
            l_grid_layout.addWidget(l_button, li_row, li_column)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_alert_button(self):
        """
        botão liga/desliga do alerta prioritário, no rodapé. Começa marcado
        se o arquivo de alerta já existir (ex.: o pad foi reiniciado com o
        alerta ativo).
        """
        self._btn_alert = QtWidgets.QPushButton("⚠️  ALERTA PRIORITÁRIO")
        self._btn_alert.setObjectName("AlertBtn")
        self._btn_alert.setCheckable(True)
        self._btn_alert.setChecked(os.path.exists(gc.CS_ALERT_TRIGGER))

        # conectado depois do setChecked acima, para não criar/apagar o
        # arquivo só por abrir o programa
        self._btn_alert.toggled.connect(self._on_alert_button_toggled)

        self._lay_main.addStretch()  # empurra o botão para o rodapé
        self._lay_main.addWidget(self._btn_alert)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_group_box(self, fs_title: str, f_layout_class):
        """
        cria uma caixa de grupo com título, já no layout principal.

        :param fs_title: título da caixa
        :param f_layout_class: classe do layout interno (ex.: QtWidgets.QGridLayout)
        :returns: o layout interno, onde os botões devem ser colocados
        """
        l_group_box = QtWidgets.QGroupBox(fs_title)
        l_group_box.setStyleSheet(CS_GROUP_BOX_STYLE)

        self._lay_main.addWidget(l_group_box)

        return f_layout_class(l_group_box)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _create_command_button(self, fs_label: str, fs_command: str, fs_style_name: str = ""):
        """
        cria um botão que envia um comando UDP quando clicado.

        :param fs_label: texto do botão
        :param fs_command: comando enviado ao dashboard (ex.: "NEXT", "GOTO 2")
        :param fs_style_name: objectName para o estilo QSS (ex.: "StopBtn");
                              vazio = estilo padrão de botão
        :returns: QtWidgets.QPushButton
        """
        l_button = QtWidgets.QPushButton(fs_label)

        if fs_style_name:
            l_button.setObjectName(fs_style_name)

        # o argumento padrão "fs_cmd=fs_command" fixa o comando DESTE botão
        # no momento da criação (sem ele, todos os botões de um laço
        # enviariam o comando do último). "_checked" é o bool que o sinal
        # clicked envia e não é usado
        l_button.clicked.connect(lambda _checked, fs_cmd=fs_command: self._send_command(fs_cmd))

        return l_button

    # < ações >────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _send_command(self, fs_command: str):
        """
        envia o comando por UDP para o IP digitado, na porta
        gc.CI_DASHBOARD_PORT. UDP não confirma entrega: "Enviado" quer dizer
        que o pacote saiu, não que o dashboard o recebeu.

        :param fs_command: comando de texto (ex.: "NEXT")
        """
        ls_dashboard_ip = self._txt_dashboard_ip.text().strip()

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as l_socket:
                l_socket.sendto(fs_command.encode("utf-8"), (ls_dashboard_ip, gc.CI_DASHBOARD_PORT))

        # IP inválido, rede fora do ar, ...
        except OSError as l_error:
            self.statusBar().showMessage(f"Erro: {l_error}")
            M_LOG.error(f"falha ao enviar {fs_command!r} para {ls_dashboard_ip}: {l_error}")
            return

        self.statusBar().showMessage(f"Enviado: {fs_command} para {ls_dashboard_ip}")

    # ─────────────────────────────────────────────────────────────────────────────────
    def _on_alert_button_toggled(self, fb_alert_on: bool):
        """
        botão de alerta clicado: cria (ligado) ou apaga (desligado) o arquivo
        de alerta. Se não conseguir, avisa numa caixa de diálogo e devolve o
        botão ao estado anterior.

        :param fb_alert_on: novo estado do botão (True = alerta ligado)
        """
        try:
            if fb_alert_on:
                _create_alert_trigger_file()
                self.statusBar().showMessage("ALERTA ATIVADO NO SISTEMA")

            else:
                _remove_alert_trigger_file()
                self.statusBar().showMessage("ALERTA DESATIVADO")

        except OSError as l_error:
            QtWidgets.QMessageBox.critical(self, "Erro de Arquivo",
                                           f"Não foi possível gerenciar o gatilho de alerta:\n{l_error}")
            self._set_alert_button_without_signal(not fb_alert_on)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _sync_alert_button_with_trigger_file(self):
        """
        põe o botão de alerta no estado do arquivo de alerta, se alguém o
        criou ou apagou por fora. Sem emitir toggled: o arquivo já está como
        deve, não há ação a executar.
        """
        lb_alert_on = os.path.exists(gc.CS_ALERT_TRIGGER)

        if lb_alert_on == self._btn_alert.isChecked():
            return

        self._set_alert_button_without_signal(lb_alert_on)
        self.statusBar().showMessage("ALERTA ATIVADO EXTERNAMENTE" if lb_alert_on
                                     else "ALERTA DESATIVADO EXTERNAMENTE")

    # ─────────────────────────────────────────────────────────────────────────────────
    def _set_alert_button_without_signal(self, fb_checked: bool):
        """
        muda o estado do botão de alerta SEM emitir toggled. Sem o bloqueio,
        desfazer o clique chamaria _on_alert_button_toggled de novo e
        executaria a ação oposta.

        :param fb_checked: estado desejado do botão
        """
        self._btn_alert.blockSignals(True)
        self._btn_alert.setChecked(fb_checked)
        self._btn_alert.blockSignals(False)

# ─────────────────────────────────────────────────────────────────────────────────────
def _create_alert_trigger_file():
    """
    cria o arquivo de alerta (vazio). Se já existir, não muda nada.

    :raises OSError: se o arquivo não puder ser criado (ex.: diretório não
                     existe, sem permissão)
    """
    with open(gc.CS_ALERT_TRIGGER, "a"):
        pass

# ─────────────────────────────────────────────────────────────────────────────────────
def _remove_alert_trigger_file():
    """
    apaga o arquivo de alerta. Se ele já não existir, não faz nada.

    :raises OSError: se o arquivo existir mas não puder ser apagado
    """
    if os.path.exists(gc.CS_ALERT_TRIGGER):
        os.remove(gc.CS_ALERT_TRIGGER)

# < the end >──────────────────────────────────────────────────────────────────────────
