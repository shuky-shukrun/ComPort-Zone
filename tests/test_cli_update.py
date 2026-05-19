"""Tests for ``comport-zone update check``.

The command always exits 0 (per spec), so coverage focuses on what gets
printed under each outcome: newer release available, no update needed,
and network failure.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone import __version__ as APP_VERSION
from ComPort_Zone.cli.main import cli


def _fake_release_body(tag: str, *, name: str | None = None, url: str | None = None) -> bytes:
    payload = {
        "tag_name": tag,
        "name": name or f"Release {tag}",
        "html_url": url or f"https://example.com/{tag}",
    }
    return json.dumps(payload).encode("utf-8")


def _bump_version_segment(version: str) -> str:
    """Build a tag plausibly newer than ``version`` for the test."""
    parts = version.split(".")
    parts[0] = str(int(parts[0]) + 99)
    return ".".join(parts)


class UpdateCheckHappyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_update_available_reports_so(self) -> None:
        future_tag = f"v{_bump_version_segment(APP_VERSION)}"
        with patch(
            "ComPort_Zone.cli.commands.update._fetch_latest_release_body",
            return_value=_fake_release_body(future_tag),
        ):
            result = self.runner.invoke(cli, ["update", "check"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("update_available: True", result.output)
        self.assertIn(future_tag.lstrip("v"), result.output)

    def test_no_update_reports_so(self) -> None:
        with patch(
            "ComPort_Zone.cli.commands.update._fetch_latest_release_body",
            return_value=_fake_release_body(f"v{APP_VERSION}"),
        ):
            result = self.runner.invoke(cli, ["update", "check"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("update_available: False", result.output)

    def test_json_mode_emits_expected_keys(self) -> None:
        with patch(
            "ComPort_Zone.cli.commands.update._fetch_latest_release_body",
            return_value=_fake_release_body(f"v{APP_VERSION}"),
        ):
            result = self.runner.invoke(cli, ["--json", "update", "check"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        for key in (
            "current_version",
            "latest_version",
            "release_name",
            "release_url",
            "update_available",
        ):
            self.assertIn(key, payload)


class UpdateCheckErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_network_failure_exits_zero_and_reports_error(self) -> None:
        def fail(*_args, **_kwargs):
            raise OSError("connection refused")

        with patch(
            "ComPort_Zone.cli.commands.update._fetch_latest_release_body",
            side_effect=fail,
        ):
            result = self.runner.invoke(cli, ["update", "check"])
        # Per spec, exit 0 even on network failure — scripts polling this
        # shouldn't die just because GitHub blinked.
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Could not reach GitHub", result.output)

    def test_invalid_json_response_exits_zero(self) -> None:
        with patch(
            "ComPort_Zone.cli.commands.update._fetch_latest_release_body",
            return_value=b"<html>not json</html>",
        ):
            result = self.runner.invoke(cli, ["update", "check"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Could not reach GitHub", result.output)


if __name__ == "__main__":
    unittest.main()
