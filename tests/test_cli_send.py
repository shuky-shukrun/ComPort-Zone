"""Tests for ``comport-zone send`` and ``comport-zone hex``."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from tests.fakes.fake_serial_transport import FakeSerialTransport


def _patch_transport(fake: FakeSerialTransport):
    """Patch the CLI's transport factory to return ``fake``."""
    return patch(
        "ComPort_Zone.cli.transports.make_serial_transport",
        return_value=fake,
    )


def _patch_send_transport(fake: FakeSerialTransport):
    # send.py imports make_serial_transport at module load, so we also need
    # to patch the imported symbol in that module's namespace.
    return patch(
        "ComPort_Zone.cli.commands.send.make_serial_transport",
        return_value=fake,
    )


class SendTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3", "description": "Bench DUT", "hwid": ""}])

    def test_send_text_returns_zero_and_records_send(self) -> None:
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(cli, ["send", "ping", "--port", "COM3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("ping", None)])
        self.assertEqual(self.fake.disconnect_calls, 1)

    def test_send_hex_parses_bytes(self) -> None:
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(cli, ["send", "55 AA 03", "--hex", "--port", "COM3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_bytes, [b"\x55\xaa\x03"])

    def test_hex_subcommand_accepts_byte_tokens(self) -> None:
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(cli, ["hex", "01", "02", "FF", "--port", "COM3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_bytes, [b"\x01\x02\xff"])

    def test_unknown_port_exits_port_not_found(self) -> None:
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(cli, ["send", "ping", "--port", "COM99"])
        self.assertEqual(result.exit_code, 14, msg=result.output)
        self.assertEqual(self.fake.sent_text, [])

    def test_busy_port_exits_port_busy(self) -> None:
        self.fake.connect_returns = False
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(cli, ["send", "ping", "--port", "COM3"])
        self.assertEqual(result.exit_code, 10, msg=result.output)
        self.assertIn("in use", result.output)


class SendExpectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3", "description": "DUT"}])

    def test_expect_match_returns_zero(self) -> None:
        self.fake.stage_rx(b"OK\r\n")
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["send", "ping", "--port", "COM3", "--expect", "OK", "--expect-timeout", "200"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_expect_timeout_returns_expect_failed(self) -> None:
        # No staged RX → pattern can never match.
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["send", "ping", "--port", "COM3", "--expect", "PONG", "--expect-timeout", "100"],
            )
        self.assertEqual(result.exit_code, 11, msg=result.output)
        self.assertIn("PONG", result.output)


class SendJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3", "description": "DUT"}])
        self.fake.stage_rx(b"ack\r\n")

    def test_json_mode_emits_ndjson_events(self) -> None:
        with _patch_send_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["--json", "send", "ping", "--port", "COM3", "--read-after", "100"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        lines = [line for line in result.output.splitlines() if line.strip()]
        events = [json.loads(line) for line in lines]
        kinds = [event["type"] for event in events]
        self.assertIn("tx", kinds)
        self.assertIn("rx", kinds)


if __name__ == "__main__":
    unittest.main()
