"""Tests for ``ports list`` and ``ports info``."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli


def _fake_port(
    device: str,
    *,
    description: str = "",
    manufacturer: str = "",
    hwid: str = "",
    vid: int | None = None,
    pid: int | None = None,
) -> SimpleNamespace:
    """Build a ``ListPortInfo``-shaped object for monkey-patching."""
    return SimpleNamespace(
        device=device,
        name=device,
        description=description,
        manufacturer=manufacturer,
        product="",
        hwid=hwid,
        vid=vid,
        pid=pid,
        serial_number="",
        interface="",
        location="",
    )


class PortsListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_empty_list_renders_placeholder(self) -> None:
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=[]):
            result = self.runner.invoke(cli, ["ports", "list"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("(no entries)", result.output)

    def test_plain_output_has_columns_and_sorts_by_device(self) -> None:
        ports = [
            _fake_port("COM7", description="USB Serial", manufacturer="Acme"),
            _fake_port("COM3", description="Bench DUT", manufacturer="DUT Co", hwid="USB\\VID_1234"),
        ]
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=ports):
            result = self.runner.invoke(cli, ["ports", "list"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        com3_index = result.output.find("COM3")
        com7_index = result.output.find("COM7")
        self.assertGreater(com3_index, 0)
        self.assertGreater(com7_index, com3_index)  # sorted alphabetically
        for column in ("port", "description", "manufacturer", "hwid"):
            self.assertIn(column, result.output)

    def test_json_output_is_array_of_objects(self) -> None:
        ports = [_fake_port("COM3", description="Bench DUT", vid=0x1234, pid=0x5678)]
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=ports):
            result = self.runner.invoke(cli, ["--json", "ports", "list"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(len(payload), 1)
        row = payload[0]
        self.assertEqual(row["port"], "COM3")
        self.assertEqual(row["description"], "Bench DUT")
        self.assertEqual(row["vid"], "0x1234")
        self.assertEqual(row["pid"], "0x5678")


class PortsInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_known_port_returns_zero_and_prints_details(self) -> None:
        ports = [_fake_port("COM3", description="Bench DUT", manufacturer="DUT Co")]
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=ports):
            result = self.runner.invoke(cli, ["ports", "info", "COM3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("port: COM3", result.output)
        self.assertIn("description: Bench DUT", result.output)
        self.assertIn("manufacturer: DUT Co", result.output)

    def test_unknown_port_exits_with_port_not_found(self) -> None:
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=[]):
            result = self.runner.invoke(cli, ["ports", "info", "COM9"])
        self.assertEqual(result.exit_code, 14, msg=result.output)
        self.assertIn("COM9", result.output)

    def test_case_insensitive_lookup(self) -> None:
        ports = [_fake_port("COM3", description="Bench DUT")]
        with patch("ComPort_Zone.cli.commands.ports.list_ports.comports", return_value=ports):
            result = self.runner.invoke(cli, ["ports", "info", "com3"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("COM3", result.output)


if __name__ == "__main__":
    unittest.main()
