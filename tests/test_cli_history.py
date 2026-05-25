"""Tests for ``comport-zone history list|clear``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from ComPort_Zone.core.models import AppSettings
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore


def _save(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _load(path: Path) -> AppSettings:
    return SettingsService(SettingsStore(path)).load()


class HistoryListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_history_renders_placeholder(self) -> None:
        _save(self.settings_path, AppSettings(command_history=[]))
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "history", "list"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("(no entries)", result.output)

    def test_lists_entries_in_chronological_order(self) -> None:
        _save(
            self.settings_path,
            AppSettings(command_history=["first", "second", "third"]),
        )
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "history", "list"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        first = result.output.find("first")
        third = result.output.find("third")
        self.assertGreaterEqual(first, 0)
        self.assertGreater(third, first)

    def test_limit_returns_only_the_most_recent_n(self) -> None:
        _save(
            self.settings_path,
            AppSettings(command_history=["a", "b", "c", "d"]),
        )
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "history", "list", "--limit", "2"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # ``a`` and ``b`` are too old to show; ``c`` and ``d`` are the
        # most recent two.
        self.assertNotIn("a", result.output.split("\n")[2])  # row after header+rule
        self.assertIn("c", result.output)
        self.assertIn("d", result.output)


class HistoryClearTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_clear_removes_every_entry(self) -> None:
        _save(
            self.settings_path,
            AppSettings(command_history=["one", "two", "three"]),
        )
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "history", "clear"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(_load(self.settings_path).command_history, [])
        self.assertIn("3 entries", result.output)


if __name__ == "__main__":
    unittest.main()
