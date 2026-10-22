"""UDP OSC receiver/sender built on QUdpSocket (runs in the Qt event loop, no threads).

`OscServer` decodes incoming packets and hands each message to a dispatcher callback; replies and
feedback go out through `send()`.  Bundles are flattened (timetags are ignored: everything is
applied immediately, which is what MadMapper does for control messages).
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QUdpSocket, QHostAddress

from .protocol import OscBundle, OscMessage, OscError, decode_packet, encode_message

Dispatcher = Callable[[OscMessage, str, int], None]   # message, sender host, sender port


class OscServer(QObject):
    received = pyqtSignal(str, object)      # address, args (for a log/monitor view)
    error = pyqtSignal(str)

    def __init__(self, dispatcher: Dispatcher, parent: QObject | None = None):
        super().__init__(parent)
        self._dispatch = dispatcher
        self.socket: QUdpSocket | None = None
        self.port = 0
        self.feedback_host = ""
        self.feedback_port = 0

    def start(self, port: int) -> bool:
        self.stop()
        sock = QUdpSocket(self)
        if not sock.bind(QHostAddress.SpecialAddress.AnyIPv4, port,
                         QUdpSocket.BindFlag.ShareAddress | QUdpSocket.BindFlag.ReuseAddressHint):
            self.error.emit(f"OSC: cannot bind UDP port {port}: {sock.errorString()}")
            sock.deleteLater()
            return False
        sock.readyRead.connect(self._on_ready)
        self.socket = sock
        self.port = port
        return True

    def stop(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket.deleteLater()
            self.socket = None
        self.port = 0

    @property
    def running(self) -> bool:
        return self.socket is not None

    def _on_ready(self) -> None:
        sock = self.socket
        if sock is None:
            return
        while sock.hasPendingDatagrams():
            datagram = sock.receiveDatagram()
            data = bytes(datagram.data())
            host = datagram.senderAddress().toString()
            port = datagram.senderPort()
            try:
                packet = decode_packet(data)
            except OscError as exc:
                self.error.emit(f"OSC: bad packet from {host}: {exc}")
                continue
            for msg in _flatten(packet):
                self.received.emit(msg.address, list(msg.args))
                try:
                    self._dispatch(msg, host, port)
                except Exception as exc:  # a handler bug must not take the app down
                    self.error.emit(f"OSC: {msg.address}: {exc}")

    def send(self, address: str, args: list, host: str | None = None, port: int | None = None) -> None:
        host = host or self.feedback_host
        port = port or self.feedback_port
        if not host or not port:
            return
        sock = self.socket or QUdpSocket(self)
        try:
            sock.writeDatagram(encode_message(address, args), QHostAddress(host), int(port))
        except OscError as exc:
            self.error.emit(f"OSC: cannot send {address}: {exc}")


def _flatten(packet: OscMessage | OscBundle) -> list[OscMessage]:
    if isinstance(packet, OscMessage):
        return [packet]
    out: list[OscMessage] = []
    for e in packet.elements:
        out.extend(_flatten(e))
    return out
