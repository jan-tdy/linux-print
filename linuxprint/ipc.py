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
        """
        Start listening for single-instance IPC connections.
        
        Returns:
        	bool: `True` if the server starts listening successfully, `False` otherwise.
        """
        QLocalServer.removeServer(IPC_SOCKET_NAME)
        return self._server.listen(IPC_SOCKET_NAME)

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._on_ready_read(socket))

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        """
        Process a command received from a connected local socket.
        
        Parameters:
        	socket (QLocalSocket): Socket containing the received command.
        """
        data = bytes(socket.readAll())
        if data.strip() == SHOW_COMMAND:
            self.show_requested.emit()
        socket.disconnectFromServer()


def notify_existing_instance() -> bool:
    """
    Notify a running instance to raise its window.
    
    Returns:
    	bool: `True` if the existing instance accepts the connection, `False` otherwise.
    """
    socket = QLocalSocket()
    socket.connectToServer(IPC_SOCKET_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.write(SHOW_COMMAND)
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True
