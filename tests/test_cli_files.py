"""Tests for ``comport-zone files ...``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from ComPort_Zone.core.models import AppSettings, QuickFile
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore
from tests.fakes.fake_serial_transport import FakeSerialTransport


def _save_settings(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _load_settings(path: Path) -> AppSettings:
    return SettingsService(SettingsStore(path)).load()


def _settings_with_files(*entries: QuickFile) -> AppSettings:
    settings = AppSettings()
    settings.quick_files = list(entries)
    return settings


class FilesCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        _save_settings(self.settings_path, _settings_with_files())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_creates_entry(self) -> None:
        script = self.tmp_path / "bringup.txt"
        script.write_text("SEND *IDN?\n", encoding="utf-8")
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "files",
                "add",
                "--label",
                "Bring-up",
                "--path",
                str(script),
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        self.assertEqual(len(settings.quick_files), 1)
        self.assertEqual(settings.quick_files[0].label, "Bring-up")

    def test_remove_deletes_entry(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_files(QuickFile(label="X", path="C:/x.txt")),
        )
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "files", "remove", "X"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        self.assertEqual(settings.quick_files, [])

    def test_edit_updates_path(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_files(QuickFile(label="X", path="C:/old.txt")),
        )
        new_target = self.tmp_path / "new.txt"
        new_target.write_text("", encoding="utf-8")
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "files",
                "edit",
                "X",
                "--path",
                str(new_target),
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        self.assertEqual(settings.quick_files[0].path, str(new_target))


class FilesRunResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_run_transport(self):
        return patch(
            "ComPort_Zone.cli.commands.run.make_transport",
            return_value=self.fake,
        )

    def test_run_by_label_uses_stored_path(self) -> None:
        script = self.tmp_path / "script.txt"
        script.write_text(dedent("SEND hello\n"), encoding="utf-8")
        _save_settings(
            self.settings_path,
            _settings_with_files(QuickFile(label="Hello", path=str(script))),
        )
        with self._patch_run_transport():
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(self.settings_path),
                    "files",
                    "run",
                    "Hello",
                    "--port",
                    "COM3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("hello", None)])

    def test_run_by_direct_path_when_label_not_found(self) -> None:
        script = self.tmp_path / "direct.txt"
        script.write_text("SEND direct\n", encoding="utf-8")
        _save_settings(self.settings_path, _settings_with_files())
        with self._patch_run_transport():
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(self.settings_path),
                    "files",
                    "run",
                    str(script),
                    "--port",
                    "COM3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("direct", None)])

    def test_unknown_identifier_exits_generic_error(self) -> None:
        _save_settings(self.settings_path, _settings_with_files())
        with self._patch_run_transport():
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(self.settings_path),
                    "files",
                    "run",
                    "no-such-thing",
                    "--port",
                    "COM3",
                ],
            )
        self.assertEqual(result.exit_code, 1, msg=result.output)


if __name__ == "__main__":
    unittest.main()
