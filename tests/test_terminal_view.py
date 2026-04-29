import unittest

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel, QTextEdit

from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.terminal_session_controller import TerminalRenderPlan
from ComPort_Zone.terminal_view import TerminalView


COLORS = {
    "rx": "#8fe388",
    "tx": "#4fc1ff",
    "status": "#ffd166",
    "error": "#ff6b6b",
    "default": "#d4d4d4",
}


class TerminalViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_view(self) -> tuple[TerminalView, QTextEdit, QLabel]:
        terminal = QTextEdit()
        count = QLabel("0")
        return TerminalView(terminal, count), terminal, count

    def test_render_plan_streams_rx_text_without_extra_line_breaks(self) -> None:
        view, terminal, _ = self.make_view()

        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="tx", message="SINK:CURR?"),
                message="SINK:CURR?",
                prefix="TX> ",
                color_role="tx",
                ensure_line_break=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )
        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="rx", message="1", raw=b"1"),
                message="1",
                color_role="rx",
                stream_text=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )
        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="rx", message="67.00\r\n", raw=b"67.00\r\n"),
                message="67.00\r\n",
                color_role="rx",
                stream_text=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )

        self.assertEqual(terminal.toPlainText(), "TX> SINK:CURR?\n167.00\n")

    def test_search_highlights_count_and_find_wraps(self) -> None:
        view, terminal, count = self.make_view()
        terminal.setPlainText("alpha\nbeta\nalpha")
        cursor = terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        terminal.setTextCursor(cursor)

        self.assertEqual(view.refresh_search_highlights("alpha", "#333333"), 2)
        self.assertEqual(count.text(), "2")
        self.assertTrue(view.find("alpha", backward=False))
        self.assertEqual(terminal.textCursor().selectedText(), "alpha")
        self.assertFalse(view.find("missing", backward=False))


if __name__ == "__main__":
    unittest.main()
