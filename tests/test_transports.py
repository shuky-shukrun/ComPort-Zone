import unittest
from queue import Queue

from ComPort_Zone.models import LanProfile, SerialProfile, UdpProfile
from ComPort_Zone.port_channel import DatagramMatcher, LineMatcher
from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.transports import (
    LanTransportAdapter,
    SerialTransportAdapter,
    TransportProfile,
    UdpTransportAdapter,
    create_transport_adapter,
)


class FakeChannel:
    """Just enough PortChannel for ``_ClientAdapter.default_matcher``."""

    def __init__(self, matcher_factory) -> None:
        self._matcher_factory = matcher_factory

    def default_matcher(self):
        return self._matcher_factory()


class FakeClient:
    """Shared body for the per-kind client fakes below; every adapter drives
    the same client surface, so only the profile type and framing differ."""

    matcher_factory = LineMatcher

    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self.connected = False
        self.reconnecting = False
        self.connected_profiles: list = []
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
    def active_profile(self):
        return self.connected_profiles[-1] if self.connected_profiles else None

    @property
    def channel(self) -> FakeChannel:
        return FakeChannel(self.matcher_factory)

    def connect(self, profile) -> bool:
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


class FakeSerialClient(FakeClient):
    def list_ports(self) -> list[dict[str, str]]:
        return [
            {
                "device": "COM9",
                "description": "USB Serial",
                "hwid": "USB VID:PID",
            }
        ]


class FakeLanClient(FakeClient):
    pass


class FakeUdpClient(FakeClient):
    matcher_factory = DatagramMatcher


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

    def test_udp_adapter_exposes_transport_contract(self) -> None:
        client = FakeUdpClient()
        adapter = UdpTransportAdapter(client)  # type: ignore[arg-type]

        self.assertEqual(adapter.list_endpoints(), [])

        profile = TransportProfile.from_udp_profile(UdpProfile(host="192.168.1.50", port=5025))
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

        # UDP has no modem control lines.
        self.assertFalse(adapter.supports_signals())
        self.assertFalse(adapter.set_dtr(True))
        self.assertFalse(adapter.set_rts(True))
        self.assertFalse(adapter.send_break())
        self.assertIsNone(adapter.signal_state())

        adapter.disconnect()
        self.assertFalse(adapter.is_connected)

    def test_udp_adapter_rejects_wrong_profile_kind(self) -> None:
        adapter = UdpTransportAdapter(FakeUdpClient())  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            adapter.connect(TransportProfile(kind="lan", settings={}))

    def test_udp_transport_profile_round_trips(self) -> None:
        profile = UdpProfile(host="dut.local", port=9000, line_ending="LF", timeout_ms=250)
        wrapped = TransportProfile.from_udp_profile(profile)
        self.assertEqual(wrapped.kind, "udp")
        self.assertEqual(wrapped.to_udp_profile(), profile)

    def test_adapters_report_their_framing_default(self) -> None:
        self.assertIsInstance(
            SerialTransportAdapter(FakeSerialClient()).default_matcher(),  # type: ignore[arg-type]
            LineMatcher,
        )
        self.assertIsInstance(
            LanTransportAdapter(FakeLanClient()).default_matcher(),  # type: ignore[arg-type]
            LineMatcher,
        )
        self.assertIsInstance(
            UdpTransportAdapter(FakeUdpClient()).default_matcher(),  # type: ignore[arg-type]
            DatagramMatcher,
        )

    def test_factory_maps_every_kind_and_falls_back_to_serial(self) -> None:
        self.assertIsInstance(create_transport_adapter("serial"), SerialTransportAdapter)
        self.assertIsInstance(create_transport_adapter("lan"), LanTransportAdapter)
        self.assertIsInstance(create_transport_adapter("udp"), UdpTransportAdapter)
        # A settings file from a newer build must still open.
        self.assertIsInstance(create_transport_adapter("carrier-pigeon"), SerialTransportAdapter)


if __name__ == "__main__":
    unittest.main()
