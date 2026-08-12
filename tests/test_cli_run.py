"""Tests for ``comport-zone run`` (command-file execution)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from tests.fakes.fake_serial_transport import (
    FakeLanTransport,
    FakeSerialTransport,
    FakeUdpTransport,
)


def _patch_run_transport(fake: FakeSerialTransport):
    return patch(
        "ComPort_Zone.cli.commands.run.make_transport",
        return_value=fake,
    )


def _write_file(parent: Path, name: str, content: str) -> Path:
    path = parent / name
    path.write_text(dedent(content), encoding="utf-8")
    return path


class RunCommandFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_executes_send_and_hex_steps(self) -> None:
        script = _write_file(self.tmp_path, "bringup.txt", """\
            // Bring-up sequence
            SEND *IDN?
            HEX 55 AA 03
            WAIT 10
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(cli, ["run", str(script), "--port", "COM3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("*IDN?", None)])
        self.assertEqual(self.fake.sent_bytes, [b"\x55\xaa\x03"])

    def test_run_expect_match_returns_zero(self) -> None:
        # Use queue_response so the RX arrives AFTER the SEND, matching real
        # device behaviour (and surviving the runner's post-send buffer reset).
        self.fake.queue_response(b"OK\r\n")
        script = _write_file(self.tmp_path, "smoke.txt", """\
            SEND ping
            EXPECT OK
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli, ["run", str(script), "--port", "COM3", "--expect-timeout", "200"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_run_supports_raw_tcp_endpoint(self) -> None:
        fake = FakeLanTransport()
        fake.queue_response(b"PONG\r\n")
        script = _write_file(self.tmp_path, "tcp_smoke.txt", """\
            SEND ping
            EXPECT PONG
        """)
        with patch(
            "ComPort_Zone.cli.commands.run.make_transport",
            return_value=fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    str(script),
                    "--host",
                    "127.0.0.1",
                    "--tcp-port",
                    "7000",
                    "--expect-timeout",
                    "200",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(fake.sent_text, [("ping", None)])

    def test_run_supports_udp_endpoint(self) -> None:
        fake = FakeUdpTransport()
        # No terminator: a command file EXPECT scans the RX stream, so it
        # resolves a bare datagram the same way it resolves a line.
        fake.queue_response(b"PONG")
        script = _write_file(self.tmp_path, "udp_smoke.txt", """\n            SEND ping
            EXPECT PONG
        """)
        with patch(
            "ComPort_Zone.cli.commands.run.make_transport",
            return_value=fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    str(script),
                    "--udp-host",
                    "127.0.0.1",
                    "--udp-port",
                    "5025",
                    "--expect-timeout",
                    "200",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(fake.sent_text, [("ping", None)])

    def test_run_expect_timeout_returns_expect_failed(self) -> None:
        script = _write_file(self.tmp_path, "missing.txt", """\
            SEND ping
            EXPECT PONG
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli, ["run", str(script), "--port", "COM3", "--expect-timeout", "100"],
            )
        self.assertEqual(result.exit_code, 11, msg=result.output)
        self.assertIn("EXPECT", result.output)

    def test_continue_on_expect_fail_keeps_running(self) -> None:
        script = _write_file(self.tmp_path, "keep_going.txt", """\
            SEND step1
            EXPECT NEVER
            SEND step2
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    str(script),
                    "--port",
                    "COM3",
                    "--expect-timeout",
                    "50",
                    "--continue-on-expect-fail",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # Both SENDs should have happened.
        sent = [text for text, _ in self.fake.sent_text]
        self.assertEqual(sent, ["step1", "step2"])

    def test_param_substitution_via_flag(self) -> None:
        script = _write_file(self.tmp_path, "param.txt", """\
            SEND voltage={{VOLT}}
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["run", str(script), "--port", "COM3", "--param", "VOLT=3.3"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("voltage=3.3", None)])

    def test_missing_param_with_non_interactive_exits_12(self) -> None:
        script = _write_file(self.tmp_path, "missing_param.txt", """\
            SEND voltage={{VOLT}}
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["run", str(script), "--port", "COM3", "--non-interactive"],
            )
        self.assertEqual(result.exit_code, 12, msg=result.output)
        self.assertIn("VOLT", result.output)

    def test_parse_error_exits_13(self) -> None:
        # ``HEX 5`` matches the HEX pattern but has an odd nibble count, so
        # parse_hex_payload raises BatchParseError. (``HEX zz zz`` doesn't
        # match the pattern at all and falls through to SEND — the parser
        # is intentionally permissive for ad-hoc text protocols.)
        script = _write_file(self.tmp_path, "bad.txt", """\
            HEX 5
        """)
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(cli, ["run", str(script), "--port", "COM3"])
        self.assertEqual(result.exit_code, 13, msg=result.output)


class RunLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_log_file_records_tx(self) -> None:
        script = _write_file(self.tmp_path, "with_log.txt", """\
            SEND hello
        """)
        log_path = self.tmp_path / "run.log"
        with _patch_run_transport(self.fake):
            result = self.runner.invoke(
                cli,
                ["run", str(script), "--port", "COM3", "--log", str(log_path)],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertTrue(log_path.exists())
        log = log_path.read_text(encoding="utf-8")
        self.assertIn("TX>", log)
        self.assertIn("hello", log)


if __name__ == "__main__":
    unittest.main()
