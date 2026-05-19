"""Tests for ``comport-zone version`` (plain + JSON output)."""

from __future__ import annotations

import json
import unittest

from click.testing import CliRunner

from ComPort_Zone import __version__ as APP_VERSION
from ComPort_Zone.cli.main import cli


class VersionCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_plain_output_includes_app_version(self) -> None:
        result = self.runner.invoke(cli, ["version"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("comport_zone:", result.output)
        self.assertIn(APP_VERSION, result.output)
        self.assertIn("python:", result.output)
        self.assertIn("pyserial:", result.output)

    def test_json_output_round_trips_and_has_keys(self) -> None:
        result = self.runner.invoke(cli, ["--json", "version"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["comport_zone"], APP_VERSION)
        self.assertIn("python", payload)
        self.assertIn("pyserial", payload)
        self.assertIn("platform", payload)


if __name__ == "__main__":
    unittest.main()
