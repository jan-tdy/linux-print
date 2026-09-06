"""Single-instance guard so launching the app twice (e.g. once via the
systemd --user daemon, once from the desktop launcher or Code Master) just
raises the existing window instead of starting a second CUPS watcher.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .config import IPC_SOCKET_NAME

SHOW_COMMAND = b"show"


class SingleInstanceServer(QObject):
    show_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def listen(self) -> bool:
        QLocalServer.removeServer(IPC_SOCKET_NAME)
        return self._server.listen(IPC_SOCKET_NAME)

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._on_ready_read(socket))

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll())
        if data.strip() == SHOW_COMMAND:
            self.show_requested.emit()
        socket.disconnectFromServer()


def notify_existing_instance() -> bool:
    """Try to reach an already-running instance and ask it to raise its
    window. Returns True if one responded."""
    socket = QLocalSocket()
    socket.connectToServer(IPC_SOCKET_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.write(SHOW_COMMAND)
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True
