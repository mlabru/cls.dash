# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

dsh_rmtsrv
servidor UDP que recebe os comandos do control pad numa thread separada.

por que uma thread e um sinal Qt:
  a interface gráfica só pode ser alterada pela thread principal. Esta thread
  só escuta a rede; cada comando recebido é emitido como sinal Qt
  (sgn_command_received), e o Qt entrega o sinal na thread principal, onde o
  dashboard o trata (CDashboardApp.process_remote_command).

fluxo (run):
  1. abre o socket UDP na porta configurada (se falhar, a thread termina);
  2. para sempre: espera um datagrama, decodifica e emite o sinal.

protocolo: texto UTF-8 simples, um comando por datagrama ("NEXT", "GOTO 2",
...). O servidor só normaliza (strip + maiúsculas); quem interpreta o
comando é o dashboard.

2026.out  mlabru  refatoração para legibilidade: removido o flag _running
                  (nunca era desligado: o recvfrom bloqueia e a thread é
                  daemon, então termina junto com o programa); abertura do
                  socket e decodificação em funções próprias
                  módulos dsh_* movidos para apps/dash/ (imports dash.dsh_xxx)
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import logging
import socket
import threading

# PyQt
from PyQt5 import QtCore

# < constants >────────────────────────────────────────────────────────────────────────

# endereço de escuta: todas as interfaces, para aceitar o pad de outra máquina
CS_LISTEN_ADDRESS = "0.0.0.0"

# tamanho máximo lido por datagrama; os comandos têm poucos bytes
CI_MAX_DATAGRAM_BYTES = 1024

# < logging >──────────────────────────────────────────────────────────────────────────

M_LOG = logging.getLogger(__name__)

# < CRemoteServer >────────────────────────────────────────────────────────────────────

class CRemoteServer(threading.Thread):
    """
    thread que escuta comandos UDP e os repassa à interface como sinal Qt.

    uso:
        l_server = CRemoteServer(5005)
        l_server.signals.sgn_command_received.connect(meu_slot)
        l_server.start()
    """
    class Signals(QtCore.QObject):
        """
        sinais do servidor. Ficam num QObject à parte porque threading.Thread
        não é QObject e não pode declarar sinais.
        """
        # (comando normalizado, IP de quem enviou)
        sgn_command_received = QtCore.pyqtSignal(str, str)

    # ─────────────────────────────────────────────────────────────────────────────────
    def __init__(self, fi_port: int):
        """
        :param fi_port: porta UDP em que o servidor vai escutar
        """
        # daemon=True: a thread não impede o programa de terminar
        super().__init__(daemon=True)

        self._port = fi_port
        self.signals = self.Signals()

    # ─────────────────────────────────────────────────────────────────────────────────
    def run(self):
        """
        corpo da thread (chamado por start()): abre o socket e fica recebendo
        comandos até ocorrer um erro de socket.
        """
        l_socket = self._open_socket()

        if l_socket is None:
            return

        with l_socket:
            self._receive_commands_forever(l_socket)

    # ─────────────────────────────────────────────────────────────────────────────────
    def _open_socket(self):
        """
        cria o socket UDP e o associa à porta.

        :returns: socket.socket pronto para receber, ou None se a porta não
                  pôde ser aberta (ex.: já está em uso)
        """
        l_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            l_socket.bind((CS_LISTEN_ADDRESS, self._port))

        except OSError as l_error:
            M_LOG.error(f"servidor UDP: falha ao abrir socket na porta {self._port}: {l_error}")
            l_socket.close()
            return None

        return l_socket

    # ─────────────────────────────────────────────────────────────────────────────────
    def _receive_commands_forever(self, f_socket):
        """
        laço de recepção: cada datagrama válido vira um sinal
        sgn_command_received. Pacotes que não são UTF-8 são descartados; um
        erro de socket encerra o laço (não há como continuar ouvindo).

        :param f_socket: socket UDP já associado à porta
        """
        while True:
            try:
                l_data, lt_sender_address = f_socket.recvfrom(CI_MAX_DATAGRAM_BYTES)

            except OSError as l_error:
                M_LOG.error(f"servidor UDP: {l_error}")
                return

            ls_command = _decode_command(l_data)

            if ls_command is None:
                continue

            ls_sender_ip = lt_sender_address[0]
            self.signals.sgn_command_received.emit(ls_command, ls_sender_ip)

# ─────────────────────────────────────────────────────────────────────────────────────
def _decode_command(f_data: bytes):
    """
    converte os bytes recebidos no comando normalizado.

    :param f_data: conteúdo bruto do datagrama
    :returns: comando sem espaços nas pontas e em maiúsculas (ex.: "  next "
              vira "NEXT"), ou None se os bytes não forem UTF-8 válido
    """
    try:
        ls_text = f_data.decode("utf-8")

    except UnicodeDecodeError as l_error:
        M_LOG.warning(f"servidor UDP: pacote descartado (não-UTF-8): {l_error}")
        return None

    return ls_text.strip().upper()

# < the end >──────────────────────────────────────────────────────────────────────────
