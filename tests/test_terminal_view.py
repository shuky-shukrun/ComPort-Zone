import unittest

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel, QTextEdit

from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.terminal_session_controller import TerminalRenderPlan
from ComPort_Zone.terminal_view import (
    TerminalView,
    clamp_prompt_label,
    prompt_leader_text,
)


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
                direction="TX",
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
                direction="RX",
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
                direction="RX",
                color_role="rx",
                stream_text=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )

        self.assertEqual(terminal.toPlainText(), "TX  SINK:CURR?\nRX  167.00\n")

    def test_render_plan_streams_rx_hex_with_spaces_between_chunks(self) -> None:
        view, terminal, _ = self.make_view()

        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="rx", message="01", raw=b"\x01"),
                message="01",
                color_role="rx",
                stream_text=True,
                stream_separator=" ",
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )
        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="rx", message="02 03", raw=b"\x02\x03"),
                message="02 03",
                color_role="rx",
                stream_text=True,
                stream_separator=" ",
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )

        self.assertEqual(terminal.toPlainText(), "01 02 03")

    def test_render_plan_keeps_progress_dots_on_one_line(self) -> None:
        view, terminal, _ = self.make_view()

        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="progress", message="Auto-reconnect armed. Retrying every 1000 ms."),
                message="Auto-reconnect armed. Retrying every 1000 ms.",
                prefix="SYS ",
                direction="SYS",
                color_role="status",
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
                event=SerialEvent(kind="progress", message="."),
                message=".",
                prefix="SYS ",
                direction="SYS",
                color_role="status",
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
                event=SerialEvent(kind="progress", message="."),
                message=".",
                prefix="SYS ",
                direction="SYS",
                color_role="status",
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
                event=SerialEvent(kind="status", message="Auto-reconnect succeeded."),
                message="Auto-reconnect succeeded.",
                prefix="SYS ",
                direction="SYS",
                color_role="status",
                ensure_line_break=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )

        self.assertEqual(
            terminal.toPlainText(),
            "SYS Auto-reconnect armed. Retrying every 1000 ms...\nSYS Auto-reconnect succeeded.\n",
        )

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


class PromptLeaderTests(unittest.TestCase):
    def test_prompt_leader_aligns_chevron_under_direction_column(self) -> None:
        # "<tab name> filling the 12-char timestamp column> <'>' in the dir column>"
        leader = prompt_leader_text("COM3", timestamps_enabled=True)
        self.assertEqual(len(leader), 17)
        self.assertTrue(leader.startswith("COM3"))
        # '>' sits where the TX/RX direction column begins (after the 13-char stamp).
        self.assertEqual(leader[13], ">")
        self.assertTrue(leader.endswith(" "))

    def test_prompt_leader_drops_tab_name_when_timestamps_off(self) -> None:
        self.assertEqual(prompt_leader_text("COM3", timestamps_enabled=False), ">  " + " ")
        self.assertNotIn("COM3", prompt_leader_text("COM3", timestamps_enabled=False))

    def test_prompt_leader_is_chevron_only_without_a_label(self) -> None:
        self.assertEqual(prompt_leader_text("", timestamps_enabled=True), ">  " + " ")

    def test_prompt_label_clamped_to_timestamp_width(self) -> None:
        clamped = clamp_prompt_label("Oscilloscope bench #1")
        self.assertEqual(len(clamped), 12)
        self.assertTrue(clamped.endswith("…"))
        # A label that already fits keeps its exact text.
        self.assertEqual(clamp_prompt_label("COM3"), "COM3")
        leader = prompt_leader_text("Oscilloscope bench #1", timestamps_enabled=True)
        self.assertEqual(len(leader), 17)
        self.assertIn("…", leader)


if __name__ == "__main__":
    unittest.main()
