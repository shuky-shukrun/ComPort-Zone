import unittest

from ComPort_Zone.serial_core import SerialClient, decode_serial_bytes, format_hex_bytes


class SerialCoreTests(unittest.TestCase):
    def test_rx_events_preserve_raw_bytes(self) -> None:
        client = SerialClient()

        client._emit("rx", decode_serial_bytes(b"\xffOK"), raw=b"\xffOK")
        event = client.events.get_nowait()

        self.assertEqual(event.message, "\ufffdOK")
        self.assertEqual(event.raw, b"\xffOK")

    def test_format_hex_bytes(self) -> None:
        self.assertEqual(format_hex_bytes(b"\x00\x7f\xff"), "00 7F FF")


if __name__ == "__main__":
    unittest.main()
