"""Unit tests for the byte-only RawTransport implementations."""

from __future__ import annotations

import socket
import unittest
from collections import deque

from ComPort_Zone.models import LanProfile, SerialProfile, UdpProfile
from ComPort_Zone.raw_transport import (
    UDP_MAX_DATAGRAM,
    ConnectionLost,
    LanRawTransport,
    SerialRawTransport,
    TransportError,
    UdpRawTransport,
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


class FakeDatagramSocket:
    def __init__(self) -> None:
        self.chunks: deque[bytes] = deque()
        self.sent: list[bytes] = []
        self.closed = False
        self.shutdown_called = False
        self.timeout: float | None = None
        self.recv_sizes: list[int] = []
        self.raise_on_recv: BaseException | None = None
        self.raise_on_send: BaseException | None = None
        self.short_write = False

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def recv(self, size: int) -> bytes:
        self.recv_sizes.append(size)
        if self.raise_on_recv is not None:
            error, self.raise_on_recv = self.raise_on_recv, None
            raise error
        if self.chunks:
            return self.chunks.popleft()
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        if self.raise_on_send is not None:
            error, self.raise_on_send = self.raise_on_send, None
            raise error
        self.sent.append(bytes(data))
        return 1 if self.short_write else len(data)

    def close(self) -> None:
        self.closed = True

    def shutdown(self, how: int) -> None:
        self.shutdown_called = True


class UdpRawTransportTests(unittest.TestCase):
    def _transport(self, sock: FakeDatagramSocket) -> UdpRawTransport:
        return UdpRawTransport(
            UdpProfile(host="127.0.0.1", port=5025),
            socket_factory=lambda addr, timeout: sock,
        )

    def test_roundtrip_write_and_read(self) -> None:
        sock = FakeDatagramSocket()
        sock.chunks.append(b"hello")
        raw = self._transport(sock)
        raw.open()
        self.assertTrue(raw.is_open)
        raw.write(b"PING\n")
        self.assertEqual(sock.sent, [b"PING\n"])
        self.assertEqual(raw.read(), b"hello")
        self.assertEqual(raw.read(), b"")  # nothing queued -> timeout -> empty
        # Sized so Windows never raises WSAEMSGSIZE on a legal IPv4 datagram.
        self.assertEqual(set(sock.recv_sizes), {UDP_MAX_DATAGRAM})

    def test_zero_length_datagram_is_not_end_of_stream(self) -> None:
        sock = FakeDatagramSocket()
        sock.chunks.append(b"")
        raw = self._transport(sock)
        raw.open()
        self.assertEqual(raw.read(), b"")  # no ConnectionLost, unlike TCP

    def test_connection_reset_on_read_is_not_a_loss(self) -> None:
        sock = FakeDatagramSocket()
        sock.raise_on_recv = ConnectionResetError(10054, "reset")
        raw = self._transport(sock)
        raw.open()
        self.assertEqual(raw.read(), b"")

    def test_connection_reset_on_write_is_swallowed(self) -> None:
        sock = FakeDatagramSocket()
        sock.raise_on_send = ConnectionResetError(10054, "reset")
        raw = self._transport(sock)
        raw.open()
        raw.write(b"x")  # no raise
        self.assertEqual(sock.sent, [])

    def test_other_write_error_raises_connection_lost(self) -> None:
        sock = FakeDatagramSocket()
        sock.raise_on_send = OSError("message too long")
        raw = self._transport(sock)
        raw.open()
        with self.assertRaises(ConnectionLost):
            raw.write(b"x")

    def test_short_write_raises_connection_lost(self) -> None:
        sock = FakeDatagramSocket()
        sock.short_write = True
        raw = self._transport(sock)
        raw.open()
        with self.assertRaises(ConnectionLost):
            raw.write(b"xyz")

    def test_other_read_error_raises_connection_lost(self) -> None:
        sock = FakeDatagramSocket()
        sock.raise_on_recv = OSError("socket closed")
        raw = self._transport(sock)
        raw.open()
        with self.assertRaises(ConnectionLost):
            raw.read()

    def test_open_rejects_blank_host_and_bad_port(self) -> None:
        with self.assertRaises(TransportError):
            UdpRawTransport(UdpProfile(host="", port=5025)).open()
        with self.assertRaises(TransportError):
            UdpRawTransport(UdpProfile(host="127.0.0.1", port=70000)).open()

    def test_cancel_read_short_circuits_without_shutdown(self) -> None:
        sock = FakeDatagramSocket()
        sock.chunks.append(b"never delivered")
        raw = self._transport(sock)
        raw.open()
        raw.cancel_read()
        self.assertEqual(raw.read(), b"")
        # shutdown() does not reliably unblock a parked UDP recv, so the
        # transport must not depend on it.
        self.assertFalse(sock.shutdown_called)

    def test_reopen_clears_the_cancel_flag(self) -> None:
        sock = FakeDatagramSocket()
        sock.chunks.append(b"after reopen")
        raw = self._transport(sock)
        raw.open()
        raw.cancel_read()
        raw.close()
        raw.open()
        self.assertEqual(raw.read(), b"after reopen")

    def test_close_is_idempotent(self) -> None:
        sock = FakeDatagramSocket()
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
