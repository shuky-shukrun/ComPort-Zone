import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ComPort_Zone.widgets import IntegratedTerminalEdit


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
            self.assertIn("TX> statusX", terminal.display_text())
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
            cursor.setPosition(terminal.display_text().index("TX> "))
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
            self.assertIn("TX> draft", terminal.display_text())
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
