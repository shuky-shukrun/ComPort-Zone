import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QLabel, QTextEdit

from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.terminal_session_controller import TerminalRenderPlan
from ComPort_Zone.terminal_view import (
    TerminalView,
    clamp_prompt_label,
    prompt_leader_text,
)
from ComPort_Zone.widgets import IntegratedTerminalEdit


COLORS = {
    "rx": "#8fe388",
    "tx": "#4fc1ff",
    "status": "#ffd166",
    "script": "#c792ea",
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

    def test_rx_after_restored_scrollback_never_reads_the_whole_document(self) -> None:
        # Saved terminal text is restored on launch. Rendering a small response
        # must not serialize that growing history for each incoming fragment.
        history = ("previous device output " + "x" * 76 + "\n") * 5000
        for widget_type in (QTextEdit, IntegratedTerminalEdit):
            with self.subTest(widget=widget_type.__name__):
                terminal = widget_type()
                count = QLabel()
                try:
                    terminal.setPlainText(history)
                    if isinstance(terminal, IntegratedTerminalEdit):
                        terminal.setText("next\ncommand")
                        terminal.setCursorPosition(2)
                    view = TerminalView(terminal, count)
                    with (
                        mock.patch.object(QTextEdit, "toPlainText", side_effect=AssertionError("full widget scan")),
                        mock.patch.object(QTextDocument, "toPlainText", side_effect=AssertionError("full document scan")),
                    ):
                        for message in ("read", " complete\nnext", " line\n"):
                            view.render_plan(
                                TerminalRenderPlan(
                                    event=SerialEvent(kind="rx", message=message),
                                    message=message,
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
                        if isinstance(terminal, IntegratedTerminalEdit):
                            self.assertEqual(terminal.text(), "next\ncommand")
                            self.assertEqual(terminal.cursorPosition(), 2)
                    self.assertEqual(terminal.toPlainText(), history + "RX  read complete\nRX  next line\n")
                finally:
                    terminal.deleteLater()
                    count.deleteLater()
                    self.qt.processEvents()

    def test_batch_preserves_timestamps_and_updates_search_and_scroll_once(self) -> None:
        terminal = IntegratedTerminalEdit()
        count = QLabel()
        view = TerminalView(terminal, count)
        first = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        expected = []
        try:
            with (
                mock.patch.object(view, "refresh_search_highlights", wraps=view.refresh_search_highlights) as search,
                mock.patch.object(terminal, "ensureCursorVisible") as scroll,
                view.batch_render(),
            ):
                for index in range(3):
                    stamp = first + timedelta(seconds=index)
                    event = SerialEvent(kind="rx", message="reply\n", timestamp=stamp)
                    view.render_plan(
                        TerminalRenderPlan(event=event, message=event.message, direction="RX", color_role="rx", stream_text=True),
                        colors=COLORS,
                        timestamps_enabled=True,
                        search_visible=True,
                        search_text="reply",
                        search_highlight="#333333",
                    )
                    expected.append(stamp.astimezone().strftime("%H:%M:%S.%f")[:-3] + " RX  reply\n")
                    self.assertFalse(terminal.document().isLayoutEnabled())
                    search.assert_not_called()
                    scroll.assert_not_called()
            search.assert_called_once_with("reply", "#333333")
            scroll.assert_called_once_with()
            self.assertTrue(terminal.document().isLayoutEnabled())
            self.assertEqual(terminal.toPlainText(), "".join(expected))
            self.assertEqual(count.text(), "3")
        finally:
            terminal.deleteLater()
            count.deleteLater()
            self.qt.processEvents()

    def test_failed_batch_restores_previous_layout_state(self) -> None:
        view, terminal, count = self.make_view()
        try:
            for enabled in (True, False):
                with self.subTest(layout_enabled=enabled):
                    terminal.document().setLayoutEnabled(enabled)
                    with self.assertRaisesRegex(ValueError, "render failed"):
                        with view.batch_render():
                            with view.batch_render():
                                view.render_plan(
                                    TerminalRenderPlan(event=SerialEvent(kind="rx", message="x"), message="x", stream_text=True),
                                    colors=COLORS,
                                    timestamps_enabled=False,
                                    search_visible=False,
                                    search_text="",
                                    search_highlight="#333333",
                                )
                                raise ValueError("render failed")
                    self.assertEqual(terminal.document().isLayoutEnabled(), enabled)
        finally:
            terminal.deleteLater()
            count.deleteLater()
            self.qt.processEvents()

    def test_batch_without_visible_output_does_not_invalidate_layout(self) -> None:
        view, terminal, count = self.make_view()
        document = terminal.document()
        try:
            with mock.patch.object(document, "setLayoutEnabled", wraps=document.setLayoutEnabled) as layout:
                with view.batch_render():
                    pass
                layout.assert_not_called()
        finally:
            terminal.deleteLater()
            count.deleteLater()
            self.qt.processEvents()

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

    def test_script_message_uses_msg_label_color_and_italic_text(self) -> None:
        view, terminal, _ = self.make_view()

        view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="script", message="Hello"),
                message="Hello",
                direction="MSG",
                color_role="script",
                ensure_line_break=True,
            ),
            colors=COLORS,
            timestamps_enabled=False,
            search_visible=False,
            search_text="",
            search_highlight="#333333",
        )

        self.assertEqual(terminal.toPlainText(), "MSG Hello\n")
        cursor = terminal.textCursor()
        cursor.setPosition(4)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        self.assertEqual(cursor.charFormat().foreground().color().name(), COLORS["script"])
        self.assertTrue(cursor.charFormat().fontItalic())

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
