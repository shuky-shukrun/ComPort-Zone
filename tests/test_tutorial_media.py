"""Exercise the tutorial as a real TCP/UDP client, without COM hardware."""
import json
import socket
import unittest
from pathlib import Path

from ComPort_Zone.control_panel_models import ControlPanelConfig
from tools.media.demo_device import DemoInstrument, running_demo


class TutorialMediaTests(unittest.TestCase):
    def test_tcp_framing_and_silent_writes(self):
        with running_demo(0) as (_, port):
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                stream = client.makefile("rb")
                client.sendall(b"*ID")
                client.sendall(b"N?\r\nVOLT 15\r\nVOLT?\r\nOUTP OFF\r\nOUTP?\r\n")
                self.assertIn(b"Demo PSU", stream.readline())
                self.assertEqual(stream.readline(), b"15.000\r\n")
                self.assertEqual(stream.readline(), b"0\r\n")
                stream.close()

    def test_udp_uses_the_same_instrument_and_unknown_commands_time_out(self):
        with running_demo(0) as (instrument, port):
            instrument.reply("DEMO:FAULT ON")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.3)
                client.sendto(b"STAT?", ("127.0.0.1", port))
                self.assertEqual(client.recv(100), b"FAULT\r\n")
                client.sendto(b"UNKNOWN?", ("127.0.0.1", port))
                with self.assertRaises(TimeoutError):
                    client.recv(100)

    def test_invalid_setpoints_do_not_corrupt_later_readings(self):
        instrument = DemoInstrument()
        for value in ("nan", "inf", "-1", "25", "bad"):
            instrument.reply(f"VOLT {value}")
        self.assertEqual(instrument.reply("VOLT?"), "12.000")

    def test_tutorial_panel_has_valid_entries(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "examples/tutorial/control-panel.json").read_text())
        config = ControlPanelConfig.from_dict(data["control_panels"][0])
        self.assertEqual(len(config.entries), 8)
        for entry in config.entries:
            self.assertEqual(entry.validation_errors(), [], entry.label)


if __name__ == "__main__":
    unittest.main()
