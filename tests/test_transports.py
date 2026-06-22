import unittest
from queue import Queue

from ComPort_Zone.models import LanProfile, SerialProfile
from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.transports import LanTransportAdapter, SerialTransportAdapter, TransportProfile


class FakeSerialClient:
    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self.connected = False
        self.reconnecting = False
        self.connected_profiles: list[SerialProfile] = []
        self.sent_text: list[tuple[str, str | None]] = []
        self.sent_bytes: list[bytes] = []
        self.subscribers: list[Queue[SerialEvent]] = []

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_reconnecting(self) -> bool:
        return self.reconnecting

    @property
    def active_profile(self) -> SerialProfile | None:
        return self.connected_profiles[-1] if self.connected_profiles else None

    def list_ports(self) -> list[dict[str, str]]:
        return [
            {
                "device": "COM9",
                "description": "USB Serial",
                "hwid": "USB VID:PID",
            }
        ]

    def connect(self, profile: SerialProfile) -> bool:
        self.connected = True
        self.connected_profiles.append(profile)
        return True

    def disconnect(self) -> None:
        self.connected = False

    def send_text(
        self, text: str, line_ending_override: str | None = None, *, source: str = ""
    ) -> None:
        self.sent_text.append((text, line_ending_override))

    def send_bytes(self, data: bytes, *, source: str = "") -> None:
        self.sent_bytes.append(data)

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        queue: Queue[SerialEvent] = Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self.subscribers = [subscriber for subscriber in self.subscribers if subscriber is not queue]


class FakeLanClient:
    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self.connected = False
        self.reconnecting = False
        self.connected_profiles: list[LanProfile] = []
        self.sent_text: list[tuple[str, str | None]] = []
        self.sent_bytes: list[bytes] = []
        self.subscribers: list[Queue[SerialEvent]] = []

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_reconnecting(self) -> bool:
        return self.reconnecting

    @property
    def active_profile(self) -> LanProfile | None:
        return self.connected_profiles[-1] if self.connected_profiles else None

    def connect(self, profile: LanProfile) -> bool:
        self.connected = True
        self.connected_profiles.append(profile)
        return True

    def disconnect(self) -> None:
        self.connected = False

    def send_text(
        self, text: str, line_ending_override: str | None = None, *, source: str = ""
    ) -> None:
        self.sent_text.append((text, line_ending_override))

    def send_bytes(self, data: bytes, *, source: str = "") -> None:
        self.sent_bytes.append(data)

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        queue: Queue[SerialEvent] = Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self.subscribers = [subscriber for subscriber in self.subscribers if subscriber is not queue]


class TransportTests(unittest.TestCase):
    def test_serial_adapter_exposes_transport_contract(self) -> None:
        client = FakeSerialClient()
        adapter = SerialTransportAdapter(client)  # type: ignore[arg-type]

        endpoints = adapter.list_endpoints()
        self.assertEqual(endpoints[0].id, "COM9")
        self.assertEqual(endpoints[0].metadata["hwid"], "USB VID:PID")

        profile = TransportProfile.from_serial_profile(SerialProfile(port="COM9", baudrate=57600))
        self.assertTrue(adapter.connect(profile))
        self.assertTrue(adapter.is_connected)
        self.assertEqual(client.connected_profiles[0].port, "COM9")
        self.assertEqual(client.connected_profiles[0].baudrate, 57600)

        adapter.send_text("status", "LF")
        adapter.send_bytes(b"\x55\xaa")
        self.assertEqual(client.sent_text, [("status", "LF")])
        self.assertEqual(client.sent_bytes, [b"\x55\xaa"])

        subscriber = adapter.subscribe_monitor()
        self.assertEqual(client.subscribers, [subscriber])
        adapter.unsubscribe_monitor(subscriber)
        self.assertEqual(client.subscribers, [])

        adapter.disconnect()
        self.assertFalse(adapter.is_connected)

    def test_serial_adapter_rejects_wrong_profile_kind(self) -> None:
        adapter = SerialTransportAdapter(FakeSerialClient())  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            adapter.connect(TransportProfile(kind="tcp", settings={}))

    def test_lan_adapter_exposes_transport_contract(self) -> None:
        client = FakeLanClient()
        adapter = LanTransportAdapter(client)  # type: ignore[arg-type]

        self.assertEqual(adapter.list_endpoints(), [])

        profile = TransportProfile.from_lan_profile(LanProfile(host="192.168.1.50", port=5025))
        self.assertTrue(adapter.connect(profile))
        self.assertTrue(adapter.is_connected)
        self.assertEqual(client.connected_profiles[0].host, "192.168.1.50")
        self.assertEqual(client.connected_profiles[0].port, 5025)

        adapter.send_text("status", "LF")
        adapter.send_bytes(b"\x55\xaa")
        self.assertEqual(client.sent_text, [("status", "LF")])
        self.assertEqual(client.sent_bytes, [b"\x55\xaa"])

        subscriber = adapter.subscribe_monitor()
        self.assertEqual(client.subscribers, [subscriber])
        adapter.unsubscribe_monitor(subscriber)
        self.assertEqual(client.subscribers, [])

        adapter.disconnect()
        self.assertFalse(adapter.is_connected)

    def test_lan_adapter_rejects_wrong_profile_kind(self) -> None:
        adapter = LanTransportAdapter(FakeLanClient())  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            adapter.connect(TransportProfile(kind="serial", settings={}))


if __name__ == "__main__":
    unittest.main()
