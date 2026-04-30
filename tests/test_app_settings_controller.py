import json
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.app_settings_controller import AppSettingsController
from ComPort_Zone.models import AppSettings, QuickCommand, QuickFile, SerialProfile, TerminalSessionState
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore


class AppSettingsControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_export_settings_to_path_saves_runtime_state_and_uses_app_settings_payload(self) -> None:
        parent = QWidget()
        store_path = Path(__file__).with_name("_tmp_controller_settings_store.json")
        export_path = Path(__file__).with_name("_tmp_controller_settings_export.json")
        store_path.unlink(missing_ok=True)
        export_path.unlink(missing_ok=True)
        settings = AppSettings(
            serial=SerialProfile(port="COM7"),
            quick_commands=[QuickCommand(label="Local", command="local")],
            quick_files=[QuickFile(label="Local File", path="C:/scripts/local.txt")],
        )
        save_calls: list[str] = []
        statuses: list[str] = []
        controller = AppSettingsController(
            parent=parent,
            settings_service=SettingsService(SettingsStore(store_path)),
            settings_supplier=lambda: settings,
            save_runtime_settings=lambda: save_calls.append("save-runtime"),
            apply_imported_settings=lambda imported: None,
            set_status=statuses.append,
        )
        try:
            self.assertTrue(controller.export_settings_to_path(export_path))

            payload = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertEqual(save_calls, ["save-runtime"])
            self.assertEqual(payload["transport"]["profile"]["port"], "COM7")
            self.assertNotIn("libraries", payload)
            self.assertEqual(statuses[-1], f"Exported app settings to {export_path}")
        finally:
            store_path.unlink(missing_ok=True)
            export_path.unlink(missing_ok=True)
            parent.deleteLater()

    def test_import_settings_from_json_applies_and_saves_imported_settings(self) -> None:
        parent = QWidget()
        store_path = Path(__file__).with_name("_tmp_controller_settings_import_store.json")
        import_path = Path(__file__).with_name("_tmp_controller_settings_import.json")
        store_path.unlink(missing_ok=True)
        import_path.unlink(missing_ok=True)
        current = AppSettings()
        imported = AppSettings(
            theme="Bench Light",
            restored_tabs=[
                TerminalSessionState(
                    title="Imported DUT",
                    serial=SerialProfile(port="COM12"),
                )
            ],
        )
        service = SettingsService(SettingsStore(store_path))
        service.export_to_json(imported, import_path)
        statuses: list[str] = []

        def apply_imported_settings(settings: AppSettings) -> None:
            nonlocal current
            current = settings

        controller = AppSettingsController(
            parent=parent,
            settings_service=service,
            settings_supplier=lambda: current,
            save_runtime_settings=lambda: None,
            apply_imported_settings=apply_imported_settings,
            set_status=statuses.append,
        )
        try:
            self.assertTrue(controller.import_settings_from_json(import_path))

            saved = service.load()
            self.assertEqual(current.theme, "Bench Light")
            self.assertEqual(current.restored_tabs[0].title, "Imported DUT")
            self.assertEqual(saved.theme, "Bench Light")
            self.assertEqual(statuses[-1], f"Imported app settings from {import_path}.")
        finally:
            store_path.unlink(missing_ok=True)
            import_path.unlink(missing_ok=True)
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
