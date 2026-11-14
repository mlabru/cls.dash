# -*- coding: utf-8 -*-
"""testes unitários para apps/dash/dsh_rmtsrv.py"""

import socket
import time

from PyQt5 import QtWidgets

import dash.dsh_rmtsrv as rs


def _free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for(predicate, timeout=2.0):
    """bombeia o loop de eventos do Qt até a condição ser satisfeita ou estourar o timeout.
    necessário porque o sinal é emitido de outra thread e só é entregue quando o
    event loop da thread principal roda (QueuedConnection)."""
    deadline = time.time() + timeout

    while not predicate() and time.time() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)

    return predicate()


def test_command_is_uppercased_and_ip_captured(qapp):
    port = _free_udp_port()
    server = rs.CRemoteServer(port)

    received = []
    server.signals.sgn_command_received.connect(lambda cmd, ip: received.append((cmd, ip)))
    server.start()

    time.sleep(0.1)  # dá tempo do socket fazer o bind antes de enviarmos algo

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.sendto(b"  next  ", ("127.0.0.1", port))
    client.close()

    assert _wait_for(lambda: len(received) == 1)
    assert received == [("NEXT", "127.0.0.1")]


def test_multiple_commands_preserve_order(qapp):
    port = _free_udp_port()
    server = rs.CRemoteServer(port)

    received = []
    server.signals.sgn_command_received.connect(lambda cmd, ip: received.append(cmd))
    server.start()

    time.sleep(0.1)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for cmd in (b"start", b"goto 2", b"stop"):
        client.sendto(cmd, ("127.0.0.1", port))
    client.close()

    assert _wait_for(lambda: len(received) == 3)
    assert received == ["START", "GOTO 2", "STOP"]


def test_malformed_packet_is_discarded_without_killing_the_server(qapp):
    """regressão: um pacote não-UTF-8 não pode derrubar a thread do servidor
    (o servidor precisa continuar aceitando comandos válidos depois dele)."""
    port = _free_udp_port()
    server = rs.CRemoteServer(port)

    received = []
    server.signals.sgn_command_received.connect(lambda cmd, ip: received.append(cmd))
    server.start()

    time.sleep(0.1)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.sendto(b"\xff\xfe\x00\xff", ("127.0.0.1", port))  # bytes inválidos em UTF-8
    client.sendto(b"next", ("127.0.0.1", port))
    client.close()

    assert _wait_for(lambda: len(received) == 1)
    assert received == ["NEXT"]
    assert server.is_alive()


def test_allowlist_discards_commands_from_other_ips(qapp):
    port = _free_udp_port()
    # 127.0.0.2 também é loopback no Linux: serve de "outra máquina"
    server = rs.CRemoteServer(port, "127.0.0.1", {"127.0.0.2"})

    received = []
    server.signals.sgn_command_received.connect(lambda cmd, ip: received.append((cmd, ip)))
    server.start()

    time.sleep(0.1)

    rejected = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rejected.bind(("127.0.0.1", 0))
    rejected.sendto(b"next", ("127.0.0.1", port))
    rejected.close()

    allowed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    allowed.bind(("127.0.0.2", 0))
    allowed.sendto(b"prev", ("127.0.0.1", port))
    allowed.close()

    assert _wait_for(lambda: len(received) == 1)
    time.sleep(0.1)
    assert received == [("PREV", "127.0.0.2")]
    assert server._set_rejected_ips == {"127.0.0.1"}


def test_listen_address_is_honored(qapp):
    port = _free_udp_port()
    server = rs.CRemoteServer(port, "127.0.0.1")

    received = []
    server.signals.sgn_command_received.connect(lambda cmd, ip: received.append(cmd))
    server.start()

    time.sleep(0.1)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.sendto(b"stop", ("127.0.0.1", port))
    client.close()

    assert _wait_for(lambda: received == ["STOP"])
