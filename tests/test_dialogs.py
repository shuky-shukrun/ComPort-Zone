import unittest

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QPushButton,
    QSpinBox,
)

from ComPort_Zone import app as app_module
from ComPort_Zone.batch import BatchParameterOccurrence
from ComPort_Zone.command_registry import CommandPaletteEntry
from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.version_check import VersionCheckResult
from ComPort_Zone.ui.dialogs import (
    APP_SETTINGS_EXPLANATION,
    AppSettingsTransferDialog,
    BatchParameterPromptBridge,
    COMMON_BAUD_RATES,
    CommandPaletteDialog,
    CommandFileParametersDialog,
    ConnectionSettingsDialog,
    QuickCommandDialog,
    QuickCommandImportDialog,
    QuickFileDialog,
    TerminalFontSettingsDialog,
    VersionUpdateDialog,
    summarize_parameter_occurrences,
)
from ComPort_Zone.ui.fonts import (
    TERMINAL_FONT_MAX,
    TERMINAL_FONT_MIN,
    TERMINAL_LINE_SPACING_DEFAULT,
    TERMINAL_LINE_SPACING_MAX,
)


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
        dialog = TerminalFontSettingsDialog("Definitely Missing Mono", TERMINAL_FONT_MAX + 99, 999)
        try:
            spin = dialog.findChild(QSpinBox)

            self.assertIsNotNone(spin)
            self.assertEqual(dialog.selected_size(), TERMINAL_FONT_MAX)
            self.assertEqual(dialog.selected_family(), "Definitely Missing Mono")
            # Out-of-range line spacing is clamped to the max.
            self.assertEqual(dialog.selected_line_spacing(), TERMINAL_LINE_SPACING_MAX)

            dialog.reset_defaults()

            self.assertEqual(dialog.selected_family(), "")
            self.assertEqual(dialog.selected_size(), 10)
            self.assertGreaterEqual(dialog.selected_size(), TERMINAL_FONT_MIN)
            self.assertEqual(dialog.selected_line_spacing(), TERMINAL_LINE_SPACING_DEFAULT)
        finally:
            dialog.deleteLater()

    def test_app_module_reexports_extracted_dialogs_for_compatibility(self) -> None:
        self.assertIs(app_module.COMMON_BAUD_RATES, COMMON_BAUD_RATES)
        self.assertIs(app_module.AppSettingsTransferDialog, AppSettingsTransferDialog)
        self.assertIs(app_module.CommandPaletteDialog, CommandPaletteDialog)
        self.assertIs(app_module.ConnectionSettingsDialog, ConnectionSettingsDialog)
        self.assertIs(app_module.QuickCommandDialog, QuickCommandDialog)
        self.assertIs(app_module.QuickCommandImportDialog, QuickCommandImportDialog)
        self.assertIs(app_module.QuickFileDialog, QuickFileDialog)
        self.assertIs(app_module.TerminalFontSettingsDialog, TerminalFontSettingsDialog)
        self.assertIs(app_module.VersionUpdateDialog, VersionUpdateDialog)
        self.assertIs(app_module.BatchParameterPromptBridge, BatchParameterPromptBridge)

    def test_version_update_dialog_syncs_launch_check_initial_state(self) -> None:
        result = VersionCheckResult(
            current_version="0.2.5",
            latest_version="0.2.6",
            release_name="ComPort Zone v0.2.6",
            release_url="https://github.com/shuky-shukrun/ComPort-Zone/releases/tag/v0.2.6",
            update_available=True,
        )
        dialog = VersionUpdateDialog(result, check_on_launch=False)
        try:
            checkbox = dialog.findChild(QCheckBox)

            self.assertIsNotNone(checkbox)
            self.assertFalse(dialog.check_on_launch_enabled())
            checkbox.setChecked(True)
            self.assertTrue(dialog.check_on_launch_enabled())
        finally:
            dialog.deleteLater()

    def test_version_update_dialog_offers_install_when_update_available(self) -> None:
        result = VersionCheckResult(
            current_version="0.2.5",
            latest_version="0.2.6",
            release_name="ComPort Zone v0.2.6",
            release_url="https://github.com/shuky-shukrun/ComPort-Zone/releases/tag/v0.2.6",
            update_available=True,
        )
        dialog = VersionUpdateDialog(result, check_on_launch=False)
        try:
            buttons = {button.text() for button in dialog.findChildren(QPushButton)}
            self.assertIn("Download and Install", buttons)
            self.assertIn("Later", buttons)
        finally:
            dialog.deleteLater()

    def test_version_update_dialog_offers_only_ok_when_up_to_date(self) -> None:
        result = VersionCheckResult(
            current_version="0.2.5",
            latest_version="0.2.5",
            release_name="ComPort Zone v0.2.5",
            release_url="https://github.com/shuky-shukrun/ComPort-Zone/releases/tag/v0.2.5",
            update_available=False,
        )
        dialog = VersionUpdateDialog(result, check_on_launch=False)
        try:
            buttons = {button.text() for button in dialog.findChildren(QPushButton)}
            self.assertEqual(buttons, {"OK"})
        finally:
            dialog.deleteLater()

    def test_command_file_parameter_summary_keeps_stable_names_defaults_and_lines(self) -> None:
        summary = summarize_parameter_occurrences(
            [
                BatchParameterOccurrence("VOLT", "3.3", 1, "SEND VOLT {{VOLT=3.3}}"),
                BatchParameterOccurrence("MODE", None, 2, "SEND MODE {{MODE}}"),
                BatchParameterOccurrence("VOLT", "5.0", 1, "SEND VOLT {{VOLT=3.3}}"),
                BatchParameterOccurrence("MODE", None, 3, "SEND AGAIN {{MODE}}"),
            ]
        )

        self.assertEqual(summary.names, ("VOLT", "MODE"))
        self.assertEqual(summary.defaults, {"VOLT": "3.3"})
        self.assertEqual(
            summary.lines_by_parameter,
            {
                "VOLT": ("Line 1: SEND VOLT {{VOLT=3.3}}",),
                "MODE": (
                    "Line 2: SEND MODE {{MODE}}",
                    "Line 3: SEND AGAIN {{MODE}}",
                ),
            },
        )
        self.assertEqual(
            summary.line_details,
            (
                "Line 1: SEND VOLT {{VOLT=3.3}}",
                "Line 2: SEND MODE {{MODE}}",
                "Line 3: SEND AGAIN {{MODE}}",
            ),
        )

    def test_command_file_parameter_dialog_returns_values_and_ignored_defaults(self) -> None:
        dialog = CommandFileParametersDialog(
            [
                BatchParameterOccurrence("VOLT", "3.3", 1, "SEND VOLT {{VOLT=3.3}}"),
                BatchParameterOccurrence("MODE", None, 2, "SEND MODE {{MODE}}"),
            ]
        )
        try:
            self.assertEqual(dialog.inputs["VOLT"].text(), "3.3")
            self.assertEqual(dialog.inputs["MODE"].placeholderText(), "Ask while running")

            dialog.inputs["VOLT"].clear()
            dialog.inputs["MODE"].setText(" FAST ")

            values, ignored_defaults = dialog.values()

            self.assertEqual(values, {"MODE": "FAST"})
            self.assertEqual(ignored_defaults, {"VOLT"})
        finally:
            dialog.deleteLater()

    def test_connection_settings_dialog_refreshes_ports_and_preserves_manual_port(self) -> None:
        ports = [
            [{"device": "COM1", "description": "USB Serial A"}],
        ]

        def list_ports() -> list[dict[str, str]]:
            return [dict(port) for port in ports[-1]]

        dialog = ConnectionSettingsDialog(
            app_module.SerialProfile(port="COM1", baudrate=57600, line_ending="LF"),
            list_ports(),
            ports_supplier=list_ports,
        )
        try:
            self.assertTrue(dialog.port_refresh_timer.isActive())
            self.assertEqual(dialog.port_refresh_timer.interval(), 1000)
            self.assertEqual(
                [dialog.port_combo.itemData(index) for index in range(dialog.port_combo.count())],
                ["COM1"],
            )
            self.assertEqual(dialog.profile().baudrate, 57600)
            self.assertEqual(dialog.profile().line_ending, "LF")

            ports.append(
                [
                    {"device": "COM1", "description": "USB Serial A"},
                    {"device": "COM2", "description": "USB Serial B"},
                ]
            )

            self.assertTrue(dialog.refresh_ports())
            self.assertEqual(
                [dialog.port_combo.itemData(index) for index in range(dialog.port_combo.count())],
                ["COM1", "COM2"],
            )
            self.assertEqual(dialog.profile().port, "COM1")

            dialog.port_combo.setEditText("COM99")
            ports.append(
                [
                    {"device": "COM1", "description": "USB Serial A"},
                    {"device": "COM2", "description": "USB Serial B"},
                    {"device": "COM3", "description": "USB Serial C"},
                ]
            )

            self.assertTrue(dialog.refresh_ports())
            self.assertEqual(dialog.port_combo.currentText(), "COM99")
            self.assertEqual(dialog.profile().port, "COM99")
        finally:
            dialog.reject()
            dialog.deleteLater()
            self.qt.processEvents()

    def test_connection_settings_dialog_supports_lan_profile(self) -> None:
        dialog = ConnectionSettingsDialog(
            app_module.LanProfile(host="192.168.1.50", port=5025, line_ending="LF"),
            [],
            transport_kind="lan",
        )
        try:
            self.assertEqual(dialog.transport_kind(), "lan")
            self.assertEqual(dialog.connection_stack.currentIndex(), 1)
            profile = dialog.profile()

            self.assertIsInstance(profile, app_module.LanProfile)
            self.assertEqual(profile.host, "192.168.1.50")
            self.assertEqual(profile.port, 5025)
            self.assertEqual(profile.line_ending, "LF")

            serial_index = dialog.connection_type_combo.findData("serial")
            dialog.connection_type_combo.setCurrentIndex(serial_index)
            serial_profile = dialog.profile()

            self.assertEqual(dialog.transport_kind(), "serial")
            self.assertIsInstance(serial_profile, app_module.SerialProfile)
        finally:
            dialog.reject()
            dialog.deleteLater()
            self.qt.processEvents()

    def test_command_palette_filters_and_executes_selected_entry(self) -> None:
        calls: list[str] = []

        class FakeHost:
            def command_palette_entries(self) -> list[CommandPaletteEntry]:
                return [
                    CommandPaletteEntry("Connect / Disconnect", "Serial", lambda: calls.append("connect")),
                    CommandPaletteEntry("Open Command File Editor", "Command Files", lambda: calls.append("editor")),
                    CommandPaletteEntry("Clear Terminal", "Terminal", lambda: calls.append("clear")),
                ]

        dialog = CommandPaletteDialog(FakeHost())
        try:
            self.assertEqual(dialog.result_list.count(), 3)

            dialog.search_input.setText("command editor")

            self.assertEqual(dialog.result_list.count(), 1)
            self.assertEqual(dialog.filtered_entries[0].title, "Open Command File Editor")

            dialog.execute_current()
            self.qt.processEvents()

            self.assertEqual(calls, ["editor"])
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.deleteLater()

    def test_quick_command_dialog_returns_updated_command(self) -> None:
        original = QuickCommand(
            id="cmd-1",
            label="Old",
            command="*OLD",
            description="Old note",
            send_mode="Hex Bytes",
            group="Factory",
            line_ending_override="CRLF",
            favorite=True,
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
            # Editing must not silently unfavourite the command (the dialog has no
            # star control, so the favourite flag round-trips from the original).
            self.assertTrue(command.favorite)
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

    def test_quick_file_dialog_preserves_favorite_on_edit(self) -> None:
        dialog = QuickFileDialog(
            QuickFile(id="file-2", label="Boot", path="C:/scripts/boot.cpz", favorite=True)
        )
        try:
            dialog.label_input.setText("Bring-up")
            quick_file = dialog.quick_file()

            self.assertEqual(quick_file.id, "file-2")
            self.assertEqual(quick_file.label, "Bring-up")
            self.assertTrue(quick_file.favorite)
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
