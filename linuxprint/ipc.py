"""Single-instance guard so launching the app twice (e.g. once via the
systemd --user daemon, once from the desktop launcher or Code Master) just
raises the existing window instead of starting a second CUPS watcher.

The acquisition order matters: we must attempt to *become* the server
before deciding a second instance is safe to start standalone, and we must
only clear a stale socket path after confirming nobody answers on it --
`QLocalServer.removeServer()` unlinks the socket file unconditionally, so
calling it before `listen()` (as an earlier version of this module did)
could rip the socket out from under an already-running instance and let
two processes both believe they own it, each starting its own CUPS
watcher thread.
"""

from __future__ import annotations

from enum import Enum, auto

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .config import IPC_LOCK_FILE, IPC_SOCKET_NAME

SHOW_COMMAND = b"show"


class AcquisitionResult(Enum):
    PRIMARY = auto()
    SECONDARY = auto()
    ERROR = auto()


class SingleInstanceServer(QObject):
    show_requested = pyqtSignal()

    def __init__(self, socket_name: str = IPC_SOCKET_NAME, lock_file_path: str | None = None) -> None:
        super().__init__()
        self._socket_name = socket_name
        self._lock = QLockFile(lock_file_path or str(IPC_LOCK_FILE))
        self._server: QLocalServer | None = None
        self._create_server()

    def _create_server(self) -> None:
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def listen(self) -> bool:
        """Try to become the single instance. Returns False if another
        process already owns the name (or a stale socket file is in the
        way -- call notify_existing_instance() first to tell the two
        cases apart, then remove_stale_and_retry() only if that fails)."""
        return self._server.listen(self._socket_name)

    def acquire(self) -> AcquisitionResult:
        """Atomically establish or notify the single application instance.

        The lock remains owned by a primary instance for this object's
        lifetime, so no other process can race stale-socket cleanup against
        its live endpoint.
        """
        if not self._lock.tryLock(0):
            notify_existing_instance(self._socket_name)
            return AcquisitionResult.SECONDARY

        if self.listen():
            return AcquisitionResult.PRIMARY
        if notify_existing_instance(self._socket_name):
            self._lock.unlock()
            return AcquisitionResult.SECONDARY
        if self.remove_stale_and_retry():
            return AcquisitionResult.PRIMARY

        self._lock.unlock()
        return AcquisitionResult.ERROR

    def remove_stale_and_retry(self) -> bool:
        """Only call this after notify_existing_instance() has confirmed no
        live process answers on this name -- i.e. the socket path was left
        behind by a previous crash, not a running instance."""
        QLocalServer.removeServer(self._socket_name)
        self._create_server()
        return self.listen()

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


def notify_existing_instance(socket_name: str = IPC_SOCKET_NAME) -> bool:
    """
    Notify a running instance to raise its window.
    
    Returns:
    	bool: `True` if the existing instance accepts the connection, `False` otherwise.
    """
    socket = QLocalSocket()
    socket.connectToServer(socket_name)
    if not socket.waitForConnected(500):
        return False
    socket.write(SHOW_COMMAND)
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True
