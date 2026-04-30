import unittest

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QSpinBox

from ComPort_Zone import app as app_module
from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.ui.dialogs import (
    APP_SETTINGS_EXPLANATION,
    AppSettingsTransferDialog,
    QuickCommandDialog,
    QuickCommandImportDialog,
    QuickFileDialog,
    TerminalFontSettingsDialog,
)
from ComPort_Zone.ui.fonts import TERMINAL_FONT_MAX, TERMINAL_FONT_MIN


class DialogExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_app_settings_transfer_dialog_keeps_explanation_and_action_selection(self) -> None:
        dialog = AppSettingsTransferDialog(mode="import")
        try:
            label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

            self.assertIn(APP_SETTINGS_EXPLANATION, label_text)
            self.assertIn("Import App Settings...", buttons)
            self.assertNotIn("Export App Settings...", buttons)

            buttons["Import App Settings..."].click()

            self.assertEqual(dialog.selected_action, "import")
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.deleteLater()

    def test_terminal_font_dialog_clamps_size_and_resets_to_default(self) -> None:
        dialog = TerminalFontSettingsDialog("Definitely Missing Mono", TERMINAL_FONT_MAX + 99)
        try:
            spin = dialog.findChild(QSpinBox)

            self.assertIsNotNone(spin)
            self.assertEqual(dialog.selected_size(), TERMINAL_FONT_MAX)
            self.assertEqual(dialog.selected_family(), "Definitely Missing Mono")

            dialog.reset_defaults()

            self.assertEqual(dialog.selected_family(), "")
            self.assertEqual(dialog.selected_size(), 10)
            self.assertGreaterEqual(dialog.selected_size(), TERMINAL_FONT_MIN)
        finally:
            dialog.deleteLater()

    def test_app_module_reexports_extracted_dialogs_for_compatibility(self) -> None:
        self.assertIs(app_module.AppSettingsTransferDialog, AppSettingsTransferDialog)
        self.assertIs(app_module.QuickCommandDialog, QuickCommandDialog)
        self.assertIs(app_module.QuickCommandImportDialog, QuickCommandImportDialog)
        self.assertIs(app_module.QuickFileDialog, QuickFileDialog)
        self.assertIs(app_module.TerminalFontSettingsDialog, TerminalFontSettingsDialog)

    def test_quick_command_dialog_returns_updated_command(self) -> None:
        original = QuickCommand(
            id="cmd-1",
            label="Old",
            command="*OLD",
            description="Old note",
            send_mode="Hex Bytes",
            group="Factory",
            line_ending_override="CRLF",
            created_at="2026-01-01T00:00:00Z",
        )
        dialog = QuickCommandDialog(original)
        try:
            dialog.label_input.setText("Identity")
            dialog.command_input.setText("*IDN?")
            dialog.description_input.setPlainText("Read identity")
            dialog.group_input.setText("General")
            dialog.mode_combo.setCurrentText("Text")
            dialog.line_ending_combo.setCurrentText("LF")

            command = dialog.quick_command()

            self.assertEqual(command.id, "cmd-1")
            self.assertEqual(command.label, "Identity")
            self.assertEqual(command.command, "*IDN?")
            self.assertEqual(command.description, "Read identity")
            self.assertEqual(command.send_mode, "Text")
            self.assertEqual(command.group, "General")
            self.assertEqual(command.line_ending_override, "LF")
            self.assertEqual(command.created_at, "2026-01-01T00:00:00Z")
            self.assertTrue(command.updated_at)
        finally:
            dialog.deleteLater()

    def test_quick_file_dialog_uses_filename_when_label_is_empty(self) -> None:
        dialog = QuickFileDialog(QuickFile(id="file-1", label="", path="C:/scripts/startup.cmd"))
        try:
            quick_file = dialog.quick_file()

            self.assertEqual(quick_file.id, "file-1")
            self.assertEqual(quick_file.label, "startup.cmd")
            self.assertEqual(quick_file.path, "C:/scripts/startup.cmd")
        finally:
            dialog.deleteLater()

    def test_quick_action_import_dialog_returns_append_or_replace_options(self) -> None:
        dialog = QuickCommandImportDialog(
            title="Import Quick Files",
            message="Choose how to import.",
            default_replace=True,
            default_skip_duplicates=False,
            append_label="Append imported files",
            replace_label="Replace current quick files",
            duplicate_checkbox_text="Skip duplicate file paths",
        )
        try:
            self.assertTrue(dialog.options().replace_existing)
            self.assertFalse(dialog.options().skip_duplicates)

            dialog.behavior_combo.setCurrentIndex(0)
            dialog.skip_duplicates.setChecked(True)

            self.assertFalse(dialog.options().replace_existing)
            self.assertTrue(dialog.options().skip_duplicates)
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
