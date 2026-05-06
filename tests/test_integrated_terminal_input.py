import unittest

from PySide6.QtCore import Qt
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


if __name__ == "__main__":
    unittest.main()
