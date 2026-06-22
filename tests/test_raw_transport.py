"""Unit tests for the byte-only RawTransport implementations."""

from __future__ import annotations

import socket
import unittest
from collections import deque

from ComPort_Zone.models import LanProfile, SerialProfile
from ComPort_Zone.raw_transport import (
    ConnectionLost,
    LanRawTransport,
    SerialRawTransport,
    TransportError,
)


class FakeSocket:
    def __init__(self) -> None:
        self.chunks: deque[bytes] = deque()
        self.sent: list[bytes] = []
        self.closed = False
        self.shutdown_called = False
        self.timeout: float | None = None

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def recv(self, size: int) -> bytes:
        if self.chunks:
            return self.chunks.popleft()
        raise socket.timeout()

    def sendall(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    def close(self) -> None:
        self.closed = True

    def shutdown(self, how: int) -> None:
        self.shutdown_called = True


class LanRawTransportTests(unittest.TestCase):
    def _transport(self, sock: FakeSocket) -> LanRawTransport:
        return LanRawTransport(
            LanProfile(host="127.0.0.1", port=8003),
            socket_factory=lambda addr, timeout: sock,
        )

    def test_roundtrip_write_and_read(self) -> None:
        sock = FakeSocket()
        sock.chunks.append(b"hello\r\n")
        raw = self._transport(sock)
        raw.open()
        self.assertTrue(raw.is_open)
        raw.write(b"PING\n")
        self.assertEqual(sock.sent, [b"PING\n"])
        self.assertEqual(raw.read(), b"hello\r\n")
        self.assertEqual(raw.read(), b"")  # nothing queued -> timeout -> empty

    def test_read_timeout_returns_empty(self) -> None:
        sock = FakeSocket()
        raw = self._transport(sock)
        raw.open()
        self.assertEqual(raw.read(), b"")

    def test_remote_close_raises_connection_lost(self) -> None:
        sock = FakeSocket()
        sock.chunks.append(b"")  # recv returning b"" == remote closed
        raw = self._transport(sock)
        raw.open()
        with self.assertRaises(ConnectionLost):
            raw.read()

    def test_write_error_raises_connection_lost(self) -> None:
        sock = FakeSocket()

        def boom(data: bytes) -> None:
            raise OSError("broken pipe")

        sock.sendall = boom  # type: ignore[method-assign]
        raw = self._transport(sock)
        raw.open()
        with self.assertRaises(ConnectionLost):
            raw.write(b"x")

    def test_open_rejects_blank_host(self) -> None:
        raw = LanRawTransport(LanProfile(host="", port=8003))
        with self.assertRaises(TransportError):
            raw.open()

    def test_cancel_read_shuts_down_socket(self) -> None:
        sock = FakeSocket()
        raw = self._transport(sock)
        raw.open()
        raw.cancel_read()
        self.assertTrue(sock.shutdown_called)

    def test_close_is_idempotent(self) -> None:
        sock = FakeSocket()
        raw = self._transport(sock)
        raw.open()
        raw.close()
        raw.close()  # no raise
        self.assertTrue(sock.closed)
        self.assertFalse(raw.is_open)


class SerialRawTransportTests(unittest.TestCase):
    def test_open_bad_port_raises_transport_error(self) -> None:
        raw = SerialRawTransport(SerialProfile(port="COM_DOES_NOT_EXIST_99999"))
        with self.assertRaises(TransportError):
            raw.open()
        self.assertFalse(raw.is_open)

    def test_write_when_closed_raises_connection_lost(self) -> None:
        raw = SerialRawTransport(SerialProfile(port="COM_DOES_NOT_EXIST_99999"))
        with self.assertRaises(ConnectionLost):
            raw.write(b"x")

    def test_cancel_read_safe_when_never_opened(self) -> None:
        raw = SerialRawTransport(SerialProfile(port="COM_DOES_NOT_EXIST_99999"))
        raw.cancel_read()  # no raise
        raw.close()  # no raise


if __name__ == "__main__":
    unittest.main()
