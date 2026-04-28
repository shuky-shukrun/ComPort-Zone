import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ComPort_Zone.command_editor import CommandEditorSources, CommandFileEditorDialog
from ComPort_Zone.models import QuickCommand, QuickFile


class CommandEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_validation_accepts_known_command_with_suffix_and_flags_unknown(self) -> None:
        sources = CommandEditorSources(
            history_commands=["OUTP 1"],
            quick_commands=[QuickCommand(label="Sink current", command="SINK:CURR 4.5", group="Power")],
        )

        issues = sources.validation_issues("SINK:CURR 4.5\nUNKNOWN:CMD 1\nWAIT 5\nEXPECT OK")

        self.assertEqual([issue.message for issue in issues], ["Unknown command: UNKNOWN:CMD"])

    def test_suggestions_include_dsl_history_document_words_and_filtered_quick_commands(self) -> None:
        sources = CommandEditorSources(
            history_commands=["MEAS:VOLT?"],
            quick_commands=[
                QuickCommand(label="Power", command="POW 100", group="Source"),
                QuickCommand(label="Sink Power", command="SINK:POW 50", group="Sink"),
            ],
            quick_group_filter="Sink",
        )

        suggestions = sources.suggestions("MEAS:CURR?\n", "PO")

        self.assertIn("SINK:POW 50", suggestions)
        self.assertIn("MEAS:CURR?", sources.suggestions("MEAS:CURR?\n", "MEAS"))
        self.assertNotIn("POW 100", suggestions)
        self.assertIn("WAIT", sources.suggestions("", "WA"))
        self.assertIn("MEAS:VOLT?", sources.suggestions("", "MEAS"))
        self.assertNotIn("PO", sources.suggestions("PO", "PO", exclude="PO"))
        self.assertEqual(sources.suggestions("")[:4], ["SEND", "WAIT", "HEX", "EXPECT"])

    def test_editor_autocomplete_excludes_active_token_and_accepts_current_completion(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.setPlainText("SIN")
            dialog.editor.moveCursor(QTextCursor.MoveOperation.End)

            dialog.editor.show_completions()
            self.assertEqual(dialog.completer.currentCompletion(), "SINK:CURR")

            dialog.editor.accept_current_completion()
            self.assertEqual(dialog.text(), "SINK:CURR")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_autocomplete_arrow_navigation_accepts_selected_completion(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.editor.show()
            dialog.editor.setFocus()
            QTest.keyClicks(dialog.editor, "SIN")
            self.qt.processEvents()
            self.assertEqual(dialog.completer.currentCompletion(), "SINK:CURR")

            QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Down)
            self.qt.processEvents()
            self.assertEqual(dialog.completer.popup().currentIndex().data(), "SINK:CURR?")

            QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Return)
            self.qt.processEvents()
            self.assertEqual(dialog.text(), "SINK:CURR?")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_editor_run_buffer_uses_unsaved_text(self) -> None:
        calls: list[tuple[str, object]] = []
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            run_callback=lambda text, path: calls.append((text, path)),
        )
        try:
            dialog.setPlainText("SEND *IDN?\nEXPECT OK")
            dialog.run_buffer()

            self.assertEqual(calls, [("SEND *IDN?\nEXPECT OK", None)])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_workspace_side_panel_inserts_commands_and_opens_quick_files(self) -> None:
        script_path = Path(__file__).with_name("_tmp_editor_quick_file.txt")
        script_path.write_text("SEND SYST:ERR:ALL?\n", encoding="utf-8")
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(
                quick_commands=[
                    QuickCommand(id="cmd-1", label="Identity", command="*IDN?", group="General"),
                    QuickCommand(id="cmd-2", label="Wake", command="55 AA", send_mode="Hex Bytes", group="General"),
                ]
            ),
            quick_files_supplier=lambda: [QuickFile(id="file-1", label="Errors", path=str(script_path))],
            show_workspace_side_panel=True,
        )
        try:
            dialog.quick_command_list.setCurrentRow(0)
            dialog.insert_selected_quick_command()
            self.assertEqual(dialog.text(), "*IDN?")

            dialog.quick_command_list.setCurrentRow(1)
            dialog.editor.moveCursor(QTextCursor.MoveOperation.End)
            dialog.insert_text_at_cursor("\n")
            dialog.insert_selected_quick_command()
            self.assertEqual(dialog.text(), "*IDN?\nHEX 55 AA")

            dialog.confirm_save_or_discard_if_dirty = lambda: True
            dialog.quick_file_list.setCurrentRow(0)
            dialog.open_selected_quick_file()
            self.assertEqual(dialog.text(), "SEND SYST:ERR:ALL?\n")
            self.assertEqual(dialog.path, script_path)
        finally:
            dialog.close()
            dialog.deleteLater()
            script_path.unlink(missing_ok=True)

    def test_editor_send_target_bar_runs_selected_connected_port(self) -> None:
        calls: list[tuple[object, int]] = []
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            run_targets_supplier=lambda: [(42, "Connected | COM42 | 115200 8N1")],
            run_target_callback=lambda editor, target_id: calls.append((editor.text(), target_id)),
        )
        try:
            dialog.setPlainText("SEND *IDN?")
            dialog.refresh_run_targets()
            self.assertEqual(dialog.run_target_combo.currentData(), 42)

            dialog.send_to_selected_target()

            self.assertEqual(calls, [("SEND *IDN?", 42)])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_editor_ctrl_s_saves_current_file(self) -> None:
        script_path = Path(__file__).with_name("_tmp_editor_save_shortcut.txt")
        script_path.write_text("SEND old\n", encoding="utf-8")
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            path=script_path,
        )
        try:
            dialog.show()
            dialog.setPlainText("SEND new\n")
            dialog.editor.setFocus()
            QTest.keyClick(dialog.editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()

            self.assertEqual(script_path.read_text(encoding="utf-8"), "SEND new\n")
            self.assertFalse(dialog.is_dirty())
        finally:
            dialog.close()
            dialog.deleteLater()
            script_path.unlink(missing_ok=True)

    def test_editor_find_bar_shortcut_highlights_and_navigates_matches(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.show()
            dialog.setPlainText("SEND VOLT?\nSEND CURR?\nSEND VOLT?\n")
            dialog.editor.setFocus()

            QTest.keyClick(dialog.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()
            self.assertTrue(dialog.find_replace_bar.isVisible())

            dialog.search_input.setText("volt")
            self.qt.processEvents()
            self.assertEqual(dialog.search_count_label.text(), "1/2")
            self.assertEqual(dialog.editor.textCursor().selectedText(), "VOLT")

            dialog.find_next()
            self.assertEqual(dialog.search_count_label.text(), "2/2")
            self.assertEqual(dialog.editor.textCursor().selectedText(), "VOLT")

            dialog.find_previous()
            self.assertEqual(dialog.search_count_label.text(), "1/2")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_replace_current_and_replace_all(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.setPlainText("SEND VOLT?\nSEND CURR?\nSEND VOLT?\n")
            dialog.show_replace_bar()
            dialog.search_input.setText("SEND")
            dialog.replace_input.setText("EXPECT")
            self.qt.processEvents()

            dialog.replace_current()
            self.assertEqual(dialog.text(), "EXPECT VOLT?\nSEND CURR?\nSEND VOLT?\n")

            dialog.replace_all()
            self.assertEqual(dialog.text(), "EXPECT VOLT?\nEXPECT CURR?\nEXPECT VOLT?\n")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_case_sensitive_find(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.setPlainText("SEND volt?\nSEND VOLT?\n")
            dialog.show_find_bar()
            dialog.case_sensitive_check.setChecked(True)
            dialog.search_input.setText("volt")
            self.qt.processEvents()

            self.assertEqual(dialog.search_count_label.text(), "1/1")
            self.assertEqual(dialog.editor.textCursor().selectedText(), "volt")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
