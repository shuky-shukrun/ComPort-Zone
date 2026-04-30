import unittest

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QSpinBox

from ComPort_Zone import app as app_module
from ComPort_Zone.ui.dialogs import APP_SETTINGS_EXPLANATION, AppSettingsTransferDialog, TerminalFontSettingsDialog
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
        self.assertIs(app_module.TerminalFontSettingsDialog, TerminalFontSettingsDialog)


if __name__ == "__main__":
    unittest.main()
