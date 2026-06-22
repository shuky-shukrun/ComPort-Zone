import socket
import time
import unittest
from queue import Queue

from ComPort_Zone.lan_core import LanClient
from ComPort_Zone.models import LanProfile
from ComPort_Zone.port_channel import SerialEvent


class FakeSocket:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.sent: list[bytes] = []
        self.closed = False
        self.timeout: float | None = None

    def recv(self, _size: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.01)
        raise socket.timeout()

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True

    def shutdown(self, _how: int) -> None:
        pass

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


class LanCoreTests(unittest.TestCase):
    def test_connect_send_and_disconnect(self) -> None:
        sockets: list[FakeSocket] = []
        calls: list[tuple[tuple[str, int], float]] = []

        def factory(address: tuple[str, int], timeout: float) -> FakeSocket:
            connection = FakeSocket()
            sockets.append(connection)
            calls.append((address, timeout))
            return connection

        client = LanClient(factory)
        monitor = client.subscribe_monitor()
        profile = LanProfile(host="192.168.1.50", port=5025, line_ending="CRLF", auto_reconnect=False)

        self.assertTrue(client.connect(profile))
        self.assertTrue(client.is_connected)
        self.assertEqual(calls, [(("192.168.1.50", 5025), 0.1)])
        wait_for_event(monitor, "connection")

        client.send_text("PING")
        client.send_bytes(b"\x55\xaa")

        # Sends are serialized through the channel; once both TX echoes land
        # the writes have reached the socket in order.
        self.assertEqual(wait_for_event(monitor, "tx").message, "PING")
        self.assertEqual(wait_for_event(monitor, "tx").message, "HEX 55 AA")
        self.assertEqual(sockets[0].sent, [b"PING\r\n", b"\x55\xaa"])

        client.disconnect()
        self.assertFalse(client.is_connected)
        self.assertTrue(sockets[0].closed)

    def test_rx_events_preserve_raw_bytes_and_remote_close_disconnects(self) -> None:
        client = LanClient(lambda _address, _timeout: FakeSocket([b"\xffOK", b""]))
        monitor = client.subscribe_monitor()

        self.assertTrue(
            client.connect(LanProfile(host="dut.local", port=9000, auto_reconnect=False))
        )

        event = wait_for_event(monitor, "rx")
        self.assertEqual(event.message, "�OK")
        self.assertEqual(event.raw, b"\xffOK")
        self.assertEqual(
            wait_for_event(monitor, "error").message,
            "Connection lost: Remote host closed the connection.",
        )
        deadline = time.time() + 1.0
        while time.time() < deadline and client.is_connected:
            time.sleep(0.01)
        self.assertFalse(client.is_connected)

    def test_failed_connect_can_enter_and_stop_reconnect(self) -> None:
        def factory(_address: tuple[str, int], _timeout: float) -> FakeSocket:
            raise OSError("refused")

        client = LanClient(factory)
        monitor = client.subscribe_monitor()

        self.assertFalse(client.connect(LanProfile(host="192.168.1.70", port=23)))
        wait_for_event(monitor, "error")

        deadline = time.time() + 1.0
        while time.time() < deadline and not client.is_reconnecting:
            time.sleep(0.01)
        self.assertTrue(client.is_reconnecting)

        client.disconnect()
        self.assertFalse(client.is_reconnecting)


if __name__ == "__main__":
    unittest.main()
