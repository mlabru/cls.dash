# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_dashbrd
janela principal do dashboard desktop (NOC / videowall): roda em ciclo as
páginas do config.json comum com o web (dsh_nowcast.load_config). Não foi feita para interação direta: é comandada
pelo control pad (UDP) e pelo arquivo de alerta.

páginas de execução: a cada troca de página, a config (relida se o
config.json mudou) é expandida por dsh_nowcast.build_runtime_pages (cada entrada de nowcast vira N páginas, uma
linha por radar, conforme a idade dos mosaicos). _current_page_index indexa
essa lista; GOTO n indexa as entradas do config.json (os botões do pad) e vai para a
primeira página de execução vinda da entrada n. Se um radar aparecer ou
sumir no meio do ciclo, a rotação pode repetir ou pular uma página uma vez.

layout da janela:
  ┌──────────────────────────────────────┐
  │ _pgr_page_time  (tempo da página)    │
  │ _lbl_header     (nome da página /    │
  │                  alerta)             │
  │ _lbl_notice     (aviso da página;    │
  │                  oculto se vazio)    │
  │ _lay_tiles      (tiles lado a lado,  │
  │                  ou um por linha)    │
  │ statusBar       (último evento)      │
  └──────────────────────────────────────┘

três fontes de eventos, todas tratadas na thread principal:
  1. timer (_on_update_timer, a cada gc.CI_UPDATE_INTERVAL_MS):
     a. sincroniza o modo de alerta com a existência de gc.CS_ALERT_TRIGGER;
     b. se não está pausado nem em alerta, avança a barra de progresso e,
        quando o tempo da página acaba, mostra a próxima;
  2. comandos UDP (process_remote_command): GOTO n, NEXT, PREV, START,
     STOP — ignorados durante o alerta;
  3. arquivo de alerta: enquanto existir, a janela fica presa na página 0
     com o cabeçalho vermelho.

regra de robustez: o PyQt5 encerra o programa inteiro se uma exceção escapa
de um slot. Toda troca de página passa por _show_page, que isola cada tile
(um tile com problema fica em branco, mas o videowall continua no ar).

2026.nov  mlabru  páginas vêm do config.json comum com o web (dsh_nowcast.
                  load_config), não mais de gc.CLST_PAGES
2026.nov  mlabru  "duration" inválida (ausente, 0, não numérica) vira
                  CF_MIN_PAGE_SECONDS: antes dividia por zero no slot do timer
2026.out  mlabru  _lbl_notice: aviso da página (radares de nowcast ocultos)
2026.out  mlabru  páginas de nowcast (expandidas em tempo de execução por
                  dsh_nowcast; layout "rows" = um tile por linha); cabeçalho
                  mostra o nome da página; imagem de indisponível
                  (gc.CS_NO_CAST_IMAGE) passada ao wid_tile
2026.out  mlabru  refatoração para legibilidade: comandos remotos numa tabela
                  comando -> método; _display_page, _update_loop e a troca de
                  modo divididos em funções de uma responsabilidade; estilos
                  repetidos viram constantes; tiles antigos param a mídia
                  antes de serem descartados; cada tile é carregado dentro de
                  try/except (uma exceção num slot abortava o PyQt5)
                  módulos dsh_* movidos para apps/dash/ (imports dash.dsh_xxx)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import datetime
import logging
import os
import time

# PyQt
from PyQt5 import QtCore, QtWidgets

# locals
import dash.dsh_config as gc
import dash.dsh_nowcast as nc
import dash.dsh_rmtsrv as rs
import widgets.wid_tile as wt

# < constants >────────────────────────────────────────────────────────────────────────

# a barra de progresso vai de 0 a CI_PROGRESS_MAX (resolução de 0,1%)
CI_PROGRESS_MAX = 1000

# cor da barra de progresso em cada estado
CS_PROGRESS_STYLE_RUNNING = "QProgressBar::chunk { background-color: #ff4b4b; }"
CS_PROGRESS_STYLE_PAUSED = "QProgressBar::chunk { background-color: #555555; }"
CS_PROGRESS_STYLE_ALERT = "QProgressBar::chunk { background-color: #ffff00; }"

# cabeçalho durante o alerta prioritário
CS_ALERT_HEADER = "⚠️  ALERTA DE TEMPO SEVERO ATIVO ⚠️"
CS_ALERT_HEADER_STYLE = ("color: white; background-color: #ff0000; "
                         "font-size: 30px; font-weight: bold;")

# aviso da página (ex.: radares de nowcast ocultos), sob o cabeçalho
CS_NOTICE_STYLE = "color: #ffa500; font-size: 18px; font-weight: bold;"

# cores das mensagens na barra de status
CS_STATUS_COLOR_NORMAL = "#00ff00"
CS_STATUS_COLOR_WARNING = "orange"
CS_STATUS_COLOR_ALERT = "red"

# página exibida durante o alerta prioritário
CI_ALERT_PAGE_INDEX = 0

# piso da duração de uma página (s): "duration" inválida na config vira
# isso em vez de derrubar o programa (ver _page_duration)
CF_MIN_PAGE_SECONDS = 1.

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < CDashboardApp >────────────────────────────────────────────────────────────────────

class CDashboardApp(QtWidgets.QMainWindow):
    """
    janela principal do dashboard (ver o fluxo no topo do módulo).

    estado:
      _llst_pages:         páginas de execução (ver o topo do módulo)
      _current_page_index: índice da página na tela, em _llst_pages
      _page_start_time:    time.time() de quando a página atual começou
      _is_paused:          True depois de STOP, até START
      _in_priority_alert:  True enquanto o arquivo de alerta existir
    """
    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self):
        super().__init__()

        self._llst_pages = []
        self._li_config_page_count = 0
        self._current_page_index = 0
        self._page_start_time = time.time()
        self._is_paused = False
        self._in_priority_alert = False

        wt.set_unavailable_image(gc.CS_NO_CAST_IMAGE)

        self._build_ui()

        # comando UDP (já normalizado pelo servidor) -> método que o executa.
        # GOTO não está aqui porque leva um argumento (ver process_remote_command)
        self._dct_simple_commands = {
            "NEXT": self._show_next_page,
            "PREV": self._show_previous_page,
            "START": self._resume_rotation,
            "STOP": self._pause_rotation,
        }

        self._update_timer = QtCore.QTimer(self)
        self._update_timer.timeout.connect(self._on_update_timer)
        self._update_timer.start(gc.CI_UPDATE_INTERVAL_MS)

        self._remote_server = rs.CRemoteServer(gc.CI_DASHBOARD_PORT,
                                               gc.CS_DASHBOARD_LISTEN_ADDRESS,
                                               gc.CSET_DASHBOARD_ALLOWED_IPS)
        self._remote_server.signals.sgn_command_received.connect(self.process_remote_command)
        self._remote_server.start()

        self._show_page(0)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        """
        cria os widgets da janela (ver o desenho no topo do módulo).
        """
        self._pgr_page_time = QtWidgets.QProgressBar()
        self._pgr_page_time.setTextVisible(False)
        self._pgr_page_time.setRange(0, CI_PROGRESS_MAX)

        self._lbl_header = QtWidgets.QLabel(gc.CS_HEADER)
        self._lbl_header.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_header.setStyleSheet(gc.CS_HEADER_STYLE)

        self._lbl_notice = QtWidgets.QLabel()
        self._lbl_notice.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_notice.setStyleSheet(CS_NOTICE_STYLE)
        self._lbl_notice.hide()

        # a direção muda por página: lado a lado, ou um por linha ("rows")
        self._lay_tiles = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight)

        l_central_widget = QtWidgets.QWidget()
        self.setCentralWidget(l_central_widget)

        l_main_layout = QtWidgets.QVBoxLayout(l_central_widget)
        l_main_layout.addWidget(self._pgr_page_time)
        l_main_layout.addWidget(self._lbl_header)
        l_main_layout.addWidget(self._lbl_notice)
        l_main_layout.addLayout(self._lay_tiles)

        self.setStatusBar(QtWidgets.QStatusBar())

    # < páginas >──────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_page(self, fi_page_index: int):
        """
        troca a página na tela e reinicia a contagem do tempo dela.

        fluxo:
          1. reconstrói as páginas de execução (idade dos mosaicos agora);
          2. normaliza o índice (dá a volta: -1 vira a última página);
          3. remove os tiles da página anterior;
          4. ajusta a direção do layout e cria um tile por item de "tiles";
          5. põe o nome da página no cabeçalho (fora do modo de alerta) e o
             aviso dela (se houver) logo abaixo.

        :param fi_page_index: índice desejado em _llst_pages; pode estar fora
                              da faixa
        """
        self._rebuild_pages()

        if not self._llst_pages:
            M_LOG.error("sem configuração válida: nenhuma página para exibir")
            return

        self._current_page_index = fi_page_index % len(self._llst_pages)
        ldct_page = self._llst_pages[self._current_page_index]

        self._remove_all_tiles()

        self._lay_tiles.setDirection(QtWidgets.QBoxLayout.TopToBottom
                                     if ldct_page.get("layout") == "rows"
                                     else QtWidgets.QBoxLayout.LeftToRight)

        for ls_title, ls_file in ldct_page["tiles"]:
            self._add_tile(ls_title, ls_file)

        if not self._in_priority_alert:
            self._show_page_name_in_header()

        self._show_page_notice(ldct_page.get("notice", ""))

        self._page_start_time = time.time()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_page_notice(self, fs_notice: str):
        """
        mostra o aviso da página sob o cabeçalho, ou esconde o label se não
        houver aviso (para não ocupar uma linha vazia).

        :param fs_notice: texto do aviso ("" ou None = sem aviso)
        """
        self._lbl_notice.setText(fs_notice or "")
        self._lbl_notice.setVisible(bool(fs_notice))

    # ─────────────────────────────────────────────────────────────────────────────────
    def _rebuild_pages(self):
        """
        recalcula as páginas de execução a partir do config.json (relido só
        se mudou; inválido = última versão válida; nunca lido = sem páginas). Barato
        (só um stat por radar), por isso roda a cada troca de página: um
        radar que volta ao ar aparece já na próxima página.
        """
        ldct_config = nc.load_config()

        if ldct_config is None:
            self._llst_pages = []
            self._li_config_page_count = 0
            return

        self._llst_pages = nc.build_runtime_pages(ldct_config, time.time())
        self._li_config_page_count = len(ldct_config["pages"])

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_config_page(self, fi_config_index: int):
        """
        mostra a primeira página de execução vinda da entrada fi_config_index
        do config.json (é o índice que o control pad envia no GOTO).

        :param fi_config_index: índice das entradas do config.json; dá a volta se fora
                                da faixa
        """
        self._rebuild_pages()

        if not self._li_config_page_count:
            M_LOG.error("sem configuração válida: nenhuma página para exibir")
            return

        li_source_index = fi_config_index % self._li_config_page_count

        for li_page_index, ldct_page in enumerate(self._llst_pages):
            if ldct_page["source_index"] == li_source_index:
                self._show_page(li_page_index)
                return

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_page_name_in_header(self):
        """
        cabeçalho em operação normal: o nome da página atual (ou
        gc.CS_HEADER, se a página não tiver nome).
        """
        ls_name = gc.CS_HEADER

        if self._llst_pages:
            ls_name = self._llst_pages[self._current_page_index].get("name") or gc.CS_HEADER

        self._lbl_header.setText(ls_name)
        self._lbl_header.setStyleSheet(gc.CS_HEADER_STYLE)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _remove_all_tiles(self):
        """
        tira os tiles da página atual do layout e os destrói, parando antes
        o GIF ou vídeo de cada um.
        """
        # de trás para frente: remover um item muda o índice dos seguintes
        for li_position in reversed(range(self._lay_tiles.count())):
            l_tile = self._lay_tiles.itemAt(li_position).widget()

            if l_tile is None:
                continue

            l_tile.stop_playback()
            l_tile.setParent(None)  # sai do layout
            l_tile.deleteLater()    # o Qt destrói o widget com segurança no próximo ciclo

    # ─────────────────────────────────────────────────────────────────────────────────
    def _add_tile(self, fs_title: str, fs_file: str):
        """
        cria um tile e o põe no layout. Se o carregamento da mídia falhar,
        o erro é registrado e o tile fica em branco: o dashboard não cai.

        :param fs_title: título do tile
        :param fs_file: caminho do arquivo de mídia
        """
        l_tile = wt.CTileWidget()
        self._lay_tiles.addWidget(l_tile, stretch=1)

        try:
            l_tile.update_content(fs_title, fs_file)

        except Exception:
            M_LOG.exception(f"falha ao carregar o tile {fs_title!r} ({fs_file})")

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_next_page(self):
        self._show_page(self._current_page_index + 1)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_previous_page(self):
        self._show_page(self._current_page_index - 1)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _resume_rotation(self):
        """
        START: volta a rodar as páginas, com o tempo da página atual zerado.
        """
        self._is_paused = False
        self._pgr_page_time.setStyleSheet(CS_PROGRESS_STYLE_RUNNING)
        self._page_start_time = time.time()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _pause_rotation(self):
        """
        STOP: congela na página atual (a barra fica cinza).
        """
        self._is_paused = True
        self._pgr_page_time.setStyleSheet(CS_PROGRESS_STYLE_PAUSED)

    # < comandos remotos >─────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    @QtCore.pyqtSlot(str, str)
    def process_remote_command(self, fs_command: str, fs_sender_ip: str):
        """
        executa um comando recebido do control pad. Chamado pelo Qt na thread
        principal (via sinal sgn_command_received do servidor UDP).

        comandos: "GOTO n" (vai para a página n), "NEXT", "PREV", "START",
        "STOP". Durante o alerta prioritário todos são ignorados; comandos
        desconhecidos também.

        :param fs_command: comando já em maiúsculas e sem espaços nas pontas
        :param fs_sender_ip: IP de quem enviou (só para a mensagem de status)
        """
        if self._in_priority_alert:
            self._show_status_message(f"Comando '{fs_command}' ignorado: MODO ALERTA ATIVO",
                                      CS_STATUS_COLOR_WARNING)
            return

        self._show_status_message(f"Remoto ({fs_sender_ip}): {fs_command}")

        if fs_command.startswith("GOTO"):
            self._go_to_page_from_command(fs_command)
            return

        l_command_action = self._dct_simple_commands.get(fs_command)

        if l_command_action is None:
            M_LOG.warning(f"comando remoto desconhecido: {fs_command!r}")
            return

        l_command_action()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _go_to_page_from_command(self, fs_command: str):
        """
        trata "GOTO n". Comando sem número ou com número inválido é ignorado
        (só registra um aviso).

        :param fs_command: o comando completo, ex.: "GOTO 2"
        """
        llst_parts = fs_command.split()

        if len(llst_parts) < 2:
            M_LOG.warning(f"comando GOTO sem número de página: {fs_command!r}")
            return

        try:
            li_page_index = int(llst_parts[1])

        except ValueError:
            M_LOG.warning(f"comando GOTO com página inválida: {fs_command!r}")
            return

        self._show_config_page(li_page_index)

    # < timer >────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _on_update_timer(self):
        """
        chamado pelo timer a cada gc.CI_UPDATE_INTERVAL_MS: primeiro o alerta,
        depois a rotação das páginas.
        """
        self._sync_priority_alert_with_trigger_file()

        if self._is_paused or self._in_priority_alert:
            return

        self._advance_page_timer()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _sync_priority_alert_with_trigger_file(self):
        """
        entra no modo de alerta quando o arquivo gc.CS_ALERT_TRIGGER aparece
        e sai quando ele some. Não faz nada se o estado já está certo.
        """
        lb_trigger_file_exists = os.path.exists(gc.CS_ALERT_TRIGGER)

        if lb_trigger_file_exists and not self._in_priority_alert:
            self._enter_priority_alert()

        elif not lb_trigger_file_exists and self._in_priority_alert:
            self._exit_priority_alert()

    # ─────────────────────────────────────────────────────────────────────────────────
    def _advance_page_timer(self):
        """
        atualiza a barra de progresso com o tempo já passado na página e
        mostra a próxima página quando a duração dela termina.
        """
        if not self._llst_pages:
            return

        lf_page_duration = _page_duration(self._llst_pages[self._current_page_index])
        lf_elapsed_seconds = time.time() - self._page_start_time

        li_progress = int(lf_elapsed_seconds / lf_page_duration * CI_PROGRESS_MAX)
        self._pgr_page_time.setValue(min(li_progress, CI_PROGRESS_MAX))

        if lf_elapsed_seconds >= lf_page_duration:
            self._show_next_page()

    # < alerta prioritário >───────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _enter_priority_alert(self):
        """
        modo de alerta: cabeçalho vermelho, barra amarela e página
        CI_ALERT_PAGE_INDEX fixa até o arquivo de alerta sumir.
        """
        self._in_priority_alert = True

        self._show_status_message("!!! ALERTA PRIORITÁRIO ATIVADO !!!", CS_STATUS_COLOR_ALERT)

        self._lbl_header.setText(CS_ALERT_HEADER)
        self._lbl_header.setStyleSheet(CS_ALERT_HEADER_STYLE)
        self._pgr_page_time.setStyleSheet(CS_PROGRESS_STYLE_ALERT)

        self._show_config_page(CI_ALERT_PAGE_INDEX)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _exit_priority_alert(self):
        """
        volta ao normal: cabeçalho e barra originais; a rotação continua a
        partir da página atual, com o tempo zerado.
        """
        self._in_priority_alert = False

        self._show_status_message("Alerta finalizado. Retornando ao ciclo normal.")

        self._show_page_name_in_header()
        self._pgr_page_time.setStyleSheet(CS_PROGRESS_STYLE_RUNNING)

        self._page_start_time = time.time()

    # < barra de status >──────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────────────
    def _show_status_message(self, fs_message: str, fs_color: str = CS_STATUS_COLOR_NORMAL):
        """
        mostra uma mensagem com horário na barra de status.

        :param fs_message: texto da mensagem
        :param fs_color: cor do texto (nome ou "#rrggbb")
        """
        ls_now = datetime.datetime.now().strftime("%H:%M:%S")

        self.statusBar().setStyleSheet(f"color: {fs_color};")
        self.statusBar().showMessage(f"[{ls_now}] {fs_message}")

# ─────────────────────────────────────────────────────────────────────────────────────
def _page_duration(fdct_page: dict) -> float:
    """
    duração da página em segundos, nunca menor que CF_MIN_PAGE_SECONDS. Roda
    dentro do slot do timer: "duration" ausente, não numérica ou 0 (divisão
    por zero) levantaria exceção ali, e o PyQt5 encerraria o programa.

    :param fdct_page: página de execução
    :returns: a duração configurada, ou CF_MIN_PAGE_SECONDS se ela for inválida
    """
    try:
        lf_duration = float(fdct_page.get("duration"))

    except (TypeError, ValueError):
        lf_duration = 0.

    # "not >" também pega NaN
    if not lf_duration > CF_MIN_PAGE_SECONDS:
        return CF_MIN_PAGE_SECONDS

    return lf_duration

# < the end >──────────────────────────────────────────────────────────────────────────
