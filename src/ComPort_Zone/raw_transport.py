"""Byte-only transport layer underneath :mod:`ComPort_Zone.port_channel`.

A :class:`RawTransport` knows how to open/close a link and move raw bytes
in both directions — nothing else. It has **no** reader thread, no event
queue, no request/response notion. The single owner of a raw transport is
the :class:`~ComPort_Zone.port_channel.PortChannel`, whose reader thread is
the only caller of :meth:`RawTransport.read` and whose worker thread is the
only caller of :meth:`RawTransport.write`. That single-owner rule is what
makes serial and LAN behave identically and is the foundation of the
structural request/response correlation in the channel above.

Qt-free by design (re-exported through ``core/raw_transport.py``).
"""

from __future__ import annotations

import socket
from threading import Lock
from typing import Callable, Protocol

import serial
from serial import SerialException

from .models import LanProfile, SerialProfile

# Reader-thread block granularity. ``read()`` blocks at most this long when
# the wire is idle, so the channel's reader stays responsive to shutdown.
# The per-request response timeout lives in the channel, not here.
DEFAULT_READ_TIMEOUT_S = 0.05

FLOW_CONTROL_FLAGS = {
    "None": {"rtscts": False, "xonxoff": False, "dsrdtr": False},
    "RTS/CTS": {"rtscts": True, "xonxoff": False, "dsrdtr": False},
    "XON/XOFF": {"rtscts": False, "xonxoff": True, "dsrdtr": False},
    "DSR/DTR": {"rtscts": False, "xonxoff": False, "dsrdtr": True},
}


class TransportError(Exception):
    """Opening the link failed (bad port, refused connection, …)."""


class ConnectionLost(Exception):
    """The link dropped mid-stream (cable pulled, remote closed, write/read
    error). Raised from :meth:`RawTransport.read`/:meth:`write`; the channel
    turns it into ``closed`` results and notifies its owner."""


class RawTransport(Protocol):
    @property
    def is_open(self) -> bool: ...

    def open(self) -> None:
        """Open the link. Raises :class:`TransportError` on failure."""

    def close(self) -> None:
        """Close the link. Idempotent; never raises."""

    def write(self, data: bytes) -> None:
        """Write all of ``data``. Raises :class:`ConnectionLost` on failure."""

    def read(self) -> bytes:
        """Return bytes received within the internal read timeout (``b""`` on
        a quiet tick). Raises :class:`ConnectionLost` when the link drops."""

    def cancel_read(self) -> None:
        """Unblock a reader currently parked in :meth:`read` so :meth:`close`
        can complete promptly (the Windows COM-close hang guard)."""


class SerialRawTransport:
    """pyserial-backed :class:`RawTransport`."""

    def __init__(
        self, profile: SerialProfile, *, read_timeout: float = DEFAULT_READ_TIMEOUT_S
    ) -> None:
        self._profile = profile
        self._read_timeout = read_timeout
        self._lock = Lock()
        self._port: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        port = self._port
        return port is not None and port.is_open

    def open(self) -> None:
        profile = self._profile
        flags = FLOW_CONTROL_FLAGS.get(profile.flow_control, FLOW_CONTROL_FLAGS["None"])
        try:
            port = serial.Serial(
                port=profile.port,
                baudrate=profile.baudrate,
                bytesize=profile.bytesize,
                parity=profile.parity,
                stopbits=profile.stopbits,
                timeout=self._read_timeout,
                write_timeout=1,
                **flags,
            )
            port.dtr = profile.dtr
            port.rts = profile.rts
        except (SerialException, ValueError, OSError) as exc:
            raise TransportError(str(exc)) from exc
        with self._lock:
            self._port = port

    def close(self) -> None:
        with self._lock:
            port = self._port
            self._port = None
        if port is None:
            return
        # Unblock a reader parked in read() BEFORE close(). On Windows,
        # closing while a blocking/overlapped read is in flight can hang the
        # calling thread and leave the COM handle held.
        cancel_read = getattr(port, "cancel_read", None)
        if cancel_read is not None:
            try:
                cancel_read()
            except Exception:
                pass
        try:
            port.close()
        except Exception:
            pass

    def write(self, data: bytes) -> None:
        port = self._port
        if port is None or not port.is_open:
            raise ConnectionLost("Serial port is not connected.")
        try:
            port.write(data)
            port.flush()
        except SerialException as exc:
            raise ConnectionLost(str(exc)) from exc

    def read(self) -> bytes:
        port = self._port
        if port is None or not port.is_open:
            raise ConnectionLost("Serial port is not connected.")
        try:
            waiting = port.in_waiting
            return port.read(waiting or 1)
        except SerialException as exc:
            raise ConnectionLost(str(exc)) from exc

    def cancel_read(self) -> None:
        port = self._port
        cancel_read = getattr(port, "cancel_read", None)
        if cancel_read is not None:
            try:
                cancel_read()
            except Exception:
                pass

    # -- serial-only control lines (the channel/client expose these) --------

    def set_signal(self, name: str, value: bool) -> bool:
        """Drive DTR/RTS on the live port. Returns True when applied."""
        with self._lock:
            port = self._port
            if port is None or not port.is_open:
                return False
            try:
                setattr(port, name, value)
            except SerialException:
                return False
            setattr(self._profile, name, value)
            return True

    def send_break(self, duration: float) -> bool:
        port = self._port
        if port is None or not port.is_open:
            return False
        try:
            port.send_break(duration)
        except SerialException:
            return False
        return True

    def signal_state(self) -> tuple[bool, bool] | None:
        port = self._port
        if port is None or not port.is_open:
            return None
        try:
            return (bool(port.dtr), bool(port.rts))
        except SerialException:
            return None


class _SocketLike(Protocol):
    def recv(self, size: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...
    def close(self) -> None: ...
    def settimeout(self, value: float | None) -> None: ...


SocketFactory = Callable[[tuple[str, int], float], _SocketLike]


def _default_socket_factory(address: tuple[str, int], timeout: float) -> _SocketLike:
    return socket.create_connection(address, timeout=timeout)


class LanRawTransport:
    """TCP-socket-backed :class:`RawTransport`."""

    def __init__(
        self,
        profile: LanProfile,
        *,
        socket_factory: SocketFactory | None = None,
        read_timeout: float = DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        self._profile = profile
        self._socket_factory = socket_factory or _default_socket_factory
        self._read_timeout = read_timeout
        self._lock = Lock()
        self._socket: _SocketLike | None = None

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def open(self) -> None:
        profile = self._profile
        if not profile.host.strip() or not 1 <= int(profile.port) <= 65535:
            raise TransportError("LAN host and port are required.")
        connect_timeout = max(profile.timeout_ms, 10) / 1000
        try:
            connection = self._socket_factory(
                (profile.host, int(profile.port)), connect_timeout
            )
            # Decouple the reader tick from the (often larger) connect
            # timeout so shutdown stays responsive.
            connection.settimeout(self._read_timeout)
        except OSError as exc:
            raise TransportError(str(exc)) from exc
        with self._lock:
            self._socket = connection

    def close(self) -> None:
        with self._lock:
            connection = self._socket
            self._socket = None
        if connection is None:
            return
        try:
            connection.close()
        except OSError:
            pass

    def write(self, data: bytes) -> None:
        connection = self._socket
        if connection is None:
            raise ConnectionLost("LAN endpoint is not connected.")
        try:
            connection.sendall(data)
        except OSError as exc:
            raise ConnectionLost(str(exc)) from exc

    def read(self) -> bytes:
        connection = self._socket
        if connection is None:
            raise ConnectionLost("LAN endpoint is not connected.")
        try:
            payload = connection.recv(4096)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConnectionLost(str(exc)) from exc
        if not payload:
            raise ConnectionLost("Remote host closed the connection.")
        return payload

    def cancel_read(self) -> None:
        connection = self._socket
        if connection is None:
            return
        # Shut the read half so a parked recv() returns at once.
        shutdown = getattr(connection, "shutdown", None)
        if shutdown is not None:
            try:
                shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
