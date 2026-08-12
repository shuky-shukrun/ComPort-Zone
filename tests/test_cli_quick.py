"""Tests for ``comport-zone quick ...``."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from ComPort_Zone.core.models import AppSettings, QuickCommand
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore
from tests.fakes.fake_serial_transport import FakeSerialTransport


def _save_settings(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _load_settings(path: Path) -> AppSettings:
    return SettingsService(SettingsStore(path)).load()


def _settings_with_commands(*entries: QuickCommand) -> AppSettings:
    settings = AppSettings()
    settings.quick_commands = list(entries)
    return settings


class QuickListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_library_renders_placeholder(self) -> None:
        _save_settings(self.settings_path, AppSettings(quick_commands=[]))
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "quick", "list"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("(no entries)", result.output)

    def test_filter_by_group(self) -> None:
        settings = _settings_with_commands(
            QuickCommand(label="Read ID", command="*IDN?", group="General"),
            QuickCommand(label="Reset", command="RST", group="Factory"),
        )
        _save_settings(self.settings_path, settings)
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "list",
                "--group",
                "Factory",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Reset", result.output)
        self.assertNotIn("Read ID", result.output)


class QuickAddEditRemoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        # Start with an empty library so default settings.json fields don't pollute.
        _save_settings(self.settings_path, _settings_with_commands())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_creates_entry(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "add",
                "--label",
                "Read ID",
                "--command",
                "*IDN?",
                "--group",
                "General",
                "--mode",
                "text",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        labels = [c.label for c in settings.quick_commands]
        self.assertIn("Read ID", labels)

    def test_add_without_required_flags_returns_usage_error(self) -> None:
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "quick", "add", "--label", "Naked"],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)

    def test_edit_updates_fields(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(label="Read ID", command="*IDN?", group="General"),
            ),
        )
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "edit",
                "Read ID",
                "--command",
                "ID?",
                "--group",
                "Factory",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        self.assertEqual(settings.quick_commands[0].command, "ID?")
        self.assertEqual(settings.quick_commands[0].group, "Factory")

    def test_remove_deletes_entry(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(label="Read ID", command="*IDN?"),
                QuickCommand(label="Reset", command="RST"),
            ),
        )
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "quick", "remove", "Read ID"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        labels = [c.label for c in settings.quick_commands]
        self.assertEqual(labels, ["Reset"])


class QuickSendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        self.fake = FakeSerialTransport()
        self.fake.set_ports([{"device": "COM3"}])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quick_send_uses_stored_command_and_line_ending(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(
                    label="Read ID",
                    command="*IDN?",
                    send_mode="Text",
                    line_ending_override="LF",
                ),
            ),
        )
        with patch(
            "ComPort_Zone.cli.commands.send.make_transport",
            return_value=self.fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(self.settings_path),
                    "quick",
                    "send",
                    "Read ID",
                    "--port",
                    "COM3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_text, [("*IDN?", "LF")])

    def test_quick_send_hex_mode_sends_bytes(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(label="Wake", command="55 AA", send_mode="Hex Bytes"),
            ),
        )
        with patch(
            "ComPort_Zone.cli.commands.send.make_transport",
            return_value=self.fake,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(self.settings_path),
                    "quick",
                    "send",
                    "Wake",
                    "--port",
                    "COM3",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(self.fake.sent_bytes, [b"\x55\xaa"])


class QuickImportExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        _save_settings(self.settings_path, _settings_with_commands())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_then_import_round_trip(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(label="Read ID", command="*IDN?", group="General"),
                QuickCommand(label="Reset", command="RST", group="Factory"),
            ),
        )
        csv_path = self.tmp_path / "library.csv"
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "quick", "export", str(csv_path)]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertTrue(csv_path.exists())

        # Wipe library; import should restore.
        _save_settings(self.settings_path, _settings_with_commands())
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "import",
                str(csv_path),
                "--mode",
                "append",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        labels = sorted(c.label for c in settings.quick_commands)
        self.assertEqual(labels, ["Read ID", "Reset"])

    def test_import_replace_mode_clears_existing(self) -> None:
        _save_settings(
            self.settings_path,
            _settings_with_commands(
                QuickCommand(label="Existing", command="OLD"),
            ),
        )
        csv_path = self.tmp_path / "fresh.csv"
        csv_path.write_text(
            "label,command,description,send_mode,group,line_ending_override\n"
            "NewOne,SHINY,,Text,General,\n",
            encoding="utf-8",
        )
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "import",
                str(csv_path),
                "--mode",
                "replace",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load_settings(self.settings_path)
        labels = [c.label for c in settings.quick_commands]
        self.assertEqual(labels, ["NewOne"])


if __name__ == "__main__":
    unittest.main()
