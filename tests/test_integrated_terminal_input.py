import unittest

from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCompleter

from ComPort_Zone.terminal_view import prompt_leader_text
from ComPort_Zone.widgets import CompletionPopupDelegate, IntegratedTerminalEdit


class IntegratedTerminalEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_committed_transcript_is_locked_while_draft_is_editable(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.show()
            terminal.setFocus()
            terminal.append_committed_text("SYS Ready\n", "#d7ba7d")
            terminal.setText("status")

            cursor = terminal.textCursor()
            cursor.setPosition(0)
            terminal.setTextCursor(cursor)
            QTest.keyClicks(terminal, "X")
            self.qt.processEvents()

            self.assertEqual(terminal.toPlainText(), "SYS Ready\n")
            self.assertEqual(terminal.text(), "statusX")
            self.assertIn(f"{terminal.prompt}statusX", terminal.display_text())
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_draft_undo_and_redo_revert_typing(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.show()
            terminal.setFocus()
            QTest.keyClicks(terminal, "measure")
            self.assertEqual(terminal.text(), "measure")

            QTest.keyClick(terminal, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "")
            QTest.keyClick(terminal, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "measure")
            # Ctrl+Shift+Z is an alternate redo.
            QTest.keyClick(terminal, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "")
            QTest.keyClick(
                terminal,
                Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
            self.assertEqual(terminal.text(), "measure")

            # The committed transcript must never be touched by draft undo.
            terminal.append_committed_text("SYS Ready\n", "#d4d4d4")
            QTest.keyClick(terminal, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.toPlainText(), "SYS Ready\n")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_programmatic_draft_swap_resets_undo_history(self) -> None:
        # History recall / clearing after send go through setText; Ctrl+Z must not
        # rewind across them into a stale command.
        terminal = IntegratedTerminalEdit()
        try:
            terminal.show()
            terminal.setFocus()
            QTest.keyClicks(terminal, "abc")
            terminal.setText("recalled")
            QTest.keyClick(terminal, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "recalled")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_ctrl_c_and_x_act_on_whole_draft_without_selection(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("freq?")
            QApplication.clipboard().clear()

            QTest.keyClick(terminal, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(QApplication.clipboard().text(), "freq?")

            QTest.keyClick(terminal, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "")
            self.assertEqual(QApplication.clipboard().text(), "freq?")

            # The whole-line cut is undoable.
            QTest.keyClick(terminal, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(terminal.text(), "freq?")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_shift_enter_adds_draft_line_and_enter_submits(self) -> None:
        terminal = IntegratedTerminalEdit()
        submitted: list[str] = []
        terminal.returnPressed.connect(lambda: submitted.append(terminal.text()))
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("status")

            QTest.keyClick(terminal, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
            QTest.keyClicks(terminal, "read")
            QTest.keyClick(terminal, Qt.Key.Key_Return)
            self.qt.processEvents()

            self.assertEqual(terminal.text(), "status\nread")
            self.assertEqual(submitted, ["status\nread"])

            cursor = terminal.textCursor()
            cursor.setPosition(terminal.display_text().index(terminal.prompt))
            terminal.setTextCursor(cursor)
            QTest.keyClick(terminal, Qt.Key.Key_Backspace)
            self.assertEqual(terminal.text(), "status\nread")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_completion_keeps_draft_text_in_prompt_color(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.set_terminal_colors(prompt="#4fc1ff", draft="#d4d4d4")
            terminal.setText("SIN")

            terminal.insert_completion("SINK:CURR?")

            display_text = terminal.display_text()
            cursor = QTextCursor(terminal.document())
            cursor.setPosition(display_text.index("SINK"))
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)

            self.assertEqual(terminal.text(), "SINK:CURR?")
            self.assertEqual(cursor.charFormat().foreground().color().name().lower(), "#4fc1ff")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_enter_submits_draft_without_accepting_visible_completion(self) -> None:
        terminal = IntegratedTerminalEdit()
        model = QStringListModel(["volt 100"], terminal)
        completer = QCompleter(model, terminal)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        submitted: list[str] = []
        terminal.setCompleter(completer)
        terminal.returnPressed.connect(lambda: submitted.append(terminal.text()))
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("volt:acdc 100")
            terminal.show_completions(forced=True)
            self.qt.processEvents()

            self.assertTrue(completer.popup().isVisible())
            QTest.keyClick(terminal, Qt.Key.Key_Return)
            self.qt.processEvents()

            self.assertEqual(submitted, ["volt:acdc 100"])
            self.assertEqual(terminal.text(), "volt:acdc 100")
            self.assertFalse(completer.popup().isVisible())
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_tab_accepts_visible_completion_without_submitting(self) -> None:
        terminal = IntegratedTerminalEdit()
        model = QStringListModel(["volt 100"], terminal)
        completer = QCompleter(model, terminal)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        submitted: list[str] = []
        terminal.setCompleter(completer)
        terminal.returnPressed.connect(lambda: submitted.append(terminal.text()))
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("volt:acdc 100")
            terminal.show_completions(forced=True)
            self.qt.processEvents()

            self.assertTrue(completer.popup().isVisible())
            QTest.keyClick(terminal, Qt.Key.Key_Tab)
            self.qt.processEvents()

            self.assertEqual(submitted, [])
            self.assertEqual(terminal.text(), "volt:acdc volt 100")
            self.assertFalse(completer.popup().isVisible())
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_menu_replacement_can_edit_committed_transcript(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.append_committed_text("OK\n", "#d4d4d4")
            terminal.setText("draft")
            cursor = QTextCursor(terminal.document())
            cursor.setPosition(0)
            cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
            terminal.setTextCursor(cursor)

            self.assertTrue(terminal.replace_selection_from_menu("4F 4B"))

            self.assertEqual(terminal.toPlainText(), "4F 4B\n")
            self.assertEqual(terminal.text(), "draft")
            self.assertIn(f"{terminal.prompt}draft", terminal.display_text())
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_set_prompt_text_swaps_prompt_keeping_transcript_colors_and_draft(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.set_terminal_colors(prompt="#4fc1ff", draft="#d4d4d4")
            terminal.append_committed_runs(
                [
                    ("12:00:00.000 ", "#5e6a7e"),
                    ("TX  ", "#4fc1ff"),
                    ("*IDN?\n", "#9cdcfe"),
                ]
            )
            terminal.setText("volt 1")
            terminal.setCursorPosition(4)

            new_prompt = prompt_leader_text("COM3", timestamps_enabled=True)
            terminal.set_prompt_text(new_prompt)

            display = terminal.display_text()
            self.assertTrue(display.startswith("12:00:00.000 TX  *IDN?\n"))
            self.assertIn(f"{new_prompt}volt 1", display)
            self.assertEqual(terminal.prompt, new_prompt)
            # Draft text + caret offset survive the prompt swap.
            self.assertEqual(terminal.text(), "volt 1")
            self.assertEqual(terminal.cursorPosition(), 4)

            # The transcript timestamp keeps its gray ink (not flattened to draft).
            stamp_cursor = QTextCursor(terminal.document())
            stamp_cursor.setPosition(display.index("12:00"))
            stamp_cursor.movePosition(
                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1
            )
            self.assertEqual(
                stamp_cursor.charFormat().foreground().color().name().lower(), "#5e6a7e"
            )
            # The new prompt renders in the prompt colour.
            prompt_cursor = QTextCursor(terminal.document())
            prompt_cursor.setPosition(display.index("COM3"))
            prompt_cursor.movePosition(
                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1
            )
            self.assertEqual(
                prompt_cursor.charFormat().foreground().color().name().lower(), "#4fc1ff"
            )
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_placeholder_text_round_trips(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.setPlaceholderText("type a command — ↑ recalls history")
            self.assertEqual(
                terminal.placeholderText(), "type a command — ↑ recalls history"
            )
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_ghost_suffix_previews_untyped_completion(self) -> None:
        terminal = IntegratedTerminalEdit()
        model = QStringListModel(["SYST:ERR?"], terminal)
        completer = QCompleter(model, terminal)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        terminal.setCompleter(completer)
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("SYST")
            terminal.show_completions(forced=True)
            self.qt.processEvents()

            self.assertTrue(completer.popup().isVisible())
            self.assertEqual(terminal._ghost_suffix(), ":ERR?")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_ghost_suffix_hidden_when_completion_does_not_extend_token(self) -> None:
        terminal = IntegratedTerminalEdit()
        model = QStringListModel(["VOLT:DC?"], terminal)
        completer = QCompleter(model, terminal)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        terminal.setCompleter(completer)
        try:
            terminal.show()
            terminal.setFocus()
            terminal.setText("DC")
            terminal.show_completions(forced=True)
            self.qt.processEvents()

            # A contains-match still lists the item, but it isn't a clean inline
            # extension of "DC", so no ghost is drawn.
            self.assertTrue(completer.popup().isVisible())
            self.assertEqual(terminal._ghost_suffix(), "")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_completion_delegate_widens_for_and_carries_descriptions(self) -> None:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QStyleOptionViewItem

        model = QStringListModel(["*IDN?", "PLAIN"])
        delegate = CompletionPopupDelegate()
        delegate.set_descriptions({"*IDN?": "identify the instrument"})
        option = QStyleOptionViewItem()
        option.font = QFont("Consolas", 11)

        with_description = delegate.sizeHint(option, model.index(0, 0))
        without_description = delegate.sizeHint(option, model.index(1, 0))
        # The row carrying a description reserves more width for the grey column.
        self.assertGreater(with_description.width(), without_description.width())

    def test_completion_popup_matches_terminal_font_and_design(self) -> None:
        terminal = IntegratedTerminalEdit()
        model = QStringListModel(["*IDN?", "SYST:ERR?"], terminal)
        completer = QCompleter(model, terminal)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        terminal.setCompleter(completer)
        terminal.set_completion_descriptions({"*IDN?": "identify"})
        terminal.set_completion_colors(
            text="#ffffff",
            description="#8a93a6",
            selection="#264f78",
            hover="#222631",
            background="#141821",
            border="#2a2f3a",
        )
        try:
            terminal.show()
            terminal.setFocus()
            font = terminal.font()
            font.setPointSize(18)
            terminal.setFont(font)
            terminal.setText("IDN")
            terminal.show_completions(forced=True)
            self.qt.processEvents()

            popup = completer.popup()
            self.assertTrue(popup.isVisible())
            self.assertIsInstance(popup.itemDelegate(), CompletionPopupDelegate)
            # Popup font tracks the terminal font size setting.
            self.assertEqual(popup.font().pointSize(), 18)
            # Themed frame: object name + the panel background colour are applied.
            self.assertEqual(popup.objectName(), "completionPopup")
            self.assertIn("#141821", popup.styleSheet())
        finally:
            terminal.deleteLater()
            self.qt.processEvents()

    def test_menu_replacement_does_not_cross_prompt_boundary(self) -> None:
        terminal = IntegratedTerminalEdit()
        try:
            terminal.append_committed_text("OK\n", "#d4d4d4")
            cursor = QTextCursor(terminal.document())
            cursor.setPosition(0)
            cursor.setPosition(len(terminal.display_text()), QTextCursor.MoveMode.KeepAnchor)
            terminal.setTextCursor(cursor)

            self.assertFalse(terminal.replace_selection_from_menu("blocked"))
            self.assertEqual(terminal.toPlainText(), "OK\n")
        finally:
            terminal.deleteLater()
            self.qt.processEvents()


if __name__ == "__main__":
    unittest.main()
