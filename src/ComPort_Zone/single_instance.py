"""Single-instance file forwarding over a Qt local socket.

When a ``.cpz`` file is double-clicked while ComPort Zone is already running, we want
the path handed to the running ("primary") window — opened in a new tab — instead of a
second process. This module is the thin IPC layer for that:

* :func:`forward_open_request` — the *secondary* launch connects to the primary and
  sends it the file paths, then exits.
* :class:`SingleInstanceServer` — the *primary* window owns this; it listens on the
  shared name and emits :attr:`SingleInstanceServer.openRequested` with the forwarded
  paths.

This is intentionally "forward-only": plain launches (no file) never forward, so the
user can still open independent windows; only the first instance binds the name and
therefore receives forwarded files. See ``app.run`` for the wiring.
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_DEFAULT_TIMEOUT_MS = 300


def default_instance_key() -> str:
    """Per-login server name.

    Scoping to the OS user keeps instances under one login sharing a single primary
    while never colliding with another user's session on a shared/RDP machine.
    """
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - getuser can raise on odd environments
        user = "default"
    return f"ComPortZone-{user}"


def forward_open_request(
    key: str, files: list[str], *, timeout_ms: int = _DEFAULT_TIMEOUT_MS
) -> bool:
    """Send ``files`` to a primary instance listening on ``key``.

    Returns ``True`` when a primary accepted the paths (this process should then exit
    without opening a window), or ``False`` when nothing is listening (this process is
    free to become the primary). Paths should already be absolute — the primary's
    working directory differs from ours.
    """
    if not files:
        return False
    socket = QLocalSocket()
    socket.connectToServer(key)
    if not socket.waitForConnected(timeout_ms):
        return False
    payload = ("\n".join(files) + "\n").encode("utf-8")
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return True


class SingleInstanceServer(QObject):
    """Primary-instance listener. Emits the paths forwarded by secondary launches."""

    openRequested = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def listen(self, key: str) -> bool:
        """Try to become the primary by binding ``key``.

        Returns ``True`` when we own the name (and will emit :attr:`openRequested`), or
        ``False`` when another live instance already owns it (we are a secondary window
        and won't receive forwards).

        Detection probes as a client first rather than relying on ``listen()`` failing:
        on Windows ``QLocalServer`` is a named pipe, which is *not* exclusive — a second
        ``listen()`` on a live name still succeeds — so the bind result alone can't tell
        us whether a primary already exists.
        """
        if _primary_is_live(key):
            return False
        # No live primary. Clear any stale socket a crashed primary left behind (POSIX),
        # then bind.
        QLocalServer.removeServer(key)
        server = QLocalServer(self)
        if not server.listen(key):
            server.deleteLater()
            return False
        self._server = server
        server.newConnection.connect(self._on_new_connection)
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    def _on_new_connection(self) -> None:
        server = self._server
        if server is None:
            return
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is None:
                continue
            # Drain anything already buffered (a client that wrote + disconnected before
            # this slot ran), then read the rest event-driven so we never block the GUI
            # loop waiting on the socket.
            buffer = bytearray(bytes(conn.readAll()))
            self._buffers[conn] = buffer
            if conn.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                self._finalize(conn)
            else:
                conn.readyRead.connect(lambda c=conn: self._on_ready_read(c))
                conn.disconnected.connect(lambda c=conn: self._finalize(c))

    def _on_ready_read(self, conn: QLocalSocket) -> None:
        self._buffers.setdefault(conn, bytearray()).extend(bytes(conn.readAll()))

    def _finalize(self, conn: QLocalSocket) -> None:
        buffer = self._buffers.pop(conn, bytearray())
        buffer.extend(bytes(conn.readAll()))
        conn.deleteLater()
        paths = [line for line in bytes(buffer).decode("utf-8", "replace").split("\n") if line.strip()]
        if paths:
            self.openRequested.emit(paths)


def _primary_is_live(key: str, *, timeout_ms: int = 100) -> bool:
    probe = QLocalSocket()
    probe.connectToServer(key)
    alive = probe.waitForConnected(timeout_ms)
    if alive:
        probe.abort()
    return alive
