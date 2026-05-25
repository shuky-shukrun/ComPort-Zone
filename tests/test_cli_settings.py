"""Tests for ``comport-zone settings show/get/set/export/import``."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from ComPort_Zone.cli.main import cli
from ComPort_Zone.core.models import AppSettings, SETTINGS_SCHEMA_VERSION, SerialProfile
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore


def _save(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _load(path: Path) -> AppSettings:
    return SettingsService(SettingsStore(path)).load()


class SettingsShowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        _save(
            self.settings_path,
            AppSettings(serial=SerialProfile(port="COM3", baudrate=57600)),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_show_emits_valid_json_with_schema_version(self) -> None:
        result = self.runner.invoke(
            cli, ["--config", str(self.settings_path), "settings", "show"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(payload["transport"]["profile"]["port"], "COM3")

    def test_show_with_section_filters_to_one_subtree(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "show",
                "--section",
                "transport",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(list(payload.keys()), ["transport"])
        self.assertEqual(payload["transport"]["profile"]["baudrate"], 57600)


class SettingsGetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        _save(
            self.settings_path,
            AppSettings(serial=SerialProfile(port="COM5", baudrate=9600)),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_dotted_leaf_prints_scalar(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "get",
                "transport.profile.baudrate",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(result.output.strip(), "9600")

    def test_get_unknown_key_exits_settings_error(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "get",
                "transport.profile.nope",
            ],
        )
        self.assertEqual(result.exit_code, 15, msg=result.output)

    def test_get_json_mode_emits_key_value_pair(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--json",
                "--config",
                str(self.settings_path),
                "settings",
                "get",
                "transport.profile.port",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload, {"key": "transport.profile.port", "value": "COM5"})


class SettingsSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        _save(self.settings_path, AppSettings())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_set_int_field_persists(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "transport.profile.baudrate",
                "230400",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        settings = _load(self.settings_path)
        self.assertEqual(settings.serial.baudrate, 230400)

    def test_set_bool_field_accepts_string_forms(self) -> None:
        for raw, expected in [("true", True), ("false", False), ("on", True), ("0", False)]:
            with self.subTest(raw=raw):
                result = self.runner.invoke(
                    cli,
                    [
                        "--config",
                        str(self.settings_path),
                        "settings",
                        "set",
                        "transport.profile.dtr",
                        raw,
                    ],
                )
                self.assertEqual(result.exit_code, 0, msg=result.output)
                self.assertEqual(_load(self.settings_path).serial.dtr, expected)

    def test_set_string_field_passes_through(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "transport.profile.port",
                "COM9",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(_load(self.settings_path).serial.port, "COM9")

    def test_set_unknown_key_exits_settings_error(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "transport.profile.bogus",
                "x",
            ],
        )
        self.assertEqual(result.exit_code, 15, msg=result.output)

    def test_set_invalid_value_exits_usage_error(self) -> None:
        # Baudrate is int — "fast" can't coerce.
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "transport.profile.baudrate",
                "fast",
            ],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)
        self.assertIn("integer", result.output.lower())

    def test_set_gui_only_key_refused_with_usage_error(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "app.theme",
                "Bench Light",
            ],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)
        self.assertIn("GUI", result.output)

    def test_set_library_key_refused_with_usage_error(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "libraries.quick_command_sort_mode",
                "Title",
            ],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)
        self.assertIn("quick", result.output.lower())

    def test_set_read_only_key_refused_with_usage_error(self) -> None:
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "set",
                "schema_version",
                "3",
            ],
        )
        self.assertEqual(result.exit_code, 2, msg=result.output)
        self.assertIn("read-only", result.output.lower())


class SettingsExportImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        _save(
            self.settings_path,
            AppSettings(serial=SerialProfile(port="COM7", baudrate=115200, line_ending="LF")),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_writes_schema_v2_payload_without_libraries(self) -> None:
        export_path = self.tmp_path / "exported.json"
        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "export",
                str(export_path),
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(payload["transport"]["profile"]["port"], "COM7")
        self.assertNotIn("libraries", payload)

    def test_import_dry_run_does_not_modify_settings(self) -> None:
        # Make an export with a different port, then dry-run import — the
        # live settings.json must not change.
        export_path = self.tmp_path / "exported.json"
        self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "settings", "export", str(export_path)],
        )
        # Mutate the export to flip the port.
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        payload["transport"]["profile"]["port"] = "COM_DRYRUN"
        export_path.write_text(json.dumps(payload), encoding="utf-8")

        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "import",
                str(export_path),
                "--dry-run",
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # settings.json should still show the original port.
        self.assertEqual(_load(self.settings_path).serial.port, "COM7")

    def test_import_round_trips_through_export(self) -> None:
        # Export, modify, import, verify the change took.
        export_path = self.tmp_path / "exported.json"
        self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "settings", "export", str(export_path)],
        )
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        payload["transport"]["profile"]["port"] = "COM_NEW"
        export_path.write_text(json.dumps(payload), encoding="utf-8")

        result = self.runner.invoke(
            cli,
            [
                "--config",
                str(self.settings_path),
                "settings",
                "import",
                str(export_path),
            ],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(_load(self.settings_path).serial.port, "COM_NEW")

    def test_import_wrong_schema_version_exits_settings_error(self) -> None:
        bad_path = self.tmp_path / "bad_schema.json"
        bad_path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "settings", "import", str(bad_path)],
        )
        self.assertEqual(result.exit_code, 15, msg=result.output)
        self.assertIn("schema_version", result.output)

    def test_import_invalid_json_exits_parse_error(self) -> None:
        bad_path = self.tmp_path / "bad.json"
        bad_path.write_text("{this is not json", encoding="utf-8")
        result = self.runner.invoke(
            cli,
            ["--config", str(self.settings_path), "settings", "import", str(bad_path)],
        )
        self.assertEqual(result.exit_code, 13, msg=result.output)


if __name__ == "__main__":
    unittest.main()
