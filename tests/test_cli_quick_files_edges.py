"""Edge-case tests for ``quick`` and ``files`` subcommands.

Happy paths live in ``test_cli_quick.py`` and ``test_cli_files.py``. This
module focuses on:

* identifier resolution failures (not-found, ambiguous)
* malformed / empty CSV imports
* JSON output for list subcommands
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from ComPort_Zone.core.models import AppSettings, QuickCommand, QuickFile
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore


def _save(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _with_commands(*entries: QuickCommand) -> AppSettings:
    settings = AppSettings()
    settings.quick_commands = list(entries)
    return settings


def _with_files(*entries: QuickFile) -> AppSettings:
    settings = AppSettings()
    settings.quick_files = list(entries)
    return settings


class IdentifierResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quick_edit_unknown_identifier_exits_generic_error(self) -> None:
        _save(self.settings_path, _with_commands())
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "edit",
                "no-such-label",
                "--command",
                "X",
            ],
        )
        self.assertEqual(result.exit_code, 1, msg=result.output)

    def test_quick_remove_unknown_identifier_exits_generic_error(self) -> None:
        _save(self.settings_path, _with_commands())
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "quick", "remove", "ghost"],
        )
        self.assertEqual(result.exit_code, 1, msg=result.output)

    def test_quick_send_unknown_identifier_exits_generic_error(self) -> None:
        _save(self.settings_path, _with_commands())
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "send",
                "ghost",
                "--port",
                "COM3",
            ],
        )
        self.assertEqual(result.exit_code, 1, msg=result.output)

    def test_quick_edit_ambiguous_label_exits_usage_error(self) -> None:
        # Two entries with the same label → exit 2 (USAGE_ERROR).
        _save(
            self.settings_path,
            _with_commands(
                QuickCommand(label="Reset", command="A"),
                QuickCommand(label="Reset", command="B"),
            ),
        )
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "quick",
                "edit",
                "Reset",
                "--command",
                "C",
            ],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)
        self.assertIn("matches", result.output.lower())

    def test_files_edit_unknown_identifier_exits_generic_error(self) -> None:
        _save(self.settings_path, _with_files())
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "files",
                "edit",
                "ghost",
                "--label",
                "X",
            ],
        )
        self.assertEqual(result.exit_code, 1, msg=result.output)

    def test_files_remove_unknown_identifier_exits_generic_error(self) -> None:
        _save(self.settings_path, _with_files())
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "files", "remove", "ghost"],
        )
        self.assertEqual(result.exit_code, 1, msg=result.output)


class MalformedCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        _save(self.settings_path, _with_commands())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quick_import_empty_rows_succeed_silently(self) -> None:
        # A header-only CSV produces zero imported commands — not a parse
        # error, just an empty result.
        csv_path = self.tmp_path / "empty.csv"
        csv_path.write_text(
            "label,command,description,send_mode,group,line_ending_override\n",
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
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Imported 0", result.output)

    def test_quick_import_rows_without_command_are_skipped(self) -> None:
        # Rows that lack a ``command`` value are silently skipped by the
        # CSV-row factory; the import still succeeds without raising.
        csv_path = self.tmp_path / "no_command.csv"
        csv_path.write_text(
            "label,command,description,send_mode,group,line_ending_override\n"
            "naked,,,Text,General,\n",
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
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Imported 0", result.output)

    def test_files_import_accepts_path_aliases(self) -> None:
        # Spec: ``file``/``command_file``/``script`` are accepted as aliases
        # for ``path``. ``title`` aliases ``label``.
        csv_path = self.tmp_path / "aliases.csv"
        csv_path.write_text(
            "title,script\n"
            "Bring-up,C:/scripts/bringup.txt\n"
            "Smoke,C:/scripts/smoke.txt\n",
            encoding="utf-8",
        )
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "files",
                "import",
                str(csv_path),
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = SettingsService(SettingsStore(self.settings_path)).load()
        labels = sorted(qf.label for qf in settings.quick_files)
        # A fresh config seeds the bundled example command file.
        self.assertEqual(labels, ["Bring-up", "Example Commands", "Smoke"])


class JsonListOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quick_list_json_is_array_of_objects(self) -> None:
        _save(
            self.settings_path,
            _with_commands(
                QuickCommand(label="Read ID", command="*IDN?", group="General"),
            ),
        )
        result = self.runner.invoke(
            cli,
            ["--json", "--config", str(self.settings_path), "quick", "list"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(len(payload), 1)
        row = payload[0]
        self.assertEqual(row["label"], "Read ID")
        self.assertEqual(row["command"], "*IDN?")
        # ``id`` is preserved by ``_command_to_row`` even though the plain
        # table only shows label/group/mode/command.
        self.assertIn("id", row)

    def test_files_list_json_is_array_of_objects(self) -> None:
        _save(
            self.settings_path,
            _with_files(QuickFile(label="Bring-up", path="C:/scripts/bringup.txt")),
        )
        result = self.runner.invoke(
            cli,
            ["--json", "--config", str(self.settings_path), "files", "list"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["label"], "Bring-up")
        self.assertEqual(payload[0]["path"], "C:/scripts/bringup.txt")


if __name__ == "__main__":
    unittest.main()
