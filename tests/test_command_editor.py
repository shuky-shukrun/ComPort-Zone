import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from ComPort_Zone.command_editor import CommandFileEditorDialog
from ComPort_Zone.command_editor_core import CommandEditorSources
from ComPort_Zone.command_run_targets import CommandRunTarget, CommandRunTargetService
from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.themes import THEMES


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

    def test_editor_suggestions_follow_active_quick_command_group_visibility(self) -> None:
        sources = CommandEditorSources(
            quick_commands=[
                QuickCommand(label="Source power", command="POW 100", group="Source"),
                QuickCommand(label="Sink power", command="SINK:POW 50", group="Sink"),
            ],
            quick_command_hidden_groups=["Source"],
        )

        suggestions = sources.suggestions("", "PO")

        self.assertIn("SINK:POW 50", suggestions)
        self.assertNotIn("POW 100", suggestions)
        self.assertEqual(sources.validation_issues("POW 100"), [])

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

            QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Tab)
            self.qt.processEvents()
            self.assertEqual(dialog.text(), "SINK:CURR?")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_editor_undo_redo_works_with_line_spacing_applied(self) -> None:
        # Regression: the line-spacing controller reformatted blocks on every
        # contentsChange, which silently killed Ctrl+Z in the editor.
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.editor.show()
            dialog.editor.setFocus()
            dialog.editor.set_line_spacing(115)
            QTest.keyClicks(dialog.editor, "hello")
            self.assertEqual(dialog.text(), "hello")

            QTest.keyClick(dialog.editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dialog.text(), "")
            QTest.keyClick(
                dialog.editor,
                Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
            self.assertEqual(dialog.text(), "hello")
            # Spacing is still in force on the typed block.
            self.assertEqual(
                dialog.editor.document().findBlockByNumber(0).blockFormat().lineHeight(), 115.0
            )
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_ctrl_c_x_v_operate_on_whole_line_without_selection(self) -> None:
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.editor.show()
            dialog.editor.setFocus()
            dialog.setPlainText("alpha\nbeta")
            cursor = dialog.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            dialog.editor.setTextCursor(cursor)
            QApplication.clipboard().clear()

            # Copy the whole current line (with newline) when nothing is selected.
            QTest.keyClick(dialog.editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(QApplication.clipboard().text(), "alpha\n")

            # Cut removes the whole line.
            QTest.keyClick(dialog.editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dialog.text(), "beta")

            # Whole-line paste drops the line back in above the current one.
            QTest.keyClick(dialog.editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dialog.text(), "alpha\nbeta")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_enter_dismisses_completion_and_inserts_newline(self) -> None:
        # Matches the terminal: only Tab accepts; Enter closes the popup and adds a
        # newline (keyPressEvent path, key delivered to the editor).
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.editor.show()
            dialog.editor.setFocus()
            QTest.keyClicks(dialog.editor, "SIN")
            self.qt.processEvents()
            self.assertTrue(dialog.completer.popup().isVisible())

            QTest.keyClick(dialog.editor, Qt.Key.Key_Return)
            self.qt.processEvents()

            self.assertFalse(dialog.completer.popup().isVisible())
            self.assertEqual(dialog.text(), "SIN\n")
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_enter_on_popup_dismisses_completion_and_inserts_newline(self) -> None:
        # Same policy via the popup's event filter (key delivered to the popup).
        dialog = CommandFileEditorDialog(sources=CommandEditorSources())
        try:
            dialog.editor.show()
            dialog.editor.setFocus()
            QTest.keyClicks(dialog.editor, "SIN")
            self.qt.processEvents()
            self.assertTrue(dialog.completer.popup().isVisible())

            QTest.keyClick(dialog.completer.popup(), Qt.Key.Key_Return)
            self.qt.processEvents()

            self.assertFalse(dialog.completer.popup().isVisible())
            self.assertEqual(dialog.text(), "SIN\n")
        finally:
            dialog._dirty = False
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
        calls: list[tuple[str, int, object, str]] = []
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            run_target_service=CommandRunTargetService(
                targets_supplier=lambda: [CommandRunTarget(42, "Connected | COM42 | 115200 8N1")],
                run_callback=lambda request, target_id: calls.append(
                    (request.text, target_id, request.path, request.display_name)
                ),
            ),
        )
        try:
            dialog.setPlainText("SEND *IDN?")
            dialog.refresh_run_targets()
            self.assertEqual(dialog.run_target_combo.currentData(), 42)

            dialog.send_to_selected_target()

            self.assertEqual(calls, [("SEND *IDN?", 42, None, "Untitled")])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_editor_applies_light_theme_line_and_highlight_colors(self) -> None:
        theme = THEMES["Bench Light"]
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            theme_palette=theme,
        )
        try:
            self.assertEqual(dialog.editor.line_number_background.name().lower(), theme.surface_alt.lower())
            self.assertEqual(dialog.editor.line_number_foreground.name().lower(), theme.muted.lower())
            self.assertEqual(dialog.editor.current_line_background.name().lower(), theme.chip.lower())
            self.assertEqual(dialog.editor.search_match_background.name().lower(), theme.search_highlight.lower())
            self.assertEqual(dialog.editor.search_current_background.name().lower(), theme.accent_soft.lower())
            self.assertEqual(dialog.editor.search_match_foreground.name().lower(), theme.text.lower())
        finally:
            dialog.close()
            dialog.deleteLater()

    def _description_on_line(self, dialog, line_index: int) -> str:
        editor = dialog.editor
        block = editor.document().findBlockByNumber(line_index)
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        editor.setTextCursor(cursor)
        return editor._current_line_description()

    def test_inline_description_hint_resolves_saved_command_on_current_line(self) -> None:
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(
                quick_commands=[
                    QuickCommand(label="Identity", command="*IDN?", description="Identify the instrument"),
                    QuickCommand(label="DC volts", command="MEAS:VOLT:DC?", description="Measure DC voltage"),
                    QuickCommand(label="No note", command="OUTP 1", description=""),
                ]
            ),
        )
        try:
            dialog.setPlainText("// header\n*IDN?\nSEND MEAS:VOLT:DC?\nWAIT 100\nOUTP 1\nUNKNOWN?\n")

            self.assertEqual(self._description_on_line(dialog, 1), "Identify the instrument")  # bare command
            self.assertEqual(self._description_on_line(dialog, 2), "Measure DC voltage")       # SEND <command>
            self.assertEqual(self._description_on_line(dialog, 0), "")  # comment line
            self.assertEqual(self._description_on_line(dialog, 3), "")  # WAIT directive
            self.assertEqual(self._description_on_line(dialog, 4), "")  # saved but no description
            self.assertEqual(self._description_on_line(dialog, 5), "")  # unknown command
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_inline_description_hint_matches_command_case_insensitively(self) -> None:
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(
                quick_commands=[QuickCommand(label="Identity", command="*IDN?", description="Identify")],
            ),
        )
        try:
            dialog.setPlainText("*idn?\n")
            self.assertEqual(self._description_on_line(dialog, 0), "Identify")
        finally:
            dialog._dirty = False
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
            self.assertTrue(dialog.search_overlay.isVisible())
            self.assertFalse(dialog.replace_input.isVisible())
            self.assertFalse(dialog.search_overlay.replace_one_button.isVisible())
            self.assertFalse(dialog.search_overlay.replace_all_button.isVisible())

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
            dialog.show()
            dialog.setPlainText("SEND VOLT?\nSEND CURR?\nSEND VOLT?\n")
            dialog.show_find_bar()
            self.qt.processEvents()
            self.assertFalse(dialog.search_overlay.replace_one_button.isVisible())
            dialog.show_replace_bar()
            self.qt.processEvents()
            self.assertTrue(dialog.replace_input.isVisible())
            self.assertTrue(dialog.search_overlay.replace_one_button.isVisible())
            self.assertTrue(dialog.search_overlay.replace_all_button.isVisible())
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

    def test_embedded_editor_minimum_width_fits_a_workspace_pane(self) -> None:
        # The embedded editor must shrink at least as small as a split pane's floor,
        # else a squeezed pane clips the command bar's Run button off the right edge.
        from ComPort_Zone.ui.tokens import WORKSPACE_PANE_MIN_W

        dialog = CommandFileEditorDialog(sources=CommandEditorSources(), embedded=True)
        try:
            self.assertLessEqual(dialog.minimumWidth(), WORKSPACE_PANE_MIN_W)
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_command_bar_collapses_to_run_button_when_narrow(self) -> None:
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            run_target_service=CommandRunTargetService(
                targets_supplier=lambda: [CommandRunTarget(7, "COM7 · Serial")],
                run_callback=lambda request, target_id: True,
            ),
        )
        try:
            dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            dialog.setMinimumSize(150, 150)  # simulate being squeezed inside a narrow pane
            dialog.show()
            dialog.refresh_run_targets()
            self.qt.processEvents()

            dialog.resize(900, 480)
            self.qt.processEvents()
            self.assertFalse(dialog.command_overflow_button.isVisible())
            self.assertTrue(dialog.warn_unknown.isVisible())
            self.assertTrue(dialog.run_target_combo.isVisible())

            dialog.resize(300, 480)
            for _ in range(4):
                self.qt.processEvents()
            # Only the Run button (plus ⋯) survives; everything else folds away.
            self.assertTrue(dialog.run_button.isVisible())
            self.assertTrue(dialog.command_overflow_button.isVisible())
            self.assertFalse(dialog.warn_unknown.isVisible())
            self.assertFalse(dialog.wrap_toggle.isVisible())
            self.assertFalse(dialog.run_target_combo.isVisible())

            dialog._build_command_overflow_menu()
            labels = [action.text() for action in dialog._command_overflow_menu.actions()]
            self.assertIn("Warn unknown commands", labels)
            self.assertIn("Wrap long lines", labels)
            self.assertIn("Run on", labels)
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()

    def test_editor_command_bar_has_green_run_wrap_and_send_to(self) -> None:
        dialog = CommandFileEditorDialog(
            sources=CommandEditorSources(),
            run_target_service=CommandRunTargetService(
                targets_supplier=lambda: [CommandRunTarget(42, "COM42 · Serial")],
                run_callback=lambda request, target_id: True,
            ),
        )
        try:
            dialog.show()
            self.qt.processEvents()
            # The Run button is the green-themed action, kept in the bottom bar.
            self.assertEqual(dialog.run_button.text(), "Run")
            self.assertEqual(dialog.run_button.objectName(), "editorRunButton")
            # Line-wrap toggle + send-to combo share the bottom command bar.
            command_bar = dialog.run_button.parentWidget()
            self.assertIs(dialog.wrap_toggle.parentWidget(), command_bar)
            self.assertIs(dialog.run_target_combo.parentWidget(), command_bar)
            self.assertTrue(dialog.wrap_toggle.isChecked())  # wraps by default
            # The shrunk send-to label flows straight through from the target.
            self.assertEqual(dialog.run_target_combo.itemText(0), "COM42 · Serial")
            # Font +/- buttons are gone from the editor chrome (Ctrl+wheel zoom).
            self.assertEqual(dialog.findChildren(QPushButton, "editorFontSizeButton"), [])
        finally:
            dialog._dirty = False
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
