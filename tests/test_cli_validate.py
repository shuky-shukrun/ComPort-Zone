"""Tests for ``comport-zone validate``."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli


def _write_file(parent: Path, content: str) -> Path:
    path = parent / "cmd.txt"
    path.write_text(dedent(content), encoding="utf-8")
    return path


class ValidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_clean_file_returns_zero(self) -> None:
        path = _write_file(self.tmp_path, """\
            // comment
            SEND *IDN?
            WAIT 100
            HEX 55 AA
            EXPECT OK
        """)
        result = self.runner.invoke(cli, ["validate", str(path)])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("OK", result.output)

    def test_odd_hex_returns_thirteen(self) -> None:
        # ``HEX 5`` matches the HEX pattern but has an odd nibble count, so
        # parse_hex_payload raises. (Anything that doesn't match the HEX
        # pattern at all — e.g. ``HEX zz`` — falls through to SEND, by
        # design: the parser intentionally treats non-keyword lines as ad-hoc
        # text payloads.)
        path = _write_file(self.tmp_path, """\
            HEX 5
        """)
        result = self.runner.invoke(cli, ["validate", str(path)])
        self.assertEqual(result.exit_code, 13, msg=result.output)
        self.assertIn("HEX", result.output)

    def test_unknown_setting_is_reported(self) -> None:
        path = _write_file(self.tmp_path, """\
            @@nope 1
        """)
        result = self.runner.invoke(cli, ["validate", str(path)])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Unknown setting", result.output)

    def test_parameter_with_default_validates_clean(self) -> None:
        path = _write_file(self.tmp_path, """\
            SEND voltage={{VOLT=3.3}}
        """)
        result = self.runner.invoke(cli, ["validate", str(path)])
        self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_json_output_lists_issues(self) -> None:
        path = _write_file(self.tmp_path, """\
            HEX 5
            HEX FFF
        """)
        result = self.runner.invoke(cli, ["--json", "validate", str(path)])
        self.assertEqual(result.exit_code, 13, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(len(payload["issues"]), 2)
        line_numbers = {issue["line_number"] for issue in payload["issues"]}
        self.assertEqual(line_numbers, {1, 2})


if __name__ == "__main__":
    unittest.main()
