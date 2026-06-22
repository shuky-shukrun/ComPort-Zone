import unittest

from ComPort_Zone.port_channel import SerialEvent
from ComPort_Zone.serial_core import SerialClient, decode_serial_bytes, format_hex_bytes


class SerialCoreTests(unittest.TestCase):
    def test_format_hex_bytes(self) -> None:
        self.assertEqual(format_hex_bytes(b"\x00\x7f\xff"), "00 7F FF")

    def test_monitor_subscribers_receive_events_with_raw_bytes(self) -> None:
        client = SerialClient()
        subscriber = client.subscribe_monitor()

        client.emit_event(
            SerialEvent(kind="rx", message=decode_serial_bytes(b"\xffOK"), raw=b"\xffOK")
        )

        event = subscriber.get_nowait()
        self.assertEqual(event.message, "�OK")
        self.assertEqual(event.raw, b"\xffOK")

    def test_unsubscribe_stops_delivery(self) -> None:
        client = SerialClient()
        subscriber = client.subscribe_monitor()

        client.emit_event(SerialEvent(kind="rx", message="OK"))
        self.assertEqual(subscriber.get_nowait().message, "OK")

        client.unsubscribe_monitor(subscriber)
        client.emit_event(SerialEvent(kind="rx", message="NEXT"))
        self.assertTrue(subscriber.empty())

    def test_reconnect_state_reports_live_thread(self) -> None:
        class AliveThread:
            def __init__(self, alive: bool) -> None:
                self.alive = alive

            def is_alive(self) -> bool:
                return self.alive

        client = SerialClient()
        self.assertFalse(client.is_reconnecting)

        client._reconnect_thread = AliveThread(True)
        self.assertTrue(client.is_reconnecting)

        client._reconnect_thread.alive = False
        self.assertFalse(client.is_reconnecting)


if __name__ == "__main__":
    unittest.main()
