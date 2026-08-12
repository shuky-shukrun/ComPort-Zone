"""UdpClient behaviour, including the datagram-specific traps that separate it
from :mod:`tests.test_lan_core`: a zero-length datagram is legal, an ICMP
port-unreachable is not a disconnect, and there is never a reconnect thread."""

import socket
import threading
import time
import unittest
from queue import Queue

from ComPort_Zone.models import UdpProfile
from ComPort_Zone.port_channel import DatagramMatcher, LineMatcher, SerialEvent
from ComPort_Zone.udp_core import UdpClient


class FakeDatagramSocket:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.sent: list[bytes] = []
        self.closed = False
        self.timeout: float | None = None
        self.shutdown_calls = 0
        # Staged exceptions, raised once each then cleared.
        self.raise_on_recv: BaseException | None = None
        self.raise_on_send: BaseException | None = None

    def recv(self, _size: int) -> bytes:
        if self.raise_on_recv is not None:
            error, self.raise_on_recv = self.raise_on_recv, None
            raise error
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.01)
        raise socket.timeout()

    def send(self, data: bytes) -> int:
        if self.raise_on_send is not None:
            error, self.raise_on_send = self.raise_on_send, None
            raise error
        self.sent.append(data)
        return len(data)

    def close(self) -> None:
        self.closed = True

    def shutdown(self, _how: int) -> None:  # pragma: no cover - must stay unused
        self.shutdown_calls += 1

    def settimeout(self, value: float | None) -> None:
        self.timeout = value


def wait_for_event(queue: "Queue[SerialEvent]", kind: str, timeout: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        while not queue.empty():
            event = queue.get_nowait()
            if event.kind == kind:
                return event
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {kind!r} event")


def assert_no_event(test: unittest.TestCase, queue: "Queue[SerialEvent]", kind: str, window: float = 0.3):
    deadline = time.time() + window
    while time.time() < deadline:
        while not queue.empty():
            event = queue.get_nowait()
            test.assertNotEqual(event.kind, kind, msg=f"unexpected {kind}: {event.message}")
        time.sleep(0.01)


class UdpCoreTests(unittest.TestCase):
    def test_open_send_and_close(self) -> None:
        sockets: list[FakeDatagramSocket] = []
        calls: list[tuple[tuple[str, int], float]] = []

        def factory(address: tuple[str, int], timeout: float) -> FakeDatagramSocket:
            connection = FakeDatagramSocket()
            sockets.append(connection)
            calls.append((address, timeout))
            return connection

        client = UdpClient(factory)
        monitor = client.subscribe_monitor()

        self.assertTrue(client.connect(UdpProfile(host="192.168.1.50", port=5025)))
        self.assertTrue(client.is_connected)
        # The read tick, not profile.timeout_ms: opening a datagram socket does
        # no network I/O, so there is no connect timeout to honour.
        self.assertEqual(calls, [(("192.168.1.50", 5025), 0.05)])
        wait_for_event(monitor, "connection")

        client.send_text("PING")
        client.send_bytes(b"\x55\xaa")
        self.assertEqual(wait_for_event(monitor, "tx").message, "PING")
        self.assertEqual(wait_for_event(monitor, "tx").message, "HEX 55 AA")
        self.assertEqual(sockets[0].sent, [b"PING\r\n", b"\x55\xaa"])

        client.disconnect()
        self.assertFalse(client.is_connected)
        self.assertTrue(sockets[0].closed)
        # cancel_read() must not reach for shutdown() on a datagram socket.
        self.assertEqual(sockets[0].shutdown_calls, 0)

    def test_rx_events_preserve_raw_bytes(self) -> None:
        client = UdpClient(lambda _address, _timeout: FakeDatagramSocket([b"\xffOK"]))
        monitor = client.subscribe_monitor()
        self.addCleanup(client.disconnect)

        self.assertTrue(client.connect(UdpProfile(host="dut.local", port=9000)))

        event = wait_for_event(monitor, "rx")
        self.assertEqual(event.raw, b"\xffOK")

    def test_zero_length_datagram_does_not_disconnect(self) -> None:
        """The TCP path treats an empty read as a closed peer. On UDP a
        zero-length datagram is legal and must be ignored."""
        client = UdpClient(lambda _address, _timeout: FakeDatagramSocket([b"", b"AFTER"]))
        monitor = client.subscribe_monitor()
        self.addCleanup(client.disconnect)

        self.assertTrue(client.connect(UdpProfile(host="dut.local", port=9000)))

        self.assertEqual(wait_for_event(monitor, "rx").raw, b"AFTER")
        self.assertTrue(client.is_connected)

    def test_connection_reset_on_recv_keeps_socket_open(self) -> None:
        """Windows raises WSAECONNRESET on the next recv after an ICMP
        port-unreachable. UDP has no connection, so this is not a loss."""
        connection = FakeDatagramSocket([b"LATE"])
        connection.raise_on_recv = ConnectionResetError(10054, "reset")
        client = UdpClient(lambda _address, _timeout: connection)
        monitor = client.subscribe_monitor()
        self.addCleanup(client.disconnect)

        self.assertTrue(client.connect(UdpProfile(host="127.0.0.1", port=5099)))

        self.assertEqual(wait_for_event(monitor, "rx").raw, b"LATE")
        self.assertTrue(client.is_connected)

    def test_connection_reset_on_send_is_swallowed(self) -> None:
        connection = FakeDatagramSocket()
        connection.raise_on_send = ConnectionResetError(10054, "reset")
        client = UdpClient(lambda _address, _timeout: connection)
        monitor = client.subscribe_monitor()
        self.addCleanup(client.disconnect)

        self.assertTrue(client.connect(UdpProfile(host="127.0.0.1", port=5099)))
        client.send_text("BOUNCES")
        client.send_text("LANDS")

        wait_for_event(monitor, "tx")
        assert_no_event(self, monitor, "error")
        self.assertEqual(connection.sent, [b"LANDS\r\n"])
        self.assertTrue(client.is_connected)

    def test_failed_open_never_starts_a_reconnect(self) -> None:
        def factory(_address: tuple[str, int], _timeout: float) -> FakeDatagramSocket:
            raise OSError("no route to host")

        client = UdpClient(factory)
        monitor = client.subscribe_monitor()

        self.assertFalse(client.connect(UdpProfile(host="192.168.1.70", port=23)))
        wait_for_event(monitor, "error")

        # A datagram socket fails to open only for deterministic reasons, so
        # retrying on a timer could never change the outcome.
        self.assertFalse(client.is_reconnecting)
        time.sleep(0.2)
        self.assertFalse(client.is_reconnecting)
        self.assertNotIn(
            "udp-reconnect", [thread.name for thread in threading.enumerate()]
        )

    def test_blank_endpoint_is_rejected(self) -> None:
        client = UdpClient(lambda _address, _timeout: FakeDatagramSocket())
        monitor = client.subscribe_monitor()

        self.assertFalse(client.connect(UdpProfile(host="", port=5025)))
        self.assertIn("host and port", wait_for_event(monitor, "error").message)

    def test_channel_default_matcher_is_datagram(self) -> None:
        client = UdpClient(lambda _address, _timeout: FakeDatagramSocket())
        self.addCleanup(client.disconnect)

        self.assertTrue(client.connect(UdpProfile(host="dut.local", port=9000)))
        self.assertIsInstance(client.channel.default_matcher(), DatagramMatcher)


class UdpLoopbackTests(unittest.TestCase):
    """End-to-end over real sockets: a datagram echo server on loopback."""

    def setUp(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.settimeout(0.1)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        # Reply verbatim minus the line ending, i.e. *without* a terminator of
        # its own — exactly the shape LineMatcher cannot resolve.
        self._thread = threading.Thread(target=self._serve, daemon=True, name="udp-echo")
        self._thread.start()

    def tearDown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._server.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                payload, peer = self._server.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            try:
                self._server.sendto(payload.strip(b"\r\n"), peer)
            except OSError:
                return

    def test_unterminated_reply_completes_via_datagram_matcher(self) -> None:
        client = UdpClient()
        self.addCleanup(client.disconnect)
        self.assertTrue(client.connect(UdpProfile(host="127.0.0.1", port=self.port)))

        result = client.query_text(
            "*IDN?", matcher=DatagramMatcher(), timeout=2.0
        ).result(timeout=3.0)

        self.assertTrue(result.ok, msg=result.status)
        self.assertEqual(result.text(), "*IDN?")

    def test_line_matcher_would_time_out_on_the_same_reply(self) -> None:
        """Pins the motivation for DatagramMatcher: the default framing the
        other transports use cannot resolve an unterminated datagram."""
        client = UdpClient()
        self.addCleanup(client.disconnect)
        self.assertTrue(client.connect(UdpProfile(host="127.0.0.1", port=self.port)))

        result = client.query_text(
            "*IDN?", matcher=LineMatcher(), timeout=0.4
        ).result(timeout=3.0)

        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
