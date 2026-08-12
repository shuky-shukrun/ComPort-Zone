"""Tests for ``comport-zone listen``."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from tests.fakes.fake_serial_transport import (
    FakeLanTransport,
    FakeSerialTransport,
    FakeUdpTransport,
)


def _patch_listen_transport(fake: FakeSerialTransport):
    return patch(
        "ComPort_Zone.cli.commands.listen.make_transport",
        return_value=fake,
    )


class ListenBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3", "description": "DUT"}])

    def test_duration_stops_listen_and_prints_rx(self) -> None:
        self.fake.stage_rx(b"hello\r\n")
        self.fake.stage_rx(b"world\r\n")
        with _patch_listen_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["listen", "--port", "COM3", "--duration", "0.3"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("hello", result.output)
        self.assertIn("world", result.output)
        self.assertEqual(self.fake.disconnect_calls, 1)

    def test_filter_drops_non_matching_events(self) -> None:
        self.fake.stage_rx(b"INFO ready\r\n")
        self.fake.stage_rx(b"ERR boom\r\n")
        with _patch_listen_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["listen", "--port", "COM3", "--duration", "0.3", "--filter", "^ERR"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertNotIn("INFO ready", result.output)
        self.assertIn("ERR boom", result.output)

    def test_hex_mode_renders_bytes_in_uppercase_hex(self) -> None:
        self.fake.stage_rx(b"\x55\xAA")
        with _patch_listen_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["listen", "--port", "COM3", "--duration", "0.3", "--hex"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("55 AA", result.output)


class ListenLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])
        self.fake.stage_rx(b"line one\r\n")

    def test_log_file_receives_rendered_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "rx.log"
            with _patch_listen_transport(self.fake):
                result = self.runner.invoke(
                    cli,
                    [
                        "listen",
                        "--port",
                        "COM3",
                        "--duration",
                        "0.3",
                        "--log",
                        str(log_path),
                    ],
                )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("line one", content)


class ListenJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])
        self.fake.stage_rx(b"ok\r\n")

    def test_json_mode_emits_rx_events_as_ndjson(self) -> None:
        with _patch_listen_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["--json", "listen", "--port", "COM3", "--duration", "0.3"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        rx_events = []
        for line in result.output.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("type") == "rx":
                rx_events.append(payload)
        self.assertEqual(len(rx_events), 1)
        self.assertEqual(rx_events[0]["port"], "COM3")
        self.assertIn("ok", rx_events[0]["data"])

    def test_tcp_json_mode_identifies_endpoint(self) -> None:
        fake = FakeLanTransport()
        fake.stage_rx(b"echo\r\n")
        with patch(
            "ComPort_Zone.cli.commands.listen.make_transport",
            return_value=fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "listen",
                    "--host",
                    "echo.local",
                    "--tcp-port",
                    "9000",
                    "--duration",
                    "0.3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        rx_payload = next(
            json.loads(line)
            for line in result.output.splitlines()
            if line.strip() and json.loads(line).get("type") == "rx"
        )
        self.assertEqual(rx_payload["transport"], "tcp")
        self.assertEqual(rx_payload["endpoint"], "echo.local:9000")

    def test_udp_json_mode_identifies_endpoint(self) -> None:
        fake = FakeUdpTransport()
        fake.stage_rx(b"echo")
        with patch(
            "ComPort_Zone.cli.commands.listen.make_transport",
            return_value=fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "listen",
                    "--udp-host",
                    "echo.local",
                    "--udp-port",
                    "9000",
                    "--duration",
                    "0.3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        rx_payload = next(
            json.loads(line)
            for line in result.output.splitlines()
            if line.strip() and json.loads(line).get("type") == "rx"
        )
        self.assertEqual(rx_payload["transport"], "udp")
        self.assertEqual(rx_payload["endpoint"], "echo.local:9000")
        # One output record per datagram: an unterminated reply still
        # gets its own line.
        self.assertEqual(rx_payload["data"], "echo")


if __name__ == "__main__":
    unittest.main()
